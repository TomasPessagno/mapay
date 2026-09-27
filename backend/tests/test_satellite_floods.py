import io
import re
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
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


def geotiff(zip_it=True) -> bytes:
    """A 20 m flood mask in Web Mercator over Brickell: one flooded block + one speckle pixel."""
    import rasterio
    from rasterio.transform import from_origin
    x0, y0 = -8_933_200.0, 2_970_600.0  # ~(-80.249, 25.788)
    data = np.zeros((50, 50), dtype="uint8")
    data[10:20, 10:25] = 1  # 200 m x 300 m
    data[40, 40] = 1  # one pixel: speckle
    buffer = io.BytesIO()
    with rasterio.MemoryFile() as memory:
        with memory.open(driver="GTiff", width=50, height=50, count=1, dtype="uint8", crs="EPSG:3857",
                         transform=from_origin(x0, y0, 20, 20)) as dataset:
            dataset.write(data, 1)
        tif = memory.read()
    if not zip_it:
        return tif
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ENSEMBLE_LIKELIHOOD_20261008T110200.tif", b"not this one")
        archive.writestr("ENSEMBLE_FLOOD_20261008T110200.tif", tif)
        archive.writestr("metadata.json", b"{}")
    return buffer.getvalue()


class GeoTiffTests(unittest.TestCase):
    def test_vectorises_reprojects_and_drops_speckle(self):
        polygons = gfm.polygons_from_geotiff(gfm.flood_raster(geotiff()))
        self.assertEqual(len(polygons), 1)
        # The flooded block's corners (pixels 10..25 x 10..20 at 20 m), projected independently.
        from rasterio.warp import transform
        xs, ys = transform("EPSG:3857", "EPSG:4326", [-8_933_200 + 200, -8_933_200 + 500],
                           [2_970_600 - 400, 2_970_600 - 200])
        for got, want in zip(polygons[0].bounds, (xs[0], ys[0], xs[1], ys[1]), strict=True):
            self.assertAlmostEqual(got, want, places=4)

    def test_zip_without_flood_layer_is_an_error(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("ENSEMBLE_LIKELIHOOD.tif", b"x")
        with self.assertRaises(ValueError):
            gfm.flood_raster(buffer.getvalue())


class GfmApi:
    def __init__(self, products=None):
        self.calls = []
        self.products = products if products is not None else [
            {"product_id": 11, "product_time": "2026-10-02T23:10:00"},
            {"product_id": 12, "product_time": "2026-10-08T11:02:00"}]

    def __call__(self, request):
        self.calls.append(f"{request.method} {request.url.path}")
        path = request.url.path
        if path == "/v2/auth/login":
            return httpx.Response(200, json={"access_token": "tok", "client_id": "user-1", "expires_in": 3600})
        assert request.headers.get("Authorization") == "Bearer tok" or request.url.host == "files.example"
        if path == "/v2/aoi/user/user-1":
            return httpx.Response(200, json={"aois": [{"aoi_id": "other", "aoi_name": "someone else"}]})
        if path == "/v2/aoi/create":
            return httpx.Response(201, json={"aoi_id": "aoi-miami"})
        if path == "/v2/aoi/aoi-miami/products":
            return httpx.Response(200, json={"aoi_id": "aoi-miami", "products": self.products})
        if path == "/v2/download/product/12/user-1":
            return httpx.Response(200, json={"download_link": "https://files.example/p12.zip"})
        if request.url.host == "files.example":
            return httpx.Response(200, content=geotiff())
        return httpx.Response(404)


def settings(**overrides):
    base = {"gfm_email": "me@example.org", "gfm_password": "pw", "gfm_aoi_id": ""}
    return patch("app.ingestion.gfm.get_settings", return_value=SimpleNamespace(**{**base, **overrides}))


class GfmRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_pass_end_to_end_then_skipped(self):
        cache = FakeIntelCache()
        db = SimpleNamespace(intel_cache=cache)
        api = GfmApi()
        with settings():
            client = httpx.AsyncClient(transport=httpx.MockTransport(api))
            result = await gfm.run(db, NOW, client)
            self.assertTrue(result["new_pass"])
            self.assertEqual(result["pass_time"], "2026-10-08T11:02:00+00:00")  # the newer product
            self.assertEqual(result["new_hazards"], 1)
            self.assertIn("POST /v2/aoi/create", api.calls)  # no Miami AOI yet, so it was created
            downloads = sum("download" in c for c in api.calls)
            again = await gfm.run(db, NOW, client)
        self.assertEqual(again, {"source": "gfm", "new_pass": False})
        self.assertEqual(sum("download" in c for c in api.calls), downloads)  # not downloaded twice

    async def test_no_products_and_pinned_aoi(self):
        api = GfmApi(products=[])
        with settings(gfm_aoi_id="aoi-miami"):
            result = await gfm.run(SimpleNamespace(intel_cache=FakeIntelCache()), NOW,
                                   httpx.AsyncClient(transport=httpx.MockTransport(api)))
        self.assertEqual(result, {"source": "gfm", "new_pass": False})
        self.assertNotIn("POST /v2/aoi/create", api.calls)

    async def test_not_configured(self):
        with settings(gfm_email=""), self.assertRaises(gfm.GfmNotConfigured):
            await gfm.run(SimpleNamespace(intel_cache=FakeIntelCache()), NOW,
                          httpx.AsyncClient(transport=httpx.MockTransport(GfmApi())))


class JobTests(unittest.IsolatedAsyncioTestCase):
    async def test_gfm_job_falls_back_to_earth_engine(self):
        with patch("app.ingestion.gfm.configured", return_value=True), \
             patch("app.ingestion.gfm.run", AsyncMock(side_effect=httpx.ConnectError("down"))), \
             patch("app.ingestion.earth_engine_s1.run", AsyncMock(return_value={"source": "s1"})) as ee_run:
            self.assertEqual(await internal.JOBS["gfm"]("db", NOW), {"source": "s1"})
        ee_run.assert_awaited_once()
        with patch("app.ingestion.gfm.configured", return_value=False), \
             patch("app.ingestion.earth_engine_s1.run", AsyncMock(return_value={"source": "s1"})):
            self.assertEqual(await internal.JOBS["gfm"]("db", NOW), {"source": "s1"})


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
