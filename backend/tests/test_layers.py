import asyncio
import json
import re
import time
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
        self.queries = []

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
        self.queries.append(query)
        return FakeCursor([d for d in self.docs if self._matches(d, query)])


class FakeDb:
    def __init__(self, docs):
        self.intel_cache = FakeIntelCache(docs)

    @property
    def evidence_queries(self):
        """How many times the evidence collection was read: the snapshot build does it once."""
        return sum(1 for q in self.intel_cache.queries if "_id" in q)


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
        # These tests pass a fixed far-off `t` and assert exact slow-path numbers; make sure the
        # wall clock can never put them inside the snapshot window (SnapshotTests covers that path).
        patcher = patch.object(layers, "SNAPSHOT_FRESH_SECONDS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

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


class SnapshotTests(unittest.TestCase):
    """A26: near-now requests are served from one in-process snapshot, without touching Mongo."""

    def setUp(self):
        app = FastAPI()
        app.include_router(layers.router)
        self.client = TestClient(app)
        layers.clear_snapshot()

    @staticmethod
    def seeded_now():
        moment = datetime.now(timezone.utc)
        return [
            belief("flood:near", "flood", point(-80.19, 25.76), 0.8, updated=moment),
            belief("flood:far", "flood", point(-81.8, 24.55), 0.8, updated=moment),
            belief("here:closure", "closure", point(-80.20, 25.77), 0.9, updated=moment),
        ]

    def get(self, db, **params):
        params.setdefault("t", datetime.now(timezone.utc).isoformat())
        with patch("app.routers.layers.get_db", return_value=db):
            response = self.client.get("/layers", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response

    @staticmethod
    def ids(body, key):
        return [f["properties"]["hazard_id"] for f in body[key]["features"]]

    def test_snapshot_is_reused_across_requests(self):
        db = FakeDb(self.seeded_now())
        first = self.get(db)
        self.assertEqual(db.evidence_queries, 1)  # built once (beliefs + evidence read)
        second = self.get(db)
        self.assertEqual(db.evidence_queries, 1)  # second request never reached Mongo
        self.assertEqual(self.ids(first.json(), "flood"), self.ids(second.json(), "flood"))

    def test_snapshot_bbox_filter(self):
        db = FakeDb(self.seeded_now())
        full = self.get(db).json()
        boxed = self.get(db, bbox="-80.25,25.70,-80.10,25.80").json()
        self.assertEqual(db.evidence_queries, 1)  # filtering happened in-process
        self.assertIn("flood:far", self.ids(full, "flood"))
        self.assertEqual(self.ids(boxed, "flood"), ["flood:near"])
        self.assertEqual(self.ids(boxed, "closure"), ["here:closure"])
        self.assertEqual(self.ids(boxed, "weather"), [])
        self.assertNotIn("flood:far", self.ids(boxed, "flood"))

    def wait_for_rebuild(self, previous, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = layers._snapshot
            if current is not None and current is not previous:
                return
            time.sleep(0.01)
        self.fail("the background rebuild never replaced the snapshot")

    def test_invalidation_keeps_serving_until_the_rebuild_lands(self):
        old_db = FakeDb(self.seeded_now())
        self.get(old_db)
        old_snapshot = layers._snapshot
        self.assertIsNotNone(old_snapshot)

        # Ingest writes a new hazard; invalidation marks the snapshot stale but leaves it serving.
        added = belief("flood:new", "flood", point(-80.18, 25.76), 0.9, updated=datetime.now(timezone.utc))
        new_db = FakeDb(self.seeded_now() + [added])
        layers.invalidate_snapshot(new_db)

        served = self.get(new_db).json()
        self.assertNotIn("flood:new", self.ids(served, "flood"))  # old snapshot, no rebuild wait

        self.wait_for_rebuild(old_snapshot)
        updated = self.get(new_db).json()
        self.assertIn("flood:new", self.ids(updated, "flood"))

    def test_far_t_keeps_the_slow_path(self):
        db = FakeDb(self.seeded_now())
        far = datetime.now(timezone.utc) + timedelta(days=1)
        self.get(db, t=far.isoformat())
        self.assertIsNone(layers._snapshot)  # never built
        self.get(db, t=(far + timedelta(days=1)).isoformat())
        self.assertIsNone(layers._snapshot)
        self.assertEqual(db.evidence_queries, 2)

    def test_cache_control_header(self):
        response = self.get(FakeDb(self.seeded_now()))
        self.assertEqual(response.headers["cache-control"], "public, max-age=60")


class RebuildRetryTests(unittest.TestCase):
    """A build discarded by an ingest mid-flight must start over instead of vanishing."""

    def test_discarded_rebuild_starts_another(self):
        async def scenario():
            layers.clear_snapshot()
            generation = layers._generation
            started, release = asyncio.Event(), asyncio.Event()
            databases = []

            async def fake_collect(db, t):
                databases.append(db)
                if len(databases) == 1:
                    started.set()
                    await release.wait()
                return {"flood": []}, {}

            with patch.object(layers, "collect_features", fake_collect):
                task = asyncio.get_running_loop().create_task(layers._rebuild("db", generation))
                await started.wait()
                layers.invalidate_snapshot()  # ingest lands while the first build is running
                release.set()
                await task
                self.assertEqual(databases, ["db", "db"])  # discarded build started a retry
                await layers._rebuild_task
            self.assertIsNotNone(layers._snapshot)

        asyncio.run(scenario())


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
