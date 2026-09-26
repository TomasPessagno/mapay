import json
import math
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.ingestion import fema, tides
from app.routing.beliefs import log_odds, probability

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def noaa_handler(request):
    path = request.url.path
    if path.endswith("floodlevels.json"):
        return httpx.Response(200, json=fixture("noaa_floodlevels.json"))
    if path.endswith("datums.json"):
        return httpx.Response(200, json=fixture("noaa_datums.json"))
    if path.endswith("datagetter"):
        return httpx.Response(200, json=fixture("noaa_predictions.json"))
    return httpx.Response(404)


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class FakeIntelCache:
    """Just enough of Mongo's update operators for beliefs.register_hazard."""

    def __init__(self):
        self.docs = {}

    @staticmethod
    def _matches(doc, query):
        return all(doc.get(k) == v for k, v in query.items())

    async def find_one(self, query):
        doc = self.docs.get(query["_id"])
        return doc if doc and self._matches(doc, query) else None

    async def update_one(self, query, update, upsert=False):
        doc = self.docs.get(query["_id"])
        if doc is None:
            if not upsert:
                return SimpleNamespace(matched_count=0)
            self.docs[query["_id"]] = {"_id": query["_id"], **update.get("$setOnInsert", {})}
            return SimpleNamespace(matched_count=0)
        if not self._matches(doc, query):
            return SimpleNamespace(matched_count=0)
        for key, value in update.get("$inc", {}).items():
            doc[key] = doc.get(key, 0) + value
        doc.update(update.get("$set", {}))
        for key, value in update.get("$max", {}).items():
            doc[key] = max(doc.get(key, value), value)
        return SimpleNamespace(matched_count=1)


class TideTests(unittest.IsolatedAsyncioTestCase):
    def test_threshold_is_nws_minor_above_mhhw(self):
        # Station datum: nws_minor 13.66 ft, MHHW 12.38 ft → 1.28 ft above MHHW (NWS gauge VAKF1 says 1.3).
        self.assertEqual(tides.parse_threshold(fixture("noaa_floodlevels.json"), fixture("noaa_datums.json")), 1.28)

    def test_interpolates_and_takes_the_peak(self):
        predictions = tides.parse_predictions(fixture("noaa_predictions.json"))
        self.assertEqual(len(predictions), 48)
        at = datetime(2026, 10, 8, 11, 30, tzinfo=timezone.utc)
        self.assertAlmostEqual(tides.tide_at(predictions, at), (0.478 + 0.582) / 2, places=3)
        end = datetime(2026, 10, 8, 14, 30, tzinfo=timezone.utc)
        self.assertEqual(tides.max_tide(predictions, at, end), 0.582)

    def test_query_uses_mhhw_feet_and_station(self):
        q = tides.predictions_query(datetime(2026, 10, 8, 11, tzinfo=timezone.utc),
                                    datetime(2026, 10, 8, 15, tzinfo=timezone.utc))
        self.assertEqual((q["station"], q["datum"], q["units"], q["time_zone"]), ("8723214", "MHHW", "english", "gmt"))
        self.assertEqual(q["begin_date"], "20261008 11:00")

    async def test_fetch(self):
        at = datetime(2026, 10, 8, 11, 30, tzinfo=timezone.utc)
        result = await tides.fetch(at, client_for(noaa_handler))
        self.assertEqual(result["flood_threshold_ft_mhhw"], 1.28)
        self.assertEqual(result["peak_tide_ft_mhhw"], 0.582)

    async def test_threshold_falls_back_when_metadata_fails(self):
        def handler(request):
            if request.url.path.endswith("datagetter"):
                return httpx.Response(200, json=fixture("noaa_predictions.json"))
            return httpx.Response(503)
        result = await tides.fetch(datetime(2026, 10, 8, 11, tzinfo=timezone.utc), client_for(handler))
        self.assertEqual(result["flood_threshold_ft_mhhw"], tides.FALLBACK_THRESHOLD_FT_MHHW)

    async def test_noaa_error_raises(self):
        with self.assertRaises(RuntimeError):
            await tides.fetch(datetime(2026, 10, 8, 11, tzinfo=timezone.utc),
                              client_for(lambda r: httpx.Response(200, json={"error": {"message": "No data"}})))


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_registers_every_hotspot_with_tide_prior(self):
        cache = FakeIntelCache()
        now = datetime(2026, 10, 8, 11, 30, tzinfo=timezone.utc)
        hotspots = tides.load_hotspots()
        result = await tides.run(SimpleNamespace(intel_cache=cache), now, client_for(noaa_handler))
        self.assertEqual(result["registered"], len(hotspots))
        self.assertEqual(len(cache.docs), len(hotspots))
        # AE zone (p 0.6) with the tide 0.582 - 1.28 = -0.698 ft below the threshold, 1 log-odds per foot.
        doc = cache.docs["belief:flood:brickell-bay-dr-se-12th-st"]
        expected = log_odds(0.6) - 0.698
        self.assertAlmostEqual(doc["prior_log_odds"], expected, places=6)
        self.assertAlmostEqual(doc["log_odds"], expected, places=6)
        self.assertEqual((doc["hazard_type"], doc["severity"]), ("flood", 3))
        self.assertAlmostEqual(probability(doc["log_odds"]), 0.43, places=2)
        self.assertEqual(doc["geometry"]["type"], "Point")

    async def test_rerun_moves_prior_and_keeps_evidence(self):
        cache = FakeIntelCache()
        db = SimpleNamespace(intel_cache=cache)
        spot = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [-80.19, 25.76]},
                 "properties": {"id": "x", "fema_zone": "AE", "severity": 3}}]
        now = datetime(2026, 10, 8, 11, 30, tzinfo=timezone.utc)
        await tides.run(db, now, client_for(noaa_handler), spot)
        cache.docs["belief:flood:x"]["log_odds"] += 1.5  # crowd evidence arrives

        def king_tide(request):
            if request.url.path.endswith("datagetter"):
                payload = fixture("noaa_predictions.json")
                for p in payload["predictions"]:
                    p["v"] = "1.78"  # half a foot over the threshold
                return httpx.Response(200, json=payload)
            return noaa_handler(request)

        await tides.run(db, now, client_for(king_tide), spot)
        doc = cache.docs["belief:flood:x"]
        self.assertAlmostEqual(doc["prior_log_odds"], log_odds(0.6) + 0.5, places=6)
        self.assertAlmostEqual(doc["log_odds"], log_odds(0.6) + 0.5 + 1.5, places=6)


class FemaTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_zone(self):
        self.assertEqual(fema.parse_zone(fixture("fema_zone_ae.json")), "AE")
        self.assertIsNone(fema.parse_zone({"features": []}))
        both = {"features": [{"attributes": {"FLD_ZONE": "X"}}, {"attributes": {"FLD_ZONE": "VE"}}]}
        self.assertEqual(fema.parse_zone(both), "VE")
        with self.assertRaises(RuntimeError):
            fema.parse_zone({"error": {"code": 400}})

    async def test_fetch_queries_point_in_wgs84(self):
        seen = []

        def handler(request):
            seen.append(request.url.params)
            return httpx.Response(200, json=fixture("fema_zone_ae.json"))

        zones = await fema.fetch([(-80.18974, 25.76185)], client_for(handler))
        self.assertEqual(zones, ["AE"])
        self.assertEqual((seen[0]["geometry"], seen[0]["inSR"]), ("-80.18974,25.76185", "4326"))

    async def test_refresh_writes_zones(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spots.geojson"
            path.write_text(json.dumps({"type": "FeatureCollection", "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-80.19, 25.76]},
                 "properties": {"id": "a"}}]}))
            await fema.refresh_hotspot_zones(path, client_for(lambda r: httpx.Response(200, json={"features": []})))
            self.assertEqual(json.loads(path.read_text())["features"][0]["properties"]["fema_zone"], "X")


class HotspotFileTests(unittest.TestCase):
    def test_hotspots_are_cited_unique_and_in_miami_dade(self):
        features = tides.load_hotspots()
        self.assertGreaterEqual(len(features), 15)
        ids = [f["properties"]["id"] for f in features]
        self.assertEqual(len(ids), len(set(ids)))
        for f in features:
            lng, lat = f["geometry"]["coordinates"]
            self.assertTrue(-80.9 < lng < -80.0 and 25.1 < lat < 26.0, f["properties"]["id"])
            self.assertTrue(f["properties"]["sources"] and all(s["url"].startswith("https://")
                                                               for s in f["properties"]["sources"]))
            self.assertIn(f["properties"]["fema_zone"], fema.ZONE_RANK)
            self.assertTrue(1 <= f["properties"]["severity"] <= 5)
            self.assertFalse(math.isnan(lng))
