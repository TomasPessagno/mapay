import json
import math
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.ingestion import sidewalks
from app.routing.beliefs import log_odds

FIXTURE = Path(__file__).parent / "fixtures" / "overpass_sidewalks.json"


def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class QueryTests(unittest.TestCase):
    def test_query_targets_both_no_sidewalk_tags_in_miami_dade(self):
        query = sidewalks.build_query()
        self.assertIn('way["sidewalk"~"^(no|none)$"]', query)
        self.assertIn('way["sidewalk:both"="no"]', query)
        self.assertIn("25.55,-80.45,25.98,-80.1", query)
        self.assertIn("out tags geom;", query)

    def test_user_agent_is_descriptive(self):
        self.assertIn("MAPAY", sidewalks.USER_AGENT)
        self.assertIn("@", sidewalks.USER_AGENT)


class ParseTests(unittest.TestCase):
    def test_parses_tagged_ways_into_linestrings_with_stable_ids(self):
        collection = sidewalks.parse_response(fixture_payload())
        features = {f["id"]: f for f in collection["features"]}
        self.assertEqual(collection["type"], "FeatureCollection")
        self.assertEqual(set(features), {"osm:way:1001", "osm:way:1002", "osm:way:1003"})

        way = features["osm:way:1001"]
        self.assertEqual(way["properties"]["hazard_id"], "osm:way:1001")
        self.assertEqual(way["properties"]["kind"], "no_sidewalk")
        self.assertEqual(way["properties"]["probability"], 0.9)
        self.assertEqual(way["geometry"], {
            "type": "LineString",
            "coordinates": [[-80.3745, 25.757], [-80.373, 25.7578]],
        })

    def test_ignores_non_ways_and_degenerate_geometry(self):
        collection = sidewalks.parse_response(fixture_payload())
        ids = {f["id"] for f in collection["features"]}
        self.assertNotIn("osm:way:2001", ids)  # node
        self.assertNotIn("osm:way:1005", ids)  # single-vertex way


class CacheTests(unittest.TestCase):
    def test_roundtrip_and_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sidewalks.geojson"
            collection = sidewalks.parse_response(fixture_payload())
            self.assertFalse(sidewalks.cache_is_fresh(path))
            sidewalks.save_cache(collection, path)
            self.assertEqual(sidewalks.load_cache(path), collection)

            now = datetime.now(timezone.utc)
            self.assertTrue(sidewalks.cache_is_fresh(path, now))
            stale = (now - timedelta(days=2)).timestamp()
            os.utime(path, (stale, stale))
            self.assertFalse(sidewalks.cache_is_fresh(path, now))


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_cache_skips_the_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sidewalks.geojson"
            collection = sidewalks.parse_response(fixture_payload())
            sidewalks.save_cache(collection, path)
            with patch.object(sidewalks, "query_overpass", new=AsyncMock()) as query:
                result = await sidewalks.fetch(path=path)
            query.assert_not_awaited()
            self.assertEqual(result, collection)

    async def test_stale_cache_queries_once_and_writes_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sidewalks.geojson"
            with patch.object(sidewalks, "query_overpass",
                              new=AsyncMock(return_value=fixture_payload())) as query:
                result = await sidewalks.fetch(path=path, force=True)
            query.assert_awaited_once()
            self.assertEqual(len(result["features"]), 3)
            self.assertEqual(sidewalks.load_cache(path), result)


class RegisterTests(unittest.IsolatedAsyncioTestCase):
    async def test_batches_upserts_with_probability_and_stable_ids(self):
        collection = sidewalks.parse_response(fixture_payload())
        bulk_write = AsyncMock(return_value=SimpleNamespace(upserted_count=3))
        db = SimpleNamespace(intel_cache=SimpleNamespace(bulk_write=bulk_write))
        now = datetime.now(timezone.utc)

        inserted = await sidewalks.register_ways(db, collection["features"], now)

        self.assertEqual(inserted, 3)
        operations, = bulk_write.call_args.args
        self.assertFalse(bulk_write.call_args.kwargs["ordered"])
        self.assertEqual(len(operations), 3)
        document = operations[0]._doc["$setOnInsert"]
        self.assertEqual(operations[0]._filter, {"_id": "belief:osm:way:1001"})
        self.assertTrue(operations[0]._upsert)
        self.assertEqual(document["hazard_type"], "no_sidewalk")
        self.assertEqual(document["hazard_id"], "osm:way:1001")
        self.assertAlmostEqual(document["prior_log_odds"], log_odds(0.9))
        self.assertAlmostEqual(document["log_odds"], log_odds(0.9))
        self.assertEqual(document["evidence"], {})

    async def test_empty_batch_makes_no_write(self):
        bulk_write = AsyncMock()
        db = SimpleNamespace(intel_cache=SimpleNamespace(bulk_write=bulk_write))
        inserted = await sidewalks.register_ways(db, [], datetime.now(timezone.utc))
        self.assertEqual(inserted, 0)
        bulk_write.assert_not_awaited()


class CoverageTests(unittest.TestCase):
    def test_counts_ways_near_each_campus(self):
        collection = sidewalks.parse_response(fixture_payload())
        counts = sidewalks.coverage_counts(collection)
        self.assertEqual(counts, {"MMC": 1, "BBC": 1})

    def test_radius_excludes_far_ways(self):
        collection = sidewalks.parse_response(fixture_payload())
        counts = sidewalks.coverage_counts(collection, radius_m=100)
        self.assertEqual(counts, {"MMC": 1, "BBC": 1})

    def test_haversine_known_distance(self):
        # ~111 km per degree of latitude.
        distance = sidewalks.haversine_m(25.0, -80.0, 26.0, -80.0)
        self.assertTrue(math.isclose(distance, 111195, rel_tol=1e-3))


if __name__ == "__main__":
    unittest.main()
