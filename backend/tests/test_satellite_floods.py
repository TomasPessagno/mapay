import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import numpy as np
from shapely.geometry import Point, box

from app.ingestion import earth_engine_s1, gfm, satellite
from app.routers import internal
from app.routing.beliefs import log_odds

NOW = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)
PASS = datetime(2026, 10, 8, 11, 2, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length=None):
        return list(self.docs)


class FakeIntelCache:
    """Enough Mongo for register_hazard, add_evidence, clear_missing and the pass markers."""

    def __init__(self):
        self.docs = {}

    @staticmethod
    def _matches(doc, query):
        for key, value in query.items():
            if isinstance(value, dict) and "$regex" in value:
                if not re.search(value["$regex"], str(doc.get(key, ""))):
                    return False
            elif isinstance(value, dict) and "$exists" in value:
                present = _get(doc, key) is not None
                if present != value["$exists"]:
                    return False
            elif _get(doc, key) != value:
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
        for key, value in update.get("$set", {}).items():
            _set(doc, key, value)
        for key, value in update.get("$max", {}).items():
            doc[key] = max(doc.get(key, value), value)
        return SimpleNamespace(matched_count=1)


def _get(doc, path):
    for part in path.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return None
        doc = doc[part]
    return doc


def _set(doc, path, value):
    *parents, last = path.split(".")
    for part in parents:
        doc = doc.setdefault(part, {})
    doc[last] = value


def hotspot(cache, hazard_id, lng, lat, prior=0.4):
    value = log_odds(prior)
    cache.docs[f"belief:{hazard_id}"] = {
        "_id": f"belief:{hazard_id}", "type": "hazard_belief", "hazard_id": hazard_id, "hazard_type": "flood",
        "geometry": {"type": "Point", "coordinates": [lng, lat]}, "severity": 3, "prior_log_odds": value,
        "log_odds": value, "evidence": {}, "created_at": NOW, "last_updated": NOW}


BRICKELL_BLOCK = box(-80.1905, 25.7612, -80.1890, 25.7625)  # around the Brickell Bay Dr hotspot
FAR_FIELD = box(-80.40, 25.60, -80.39, 25.61)


class ApplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirms_hotspots_and_registers_new_floods(self):
        cache = FakeIntelCache()
        db = SimpleNamespace(intel_cache=cache)
        hotspot(cache, "flood:brickell-bay-dr-se-12th-st", -80.18974, 25.76185)
        hotspot(cache, "flood:far-away", -80.13, 25.85)
        result = await satellite.apply_flood_polygons(db, [BRICKELL_BLOCK, FAR_FIELD], PASS, "gfm", "p1", NOW)
        self.assertEqual((result["confirmed_hazards"], result["new_hazards"]), (1, 1))
        confirmed = cache.docs["belief:flood:brickell-bay-dr-se-12th-st"]
        self.assertAlmostEqual(confirmed["log_odds"], log_odds(0.4) + 1.0)
        self.assertEqual([e["source"] for e in confirmed["evidence"].values()], ["satellite"])
        self.assertEqual(cache.docs["belief:flood:far-away"]["evidence"], {})
        evidence = [d for d in cache.docs.values() if d.get("type") == "satellite_check"]
        self.assertEqual(evidence[0]["pass_time"], PASS)
        self.assertIn("Oct 08, 11:02 UTC", evidence[0]["title"])
        new = [d for d in cache.docs.values() if d.get("hazard_id", "").startswith("gfm:")]
        self.assertAlmostEqual(new[0]["prior_log_odds"], log_odds(0.75))
        self.assertIn("pass Oct 08, 11:02 UTC", new[0]["properties"]["description"])

    async def test_same_pass_twice_is_idempotent_and_next_pass_replaces(self):
        cache = FakeIntelCache()
        db = SimpleNamespace(intel_cache=cache)
        hotspot(cache, "flood:h", -80.18974, 25.76185)
        await satellite.apply_flood_polygons(db, [BRICKELL_BLOCK, FAR_FIELD], PASS, "gfm", "p1", NOW)
        await satellite.apply_flood_polygons(db, [BRICKELL_BLOCK, FAR_FIELD], PASS, "gfm", "p1", NOW)
        self.assertAlmostEqual(cache.docs["belief:flood:h"]["log_odds"], log_odds(0.4) + 1.0)
        result = await satellite.apply_flood_polygons(db, [], PASS + timedelta(days=6), "gfm", "p2", NOW)
        self.assertEqual(result["cleared"], 1)  # the far-field flood wasn't seen again
        old = next(d for d in cache.docs.values() if d.get("hazard_id", "").startswith("gfm:"))
        self.assertAlmostEqual(old["prior_log_odds"], log_odds(0.05))


def geotiff(path) -> str:
    """A 20 m flood mask in Web Mercator over west Miami, written to `path`: one flooded block,
    one speckle pixel, and 255 (no data) around them, like GFM's ensemble_flood_extent."""
    import rasterio
    from rasterio.transform import from_origin
    data = np.full((50, 50), 255, dtype="uint8")
    data[5:45, 5:45] = 0
    data[10:20, 10:25] = 1  # 200 m x 300 m
    data[40, 40] = 1  # one pixel: speckle
    with rasterio.open(path, "w", driver="GTiff", width=50, height=50, count=1, dtype="uint8", crs="EPSG:3857",
                       transform=from_origin(-8_933_200.0, 2_970_600.0, 20, 20)) as dataset:
        dataset.write(data, 1)
    return str(path)


class GeoTiffTests(unittest.TestCase):
    def test_reads_the_miami_window_vectorises_reprojects_and_drops_speckle(self):
        import tempfile

        from rasterio.warp import transform
        with tempfile.TemporaryDirectory() as tmp:
            polygons, observed = gfm.polygons_from_cog(geotiff(f"{tmp}/flood.tif"))
        self.assertEqual(len(polygons), 1)
        self.assertGreater(observed, 0)
        # The flooded block's corners (pixels 10..25 x 10..20 at 20 m), projected independently.
        xs, ys = transform("EPSG:3857", "EPSG:4326", [-8_933_200 + 200, -8_933_200 + 500],
                           [2_970_600 - 400, 2_970_600 - 200])
        for got, want in zip(polygons[0].bounds, (xs[0], ys[0], xs[1], ys[1]), strict=True):
            self.assertAlmostEqual(got, want, places=4)


def stac_item(item_id, when, href="https://data.eodc.eu/x.tif"):
    return {"id": item_id, "properties": {"datetime": when},
            "assets": {"ensemble_flood_extent": {"href": href}, "thumbnail": {"href": "t.png"}}}


def stac_client(features, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        assert str(request.url) == gfm.STAC_SEARCH
        return httpx.Response(200, json={"type": "FeatureCollection", "features": features})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class StacTests(unittest.IsolatedAsyncioTestCase):
    async def test_passes_newest_first_with_their_scenes_grouped(self):
        seen = []
        features = [stac_item("A_20261002", "2026-10-02T23:10:00Z", "https://d/old.tif"),
                    stac_item("B_20261008a", "2026-10-08T11:02:00Z", "https://d/a.tif"),
                    stac_item("B_20261008b", "2026-10-08T11:01:35Z", "https://d/b.tif"),
                    {"id": "no_flood_layer", "properties": {"datetime": "2026-10-09T00:00:00Z"}, "assets": {}}]
        passes = await gfm.recent_passes(stac_client(features, seen), NOW)
        self.assertEqual([p["pass_time"] for p in passes], [PASS, datetime(2026, 10, 2, 23, 10, tzinfo=timezone.utc)])
        self.assertEqual(passes[0]["urls"], ["https://d/a.tif", "https://d/b.tif"])
        query = seen[0]
        self.assertEqual((query["collections"], query["bbox"]), (["GFM"], list(gfm.MIAMI_BBOX)))
        self.assertTrue(query["datetime"].startswith("2026-09-24T15:00:00Z/"))  # 14 days back

    async def test_no_products(self):
        self.assertEqual(await gfm.recent_passes(stac_client([]), NOW), [])


class GfmRunTests(unittest.IsolatedAsyncioTestCase):
    FEATURES: ClassVar[list] = [stac_item("NEW", "2026-10-08T11:02:00Z", "https://d/new.tif"),
                stac_item("OLD", "2026-10-05T23:19:00Z", "https://d/old.tif")]

    async def test_skips_passes_that_missed_miami_and_applies_the_newest_that_saw_it(self):
        cache = FakeIntelCache()
        db = SimpleNamespace(intel_cache=cache)
        reads = {"https://d/new.tif": ([], 0.0), "https://d/old.tif": ([FAR_FIELD], 0.66)}
        with patch("app.ingestion.gfm.polygons_from_cog", side_effect=lambda url: reads[url]) as read:
            first = await gfm.run(db, NOW, stac_client(self.FEATURES))
            second = await gfm.run(db, NOW, stac_client(self.FEATURES))
        self.assertEqual((first["new_pass"], first["pass_time"], first["observed"], first["skipped_without_coverage"]),
                         (True, "2026-10-05T23:19:00+00:00", 0.66, 1))
        self.assertEqual(first["new_hazards"], 1)
        self.assertFalse(second["new_pass"])
        self.assertEqual(read.call_count, 2)  # each pass read once, ever
        self.assertEqual(cache.docs["satellite_pass:gfm:NEW"]["observed"], 0.0)

    async def test_nothing_observed_in_the_lookback(self):
        with patch("app.ingestion.gfm.polygons_from_cog", return_value=([], 0.0)):
            result = await gfm.run(SimpleNamespace(intel_cache=FakeIntelCache()), NOW, stac_client(self.FEATURES))
        self.assertEqual(result, {"source": "gfm", "new_pass": False, "skipped_without_coverage": 2})

    async def test_empty_catalog(self):
        result = await gfm.run(SimpleNamespace(intel_cache=FakeIntelCache()), NOW, stac_client([]))
        self.assertEqual(result, {"source": "gfm", "new_pass": False, "skipped_without_coverage": 0})


class JobTests(unittest.IsolatedAsyncioTestCase):
    async def test_gfm_job_falls_back_to_earth_engine(self):
        with patch("app.ingestion.gfm.run", AsyncMock(side_effect=httpx.ConnectError("down"))), \
             patch("app.ingestion.earth_engine_s1.run", AsyncMock(return_value={"source": "s1"})) as ee_run:
            self.assertEqual(await internal.JOBS["gfm"]("db", NOW), {"source": "s1"})
        ee_run.assert_awaited_once()
        with patch("app.ingestion.gfm.run", AsyncMock(return_value={"source": "gfm"})):
            self.assertEqual(await internal.JOBS["gfm"]("db", NOW), {"source": "gfm"})


class EarthEngineTests(unittest.IsolatedAsyncioTestCase):
    def test_build_uses_sentinel1_vv_baseline_and_permanent_water(self):
        ee = MagicMock()
        earth_engine_s1.build(ee, NOW)
        ee.ImageCollection.assert_called_with("COPERNICUS/S1_GRD")
        ee.Image.assert_called_with("JRC/GSW1_4/GlobalSurfaceWater")
        collection = ee.ImageCollection.return_value.filterBounds.return_value.filter.return_value.filter.return_value
        collection.select.assert_called_with("VV")

    async def test_run_applies_a_new_scene_once(self):
        cache = FakeIntelCache()
        db = SimpleNamespace(intel_cache=cache)
        scene = {"pass_time": PASS, "pass_id": "S1A_IW_20261008", "polygons": [FAR_FIELD]}
        with patch("app.ingestion.earth_engine_s1.fetch", AsyncMock(return_value=scene)):
            first = await earth_engine_s1.run(db, NOW)
            second = await earth_engine_s1.run(db, NOW)
        self.assertEqual((first["new_pass"], first["new_hazards"]), (True, 1))
        self.assertFalse(second["new_pass"])
        self.assertTrue(any(k.startswith("belief:s1:") for k in cache.docs))

    def test_fetch_parses_one_getinfo(self):
        ee = MagicMock()
        ee.Dictionary.return_value.getInfo.return_value = {
            "time": int(PASS.timestamp() * 1000), "id": "S1A_x",
            "features": {"features": [{"geometry": {"type": "Polygon", "coordinates": [
                [[-80.2, 25.8], [-80.19, 25.8], [-80.19, 25.81], [-80.2, 25.8]]]}}]}}
        with patch("app.ingestion.earth_engine_s1.initialize", return_value=ee):
            scene = earth_engine_s1._fetch_blocking(NOW)
        self.assertEqual((scene["pass_time"], scene["pass_id"]), (PASS, "S1A_x"))
        self.assertTrue(scene["polygons"][0].contains(Point(-80.195, 25.803)))
