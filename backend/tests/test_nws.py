import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.ingestion import nws
from app.routing.beliefs import log_odds

FIXTURES = Path(__file__).parent / "fixtures"
ALERTS_FIXTURE = FIXTURES / "nws_alerts.json"
ZONES_FIXTURE = FIXTURES / "nws_zones.json"

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def alert_features() -> list[dict]:
    return load(ALERTS_FIXTURE)["features"]


def zone_geometries() -> dict:
    return {zone_id: feature["geometry"] for zone_id, feature in load(ZONES_FIXTURE).items()}


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for doc in self._docs:
            yield doc


def fake_db(docs=()):
    collection = SimpleNamespace(find=lambda *args, **kwargs: FakeCursor(docs))
    return SimpleNamespace(intel_cache=collection)


class QueryTests(unittest.TestCase):
    def test_alerts_cover_the_miami_dade_forecast_zones(self):
        self.assertEqual(nws.MIAMI_DADE_ZONES, ("FLZ073", "FLZ074", "FLZ173", "FLZ174"))
        params = nws.alerts_params()
        for zone_id in nws.MIAMI_DADE_ZONES:
            self.assertIn(zone_id, params["zone"])

    def test_user_agent_fallback_is_descriptive(self):
        self.assertIn("MAPAY", nws.FALLBACK_USER_AGENT)
        self.assertIn("@", nws.FALLBACK_USER_AGENT)


class CertaintyTests(unittest.TestCase):
    def test_probability_orders_observed_above_likely_above_possible(self):
        observed = nws.certainty_probability({"properties": {"certainty": "Observed"}})
        likely = nws.certainty_probability({"properties": {"certainty": "Likely"}})
        possible = nws.certainty_probability({"properties": {"certainty": "Possible"}})
        self.assertGreater(observed, likely)
        self.assertGreater(likely, possible)
        self.assertEqual(possible, 0.5)

    def test_unknown_certainty_uses_default(self):
        self.assertEqual(nws.certainty_probability({"properties": {}}),
                         nws.DEFAULT_CERTAINTY_PROBABILITY)

    def test_severity_maps_to_numeric_scale(self):
        self.assertEqual(nws.severity_level({"properties": {"severity": "Extreme"}}), 5)
        self.assertEqual(nws.severity_level({"properties": {"severity": "Severe"}}), 4)
        self.assertEqual(nws.severity_level({"properties": {"severity": "Unknown"}}), 1)


class ActivityTests(unittest.TestCase):
    def test_cancelled_and_expired_alerts_are_not_active(self):
        self.assertTrue(nws.alert_is_active({"properties": {"ends": "2099-01-01T00:00:00+00:00"}}, NOW))
        self.assertTrue(nws.alert_is_active({"properties": {}}, NOW))
        self.assertFalse(nws.alert_is_active({"properties": {"messageType": "Cancel",
                                                             "ends": "2099-01-01T00:00:00+00:00"}}, NOW))
        self.assertFalse(nws.alert_is_active({"properties": {"ends": "2020-01-01T00:00:00+00:00"}}, NOW))


class ParseTests(unittest.TestCase):
    def test_alert_with_geometry_keeps_its_polygon(self):
        feature = alert_features()[0]
        alert = nws.parse_alert(feature, {})
        self.assertEqual(alert["hazard_id"], nws.alert_hazard_id(feature["properties"]["id"]))
        self.assertTrue(alert["hazard_id"].startswith("nws:"))
        self.assertEqual(alert["kind"], "weather")
        self.assertEqual(alert["geometry"], feature["geometry"])
        self.assertEqual(alert["properties"]["probability"], 0.95)
        self.assertEqual(alert["properties"]["severity"], 4)
        self.assertEqual(alert["properties"]["expires"], "2026-09-26T23:00:00-04:00")
        self.assertEqual(alert["properties"]["event"], "Flood Warning")

    def test_zone_alert_gets_polygon_from_affected_zones(self):
        feature = alert_features()[1]
        alert = nws.parse_alert(feature, zone_geometries())
        self.assertEqual(alert["geometry"], zone_geometries()["FLZ173"])
        self.assertEqual(alert["properties"]["certainty"], "Likely")

    def test_multiple_affected_zones_union_into_multipolygon(self):
        feature = alert_features()[2]
        alert = nws.parse_alert(feature, zone_geometries())
        self.assertEqual(alert["geometry"]["type"], "MultiPolygon")
        self.assertEqual(len(alert["geometry"]["coordinates"]), 2)
        self.assertEqual(alert["properties"]["probability"], 0.5)
        self.assertEqual(alert["properties"]["severity"], 3)

    def test_unplaceable_alert_is_skipped(self):
        self.assertIsNone(nws.parse_alert(alert_features()[5], zone_geometries()))


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_active_alerts_sends_zones_and_user_agent(self):
        captured = {}

        def handler(request):
            captured["params"] = request.url.params
            captured["user_agent"] = request.headers.get("user-agent")
            return httpx.Response(200, json=load(ALERTS_FIXTURE))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            payload = await nws.fetch_active_alerts(client=client, user_agent="MAPAY test (a@b.c)")
        self.assertEqual(payload["type"], "FeatureCollection")
        self.assertEqual(captured["params"]["zone"], ",".join(nws.MIAMI_DADE_ZONES))
        self.assertEqual(captured["user_agent"], "MAPAY test (a@b.c)")

    async def test_fetch_zone_geometry_reads_the_zone_polygon(self):
        zone = load(ZONES_FIXTURE)["FLZ074"]
        captured = {}

        def handler(request):
            captured["url"] = str(request.url)
            return httpx.Response(200, json=zone)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            geometry = await nws.fetch_zone_geometry("FLZ074", client=client, user_agent="MAPAY test")
        self.assertEqual(geometry, zone["geometry"])
        self.assertIn("/zones/forecast/FLZ074", captured["url"])

    async def test_zone_without_geometry_returns_none(self):
        def handler(request):
            return httpx.Response(200, json={"type": "Feature", "geometry": None, "properties": {}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            self.assertIsNone(await nws.fetch_zone_geometry("FLZ999", client=client, user_agent="t"))


class CacheTests(unittest.IsolatedAsyncioTestCase):
    def test_cache_roundtrip_and_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nws_zones.json"
            zones = zone_geometries()
            self.assertFalse(nws.cache_is_fresh(path))
            nws.save_zone_cache(zones, path)
            self.assertEqual(nws.load_zone_cache(path), zones)
            self.assertTrue(nws.cache_is_fresh(path, NOW))
            stale = (NOW - timedelta(days=60)).timestamp()
            os.utime(path, (stale, stale))
            self.assertFalse(nws.cache_is_fresh(path, NOW))

    def test_corrupt_cache_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nws_zones.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(nws.load_zone_cache(path), {})

    async def test_ensure_zones_fetches_once_then_reuses_cache(self):
        fetch = AsyncMock(side_effect=lambda zone_id, **kwargs: zone_geometries().get(zone_id))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nws_zones.json"
            with patch.object(nws, "fetch_zone_geometry", fetch):
                first = await nws.ensure_zones(alert_features(), path=path, now=NOW)
                second = await nws.ensure_zones(alert_features(), path=path, now=NOW)
        self.assertEqual(set(first), {"FLZ073", "FLZ074", "FLZ173"})
        self.assertEqual(second, first)
        self.assertEqual(fetch.await_count, 3)

    async def test_stale_cache_refetches_zones(self):
        fetch = AsyncMock(side_effect=lambda zone_id, **kwargs: zone_geometries().get(zone_id))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nws_zones.json"
            with patch.object(nws, "fetch_zone_geometry", fetch):
                await nws.ensure_zones(alert_features(), path=path, now=NOW)
                await nws.ensure_zones(alert_features(), path=path, now=NOW + timedelta(days=60))
        self.assertEqual(fetch.await_count, 6)


class RegisterTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_alerts_calls_register_hazard_with_weather_kind(self):
        parsed = [alert for alert in (nws.parse_alert(f, zone_geometries()) for f in alert_features())
                  if alert is not None]
        with patch.object(nws, "register_hazard", AsyncMock()) as register:
            count = await nws.register_alerts(fake_db(), parsed, NOW,
                                              probability=nws.ENDED_PROBABILITY)
        self.assertEqual(count, len(parsed))
        for call in register.call_args_list:
            self.assertEqual(call.args[2], "weather")
            self.assertEqual(call.args[4]["probability"], nws.ENDED_PROBABILITY)

    async def test_close_ended_demotes_absent_beliefs(self):
        stale = {"_id": "belief:nws:old", "type": "hazard_belief", "hazard_type": "weather",
                 "hazard_id": "nws:old", "geometry": {"type": "Point", "coordinates": [-80.19, 25.76]},
                 "prior_log_odds": log_odds(0.8), "severity": 2}
        with patch.object(nws, "register_hazard", AsyncMock()) as register:
            closed = await nws.close_ended(fake_db([stale]), set(), NOW)
        self.assertEqual(closed, 1)
        _, hazard_id, kind, geometry, properties, _ = register.call_args.args
        self.assertEqual(hazard_id, "nws:old")
        self.assertEqual(kind, "weather")
        self.assertEqual(geometry, stale["geometry"])
        self.assertEqual(properties["probability"], nws.ENDED_PROBABILITY)
        self.assertEqual(properties["severity"], 2)

    async def test_close_ended_skips_already_closed_beliefs(self):
        closed = {"_id": "belief:nws:old", "type": "hazard_belief", "hazard_type": "weather",
                  "hazard_id": "nws:old", "geometry": {"type": "Point", "coordinates": [-80.19, 25.76]},
                  "prior_log_odds": log_odds(nws.ENDED_PROBABILITY), "severity": 2}
        with patch.object(nws, "register_hazard", AsyncMock()) as register:
            count = await nws.close_ended(fake_db([closed]), set(), NOW)
        self.assertEqual(count, 0)
        register.assert_not_awaited()


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_registers_active_and_demotes_ended_and_absent(self):
        stale = {"_id": "belief:nws:old", "type": "hazard_belief", "hazard_type": "weather",
                 "hazard_id": "nws:old", "geometry": {"type": "Point", "coordinates": [-80.19, 25.76]},
                 "prior_log_odds": log_odds(0.8), "severity": 2}
        fetch_zone = AsyncMock(side_effect=lambda zone_id, **kwargs: zone_geometries().get(zone_id))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(nws, "fetch_active_alerts", AsyncMock(return_value=load(ALERTS_FIXTURE))), \
                patch.object(nws, "fetch_zone_geometry", fetch_zone), \
                patch.object(nws, "register_hazard", AsyncMock()) as register:
            summary = await nws.run(fake_db([stale]), NOW, client=object(),
                                    zone_cache_path=Path(tmp) / "nws_zones.json")

        self.assertEqual(summary, {"active": 3, "ended": 2, "closed": 1})
        by_id = {call.args[1]: call for call in register.call_args_list}

        active_feature = alert_features()[0]
        active_call = by_id[nws.alert_hazard_id(active_feature["properties"]["id"])]
        self.assertAlmostEqual(active_call.args[4]["probability"], 0.95)
        self.assertEqual(active_call.args[2], "weather")
        self.assertEqual(active_call.args[5], NOW)

        ended_feature = alert_features()[3]
        ended_call = by_id[nws.alert_hazard_id(ended_feature["properties"]["id"])]
        self.assertEqual(ended_call.args[4]["probability"], nws.ENDED_PROBABILITY)

        self.assertEqual(by_id["nws:old"].args[4]["probability"], nws.ENDED_PROBABILITY)


if __name__ == "__main__":
    unittest.main()
