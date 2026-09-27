"""Ingestion: our own Sentinel-1 flood extent on Earth Engine, the fallback when GFM isn't
available (#9). AGENTS.md › Satellite: latest pass vs a dry-season baseline (VV backscatter drop),
minus permanent water (JRC Global Surface Water), vectorised on Earth Engine's side so no raster
ever leaves it. Earth Engine calls are blocking; they run in a worker thread.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from shapely.geometry import shape

from app.config import get_settings
from app.ingestion.satellite import apply_flood_polygons
from app.routing.beliefs import utc

log = logging.getLogger(__name__)

MIAMI_BBOX = [-80.45, 25.55, -80.10, 25.98]
LATEST_WITHIN = timedelta(days=12)  # Sentinel-1 revisits Miami every few days
DRY_SEASON = ("01-15", "04-15")  # South Florida's dry season, the "no flood" baseline
VV_DROP_DB = -3.0  # open water is far darker than a street or lawn in VV
SPECKLE_RADIUS_M = 40
PERMANENT_WATER_OCCURRENCE = 50  # % of time water in JRC GSW: bays, canals, lakes
SCALE_M = 20
MIN_AREA_M2 = 5000


def initialize():
    import ee
    s = get_settings()
    project = s.earth_engine_project or s.google_cloud_project
    if not project:
        raise RuntimeError("EARTH_ENGINE_PROJECT (or GOOGLE_CLOUD_PROJECT) is not set")
    ee.Initialize(project=project)  # the Cloud Run service account / local application-default login
    return ee


def build(ee, now: datetime):
    """(flood polygons FeatureCollection, the latest pass Image)."""
    aoi = ee.Geometry.Rectangle(MIAMI_BBOX)
    s1 = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(aoi)
          .filter(ee.Filter.eq("instrumentMode", "IW"))
          .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
          .select("VV"))
    latest = s1.filterDate(ee.Date(now - LATEST_WITHIN), ee.Date(now)).sort("system:time_start", False).first()
    # Same orbit direction as the latest pass, so the geometry matches the baseline.
    same_orbit = s1.filter(ee.Filter.eq("orbitProperties_pass", latest.get("orbitProperties_pass")))
    year = now.year if now.month > 4 else now.year - 1
    baseline = same_orbit.filterDate(f"{year}-{DRY_SEASON[0]}", f"{year}-{DRY_SEASON[1]}").median()
    smooth = latest.focalMedian(SPECKLE_RADIUS_M, "circle", "meters")
    drop = smooth.subtract(baseline.focalMedian(SPECKLE_RADIUS_M, "circle", "meters"))
    permanent = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").gte(PERMANENT_WATER_OCCURRENCE)
    flooded = drop.lt(VV_DROP_DB).And(permanent.unmask(0).Not()).selfMask()
    vectors = flooded.reduceToVectors(geometry=aoi, scale=SCALE_M, geometryType="polygon", eightConnected=False,
                                      maxPixels=1e10, bestEffort=True)
    vectors = vectors.map(lambda f: f.set("area_m2", f.geometry().area(1))).filter(
        ee.Filter.gte("area_m2", MIN_AREA_M2))
    return vectors, latest


def _fetch_blocking(now: datetime) -> dict | None:
    ee = initialize()
    vectors, latest = build(ee, now)
    info = ee.Dictionary({"time": latest.get("system:time_start"), "id": latest.get("system:index"),
                          "features": vectors.limit(500)}).getInfo()  # one round trip
    if not info or info.get("time") is None:
        return None
    polygons = [shape(f["geometry"]) for f in info["features"]["features"]]
    return {"pass_time": datetime.fromtimestamp(info["time"] / 1000, tz=timezone.utc), "pass_id": info["id"],
            "polygons": polygons}


async def fetch(now: datetime) -> dict | None:
    return await asyncio.to_thread(_fetch_blocking, now)


async def run(db, now: datetime | None = None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    scene = await fetch(now)
    if scene is None:
        return {"source": "s1", "new_pass": False}
    if await db.intel_cache.find_one({"_id": f"satellite_pass:s1:{scene['pass_id']}"}):
        return {"source": "s1", "new_pass": False, "pass_id": scene["pass_id"]}
    result = await apply_flood_polygons(db, scene["polygons"], scene["pass_time"], "s1", scene["pass_id"], now)
    await db.intel_cache.update_one({"_id": f"satellite_pass:s1:{scene['pass_id']}"}, {"$setOnInsert": {
        "type": "satellite_pass", "source": "s1", "pass_time": scene["pass_time"], "created_at": now,
        "expires_at": now + timedelta(days=30)}}, upsert=True)
    return {"source": "s1", "new_pass": True, **result}
