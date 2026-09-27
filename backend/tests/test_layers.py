import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import layers
from app.routing.beliefs import log_odds

NOW = datetime(2026, 9, 28, 13, 0, tzinfo=timezone.utc)
MOCK = Path(__file__).resolve().parents[2] / "frontend" / "public" / "mocks" / "layers.json"


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length=None):
        return list(self.docs)


class FakeIntelCache:
    def __init__(self, docs):
        self.docs = docs

    @staticmethod
    def _matches(doc, query):
        for key, value in query.items():
            if isinstance(value, dict) and "$regex" in value:
                if not re.search(value["$regex"], str(doc.get(key, ""))):
                    return False
            elif doc.get(key) != value:
                return False
        return True

    def find(self, query):
        return FakeCursor([d for d in self.docs if self._matches(d, query)])


class FakeDb:
    def __init__(self, docs):
        self.intel_cache = FakeIntelCache(docs)


def point(lng, lat):
    return {"type": "Point", "coordinates": [lng, lat]}


def belief(hazard_id, kind, geometry, p, *, severity=2, evidence=None, updated=NOW, properties=None):
    prior = log_odds(p)
    evidence = evidence or {}
    doc = {"_id": f"belief:{hazard_id}", "type": "hazard_belief", "hazard_id": hazard_id, "hazard_type": kind,
           "geometry": geometry, "severity": severity, "prior_log_odds": prior,
           "log_odds": prior + sum(e["applied"] for e in evidence.values()), "evidence": evidence,
           "created_at": updated, "last_updated": updated}
    if properties:
        doc["properties"] = properties
    return doc


def seeded():
    crowd_at = NOW - timedelta(hours=1)
    return [
        belief("flood:brickell-bay-dr-se-12th-st", "flood", point(-80.1897, 25.7618), 0.6, severity=3),
        belief("flood:shorecrest", "flood", point(-80.1784, 25.8520), 0.4, severity=3, evidence={
            "t1": {"source": "crowd", "observed_at": crowd_at, "applied": 1.5, "evaluated_at": crowd_at}}),
        belief("here:1", "closure", {"type": "LineString", "coordinates": [[-80.21, 25.76], [-80.20, 25.76]]}, 0.9,
               severity=5, properties={"title": "Road closed", "description": "SW 8th St at SW 17th Ave",
                                       "end_time": "2026-09-28T22:00:00Z"}),
        belief("here:gone", "closure", point(-80.2, 25.8), 0.05),
        belief("here-flow:abc", "congestion", {"type": "LineString", "coordinates": [[-80.3, 25.77], [-80.3, 25.8]]},
               0.85, severity=3, properties={"level": "heavy"}),
        belief("incident:news-fresh", "incident", point(-80.19, 25.89), 0.7, updated=NOW - timedelta(hours=1),
               evidence={"n1": {"source": "news", "observed_at": NOW, "applied": 0.5, "evaluated_at": NOW}}),
        belief("incident:news-stale", "incident", point(-80.19, 25.88), 0.7, updated=NOW - timedelta(hours=4)),
        belief("osm:way:1", "no_sidewalk", point(-80.37, 25.75), 0.95, severity=1),
        belief("far:away", "flood", point(-81.8, 24.55), 0.9),  # Key West, outside the Miami bbox
        {"_id": "evidence:news:n1", "type": "news", "hazard_id": "incident:news-fresh", "title": "NBC6: crash on I-95",
         "source_url": "https://www.nbcmiami.com/x", "created_at": NOW - timedelta(minutes=20),
         "expires_at": NOW + timedelta(hours=3)},
    ]


class LayersTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(layers.router)
        self.client = TestClient(app)

    def get(self, docs=None, **params):
        params.setdefault("t", NOW.isoformat())
        with patch("app.routers.layers.get_db", return_value=FakeDb(seeded() if docs is None else docs)):
            response = self.client.get("/layers", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def features(self, body, key):
        return {f["properties"]["hazard_id"]: f for f in body[key]["features"]}

    def test_every_legend_key_and_mock_property_is_present(self):
        body = self.get()
        mock = json.loads(MOCK.read_text())
        self.assertEqual(set(body), set(mock))
        mock_props = set(mock["flood"]["features"][0]["properties"])
        for key in layers.CATEGORIES:
            for feature in body[key]["features"]:
                self.assertTrue(mock_props <= set(feature["properties"]), feature["properties"]["hazard_id"])

    def test_predicted_vs_observed_and_probability(self):
        floods = self.features(self.get(), "flood")
        tide = floods["flood:brickell-bay-dr-se-12th-st"]["properties"]
        self.assertEqual((tide["status"], tide["title"], tide["probability"]), ("predicted", "Flooding expected", 0.6))
        self.assertEqual(tide["sources"][0]["kind"], "tides")
        crowd = floods["flood:shorecrest"]["properties"]
        self.assertEqual(crowd["status"], "observed")
        # Crowd evidence observed 1 h before t has faded to half of +1.5.
        self.assertAlmostEqual(crowd["probability"], round(1 / (1 + 2.718281828 ** -(log_odds(0.4) + 0.75)), 2))
        self.assertIn("crowd", [s["kind"] for s in crowd["sources"]])

    def test_later_t_decays_crowd_evidence_without_writing(self):
        docs = seeded()
        before = [dict(d) for d in docs]
        body = self.get(docs, t=(NOW + timedelta(hours=2)).isoformat())
        self.assertEqual(self.features(body, "flood")["flood:shorecrest"]["properties"]["probability"], 0.4)
        self.assertEqual(docs, before)

    def test_properties_expiry_level_and_hidden_cleared(self):
        body = self.get()
        closure = self.features(body, "closure")
        self.assertEqual(list(closure), ["here:1"])  # here:gone at p 0.05 is hidden
        self.assertEqual(closure["here:1"]["properties"]["place"], "SW 8th St at SW 17th Ave")
        self.assertEqual(closure["here:1"]["properties"]["expires_at"], "2026-09-28T22:00:00+00:00")
        congestion = self.features(body, "congestion")["here-flow:abc"]["properties"]
        self.assertEqual((congestion["level"], congestion["title"]), ("heavy", "Heavy traffic"))

    def test_news_only_hazards_leave_after_their_window(self):
        incidents = self.features(self.get(), "incident")
        self.assertEqual(list(incidents), ["incident:news-fresh"])
        props = incidents["incident:news-fresh"]["properties"]
        self.assertEqual(props["sources"][0]["url"], "https://www.nbcmiami.com/x")
        self.assertEqual(props["expires_at"], (NOW + timedelta(hours=3)).isoformat())

    def test_bbox_filter(self):
        body = self.get(bbox="-80.45,25.55,-80.10,25.98")
        self.assertNotIn("far:away", self.features(body, "flood"))
        self.assertIn("far:away", self.features(self.get(), "flood"))
        body = self.get(bbox="-80.40,25.70,-80.35,25.80")
        self.assertEqual(sum(len(body[k]["features"]) for k in layers.CATEGORIES), 1)

    def test_bad_bbox_is_422(self):
        with patch("app.routers.layers.get_db", return_value=FakeDb([])):
            self.assertEqual(self.client.get("/layers", params={"bbox": "1,2,3"}).status_code, 422)
            self.assertEqual(self.client.get("/layers", params={"bbox": "3,2,1,4"}).status_code, 422)

    def test_radar_overlay_is_an_xyz_tile_template(self):
        body = self.get()
        radar = body["radar"]
        self.assertEqual(radar, layers.RADAR_OVERLAY)
        self.assertEqual(radar["type"], "xyz")
        self.assertIn("{z}/{x}/{y}", radar["url_template"])
        self.assertIn("NOAA", radar["attribution"])
        self.assertIn("NEXRAD", radar["attribution"])

    def test_freshness_per_source(self):
        freshness = self.get()["freshness"]
        self.assertEqual(freshness["here"], NOW.isoformat())
        self.assertEqual(freshness["news"], (NOW - timedelta(minutes=20)).isoformat())
        self.assertIn("tides", freshness)
        self.assertIn("osm", freshness)

    def test_empty_store(self):
        body = self.get([])
        self.assertEqual(body["freshness"], {})
        self.assertTrue(all(body[k]["features"] == [] for k in layers.CATEGORIES))


class PayloadTests(unittest.TestCase):
    def test_geometry_is_simplified_and_rounded(self):
        wiggly = {"type": "LineString", "coordinates": [[-80.2, 25.8], [-80.1999999, 25.80000001],
                                                         [-80.19999, 25.80001], [-80.1, 25.8]]}
        slim = layers.slim_geometry(wiggly)
        self.assertEqual(slim["type"], "LineString")
        self.assertLess(len(slim["coordinates"]), 4)
        self.assertTrue(all(len(str(c).split(".")[-1]) <= 5 for pt in slim["coordinates"] for c in pt))
        point = layers.slim_geometry({"type": "Point", "coordinates": [-80.1897374, 25.7618462]})
        self.assertEqual(point, {"type": "Point", "coordinates": [-80.18974, 25.76185]})

    def test_responses_are_gzipped(self):
        import importlib
        import os

        from app.config import get_settings
        # The real app reads settings at import; CI has no .env, so give it dummy ones.
        with patch.dict(os.environ, {"MONGODB_URI": "mongodb://unused", "MONGODB_DB_NAME": "unused"}):
            get_settings.cache_clear()
            try:
                main = importlib.import_module("app.main")
            finally:
                get_settings.cache_clear()
        with patch("app.routers.layers.get_db", return_value=FakeDb(seeded() * 20)), \
             patch("app.main.init_indexes"):
            response = TestClient(main.app).get("/layers", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("content-encoding"), "gzip")
