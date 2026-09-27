import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.ingestion import traffic_samples as ts
from app.routing.beliefs import log_odds
from tests.test_satellite_floods import FakeCursor, FakeIntelCache

NY = ZoneInfo("America/New_York")
MONDAY_0715 = datetime(2026, 9, 28, 7, 15, tzinfo=NY)  # hour of week 7 (Mon 07:00)


class Samples:
    def __init__(self):
        self.docs = {}

    def find(self, query):
        return FakeCursor([d for d in self.docs.values() if all(d.get(k) == v for k, v in query.items())])

    async def replace_one(self, query, doc, upsert=False):
        self.docs[query["_id"]] = doc


class Db(SimpleNamespace):
    def __init__(self, routines=(), places=()):
        places = {p["_id"]: p for p in places}
        super().__init__(
            intel_cache=FakeIntelCache(), traffic_samples=Samples(),
            routines=SimpleNamespace(find=lambda q: FakeCursor(list(routines))),
            places=SimpleNamespace(find_one=AsyncMock(side_effect=lambda q: places.get(q["_id"]))))


def routes(ratio_by_hour):
    """compute_routes stub: the congestion ratio depends on the local departure hour."""
    calls = []

    async def compute(origin, destination, depart_at=None, **kw):
        calls.append((origin, destination, depart_at))
        ratio = ratio_by_hour.get(depart_at.astimezone(NY).hour, 1.0)
        return [{"duration_s": int(600 * ratio), "static_duration_s": 600, "distance_m": 1, "summary": "",
                 "route_geojson": {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                                   "geometry": {"type": "LineString",
                                                "coordinates": [[origin[1], origin[0]], [destination[1], destination[0]]]}}]}}]
    return compute, calls


class BucketTests(unittest.TestCase):
    def test_hour_of_week_and_next_buckets(self):
        self.assertEqual(ts.hour_of_week(MONDAY_0715), 7)
        self.assertEqual(ts.hour_of_week(datetime(2026, 10, 4, 23, 30, tzinfo=NY)), 6 * 24 + 23)  # Sunday 23:00
        buckets = ts.upcoming_buckets(MONDAY_0715)
        self.assertEqual([(b, d.strftime("%H:%M")) for b, d in buckets], [(8, "08:30"), (9, "09:30")])

    def test_levels(self):
        self.assertIsNone(ts.level_for(1.2))
        self.assertEqual(ts.level_for(1.4), ("moderate", 1))
        self.assertEqual(ts.level_for(1.7), ("heavy", 2))
        self.assertEqual(ts.level_for(2.5), ("severe", 3))


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_samples_corridors_and_legs_for_the_next_hours(self):
        db = Db(routines=[{"_id": "rt", "active": True, "legs": [{"from_place": "a", "to_place": "b"}]}],
                places=[{"_id": "a", "name": "MMC", "location": {"coordinates": [-80.37, 25.75]}},
                        {"_id": "b", "name": "BBC", "location": {"coordinates": [-80.14, 25.91]}}])
        compute, calls = routes({8: 1.8, 9: 1.1})
        with patch("app.ingestion.traffic_samples.compute_routes", compute):
            result = await ts.run(db, MONDAY_0715)
        corridors = len(ts.CORRIDORS) + 1
        self.assertEqual((result["corridors"], result["sampled"]), (corridors, corridors * 2))
        self.assertTrue(all(depart > MONDAY_0715 for _, _, depart in calls))  # future departures only
        doc = db.traffic_samples.docs["i95-nb:8"]
        self.assertEqual((doc["congestion_ratio"], doc["hour_of_week"]), (1.8, 8))
        self.assertEqual(doc["expires_at"] - doc["sampled_at"], ts.SAMPLE_TTL)
        self.assertIn("leg:rt:0:9", db.traffic_samples.docs)
        self.assertEqual(db.traffic_samples.docs["leg:rt:0:9"]["label"], "MMC → BBC")

    async def test_fresh_buckets_are_not_resampled(self):
        db = Db()
        compute, calls = routes({})
        with patch("app.ingestion.traffic_samples.compute_routes", compute):
            await ts.run(db, MONDAY_0715)
            first = len(calls)
            await ts.run(db, MONDAY_0715 + timedelta(minutes=30))  # same next two hours
            self.assertEqual(len(calls), first)
            await ts.run(db, MONDAY_0715 + timedelta(days=8))  # a week later: stale again
        self.assertEqual(len(calls), first * 2)

    async def test_congested_corridors_now_become_predicted_hazards_and_clear(self):
        db = Db()
        compute, _ = routes({7: 1.7})
        with patch("app.ingestion.traffic_samples.compute_routes", compute):
            # A sample for the current hour (07:00) from last week's runs.
            for corridor in ts.CORRIDORS[:2]:
                await ts.sample(db, corridor, 7, MONDAY_0715 + timedelta(minutes=15), MONDAY_0715)  # 07:30
            result = await ts.run(db, MONDAY_0715)
        self.assertEqual(result["congested_now"], 2)
        hazard = db.intel_cache.docs["belief:typical:i95-nb"]
        self.assertEqual((hazard["hazard_type"], hazard["severity"]), ("congestion", 2))
        self.assertAlmostEqual(hazard["prior_log_odds"], log_odds(0.6))
        self.assertEqual(hazard["properties"]["title"], "Usually heavy traffic at this hour")
        # An hour later the 08:00 samples are free-flowing: the typical hazards clear.
        compute, _ = routes({})
        with patch("app.ingestion.traffic_samples.compute_routes", compute):
            later = await ts.run(db, MONDAY_0715 + timedelta(hours=1))
        self.assertEqual((later["congested_now"], later["cleared"]), (0, 2))
        self.assertAlmostEqual(db.intel_cache.docs["belief:typical:i95-nb"]["prior_log_odds"], log_odds(0.05))

    async def test_routes_failure_is_skipped(self):
        from app.routing.google_routes import RoutesApiError
        db = Db()
        with patch("app.ingestion.traffic_samples.compute_routes", AsyncMock(side_effect=RoutesApiError("403"))):
            result = await ts.run(db, MONDAY_0715)
        self.assertEqual(result["sampled"], 0)

    def test_layers_marks_typical_congestion_predicted(self):
        from app.routers import layers
        self.assertEqual(layers.source_kind("typical:i95-nb"), "google_typical")
        self.assertIn("google_typical", layers.PREDICTIVE_SOURCES)
