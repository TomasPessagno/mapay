import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.ingestion import here_flow, here_incidents
from app.routing.beliefs import log_odds

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 27, 0, 0, tzinfo=timezone.utc)


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def client_for(payload, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=payload)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class settings:
    """Patch the HERE key in both modules, so tests never need a real .env (CI has none)."""

    def __enter__(self):
        fake = SimpleNamespace(here_api_key="k")
        self.patches = [patch(f"app.ingestion.{m}.get_settings", return_value=fake)
                        for m in ("here_incidents", "here_flow")]
        for p in self.patches:
            p.start()

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length=None):
        return list(self.docs)


class FakeIntelCache:
    """Just enough of Mongo for beliefs.register_hazard and the stale-belief sweep."""

    def __init__(self):
        self.docs = {}

    @staticmethod
    def _matches(doc, query):
        for key, value in query.items():
            if isinstance(value, dict) and "$regex" in value:
                if not re.search(value["$regex"], doc.get(key, "")):
                    return False
            elif doc.get(key) != value:
                return False
        return True

    def find(self, query):
        return FakeCursor([d for d in self.docs.values() if self._matches(d, query)])

    async def find_one(self, query):
        doc = self.docs.get(query["_id"])
        return doc if doc and self._matches(doc, query) else None

    async def update_one(self, query, update, upsert=False):
        doc = self.docs.get(query["_id"])
        if doc is None:
            if upsert:
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


class IncidentGeoJsonTests(unittest.TestCase):
    def test_features_keep_type_criticality_description_and_times(self):
        features = here_incidents.to_geojson(fixture("here_incidents.json"))["features"]
        self.assertEqual(len(features), 4)
        closure = next(f for f in features if f["properties"]["type"] == "roadClosure")
        self.assertEqual(closure["geometry"]["type"], "LineString")
        self.assertEqual(closure["properties"]["kind"], "closure")
        self.assertEqual(closure["properties"]["criticality"], "critical")
        self.assertTrue(closure["properties"]["description"])
        self.assertEqual(closure["properties"]["start_time"], "2026-09-26T22:53:20Z")
        lng, lat = closure["geometry"]["coordinates"][0]
        self.assertTrue(-81 < lng < -80 and 25 < lat < 26)

    def test_kinds(self):
        self.assertEqual(here_incidents.kind_for({"type": "construction"}), "construction")
        self.assertEqual(here_incidents.kind_for({"type": "construction", "roadClosed": True}), "closure")
        self.assertEqual(here_incidents.kind_for({"type": "accident"}), "incident")
        self.assertIsNone(here_incidents.kind_for({"type": "congestion"}))

    def test_links_join_or_split(self):
        a = {"points": [{"lat": 1, "lng": 0}, {"lat": 1, "lng": 1}]}
        b = {"points": [{"lat": 1, "lng": 1}, {"lat": 1, "lng": 2}]}
        c = {"points": [{"lat": 5, "lng": 5}, {"lat": 5, "lng": 6}]}
        self.assertEqual(here_incidents.links_geometry([a, b]),
                         {"type": "LineString", "coordinates": [[0, 1], [1, 1], [2, 1]]})
        self.assertEqual(here_incidents.links_geometry([a, c])["type"], "MultiLineString")
        self.assertIsNone(here_incidents.links_geometry([]))


class TitleTests(unittest.TestCase):
    def test_titles_by_kind_and_place_from_description(self):
        base = {"criticality": "critical", "road_closed": True, "description": "Between A St and B Ave - Closed",
                "summary": "Closed", "start_time": None, "end_time": None}
        closure = here_incidents.hazard_properties({**base, "kind": "closure"})
        self.assertEqual((closure["title"], closure["place"]), ("Road closed", "Between A St and B Ave"))
        roadwork = here_incidents.hazard_properties({**base, "kind": "construction", "road_closed": False})
        self.assertEqual(roadwork["title"], "Roadwork")
        crash = here_incidents.hazard_properties({**base, "kind": "incident", "summary": "Accident"})
        self.assertEqual(crash["title"], "Accident")


class IncidentRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_registers_current_incidents_with_criticality_priors(self):
        cache = FakeIntelCache()
        seen = []
        with settings():
            result = await here_incidents.run(SimpleNamespace(intel_cache=cache), NOW,
                                              client_for(fixture("here_incidents.json"), seen))
        self.assertEqual(seen[0].url.params["apiKey"], "k")
        self.assertEqual(seen[0].url.params["locationReferencing"], "shape")
        self.assertEqual(result, {"registered": 3, "cleared": 0})
        kinds = {d["hazard_id"]: d["hazard_type"] for d in cache.docs.values()}
        self.assertEqual(sorted(kinds.values()), ["closure", "construction", "incident"])
        self.assertTrue(all(h.startswith("here:") for h in kinds))
        closure = next(d for d in cache.docs.values() if d["hazard_type"] == "closure")
        self.assertAlmostEqual(closure["prior_log_odds"], log_odds(0.9))
        self.assertEqual(closure["severity"], 5)
        construction = next(d for d in cache.docs.values() if d["hazard_type"] == "construction")
        self.assertAlmostEqual(construction["prior_log_odds"], log_odds(0.75))

    async def test_expired_incident_skipped_and_vanished_one_cleared(self):
        cache = FakeIntelCache()
        db = SimpleNamespace(intel_cache=cache)
        with settings():
            await here_incidents.run(db, NOW, client_for(fixture("here_incidents.json")))
            later = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)  # "other" ended at 10:00
            result = await here_incidents.run(db, later, client_for(fixture("here_incidents.json")))
            self.assertEqual(result, {"registered": 2, "cleared": 1})
            incident = next(d for d in cache.docs.values() if d["hazard_type"] == "incident")
            self.assertAlmostEqual(incident["prior_log_odds"], log_odds(0.05))
            # A second sweep leaves it alone.
            result = await here_incidents.run(db, later, client_for(fixture("here_incidents.json")))
            self.assertEqual(result["cleared"], 0)


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def test_levels(self):
        self.assertIsNone(here_flow.level_for(3.9))
        self.assertEqual(here_flow.level_for(4.0), ("moderate", 2))
        self.assertEqual(here_flow.level_for(6.5), ("heavy", 3))
        self.assertEqual(here_flow.level_for(10), ("severe", 4))

    def test_only_jammed_segments_with_stable_ids(self):
        segments = here_flow.congested_segments(fixture("here_flow.json"))
        self.assertEqual(sorted(s["properties"]["level"] for s in segments),
                         ["heavy", "moderate", "moderate", "severe", "severe"])
        again = here_flow.congested_segments(fixture("here_flow.json"))
        self.assertEqual([s["properties"]["id"] for s in segments], [s["properties"]["id"] for s in again])

    async def test_run_registers_congestion_and_clears_later(self):
        cache = FakeIntelCache()
        db = SimpleNamespace(intel_cache=cache)
        with settings():
            result = await here_flow.run(db, NOW, client_for(fixture("here_flow.json")))
            self.assertEqual(result, {"registered": 5, "cleared": 0})
            self.assertTrue(all(d["hazard_type"] == "congestion" and d["hazard_id"].startswith("here-flow:")
                                for d in cache.docs.values()))
            self.assertAlmostEqual(next(iter(cache.docs.values()))["prior_log_odds"], log_odds(0.85))
            result = await here_flow.run(db, NOW, client_for({"results": []}))
        self.assertEqual(result, {"registered": 0, "cleared": 5})
