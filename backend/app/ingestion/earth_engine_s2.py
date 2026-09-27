"""Ingestion: construction sites from Sentinel-2 change detection, confirmed by Gemini vision (#16).

AGENTS.md › Satellite, construction rows. Detect mode: a cloud-masked composite of the last 30 days
vs the same 30 days a year earlier; an NDVI drop plus a brightness rise over ≥ ~0.5 ha is a
candidate. Each candidate's before/after true-colour chips (Earth Engine thumbnails of Copernicus
data, never Google imagery) go to Gemini. A confirmed site adds `satellite` evidence to a nearby
City permit/project hazard (#5) or registers a new `construction` hazard. Permit mode (fallback)
only checks chips at the City's active permit sites. Weekly; 10 m pixels and clouds mean large
sites only.
"""
import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone

import httpx
from shapely.geometry import mapping, shape

from app.agents.satellite_check import check_site
from app.ingestion.earth_engine_s1 import MIAMI_BBOX, initialize
from app.ingestion.here_incidents import clear_missing
from app.routing.belief_config import BELIEF_CONFIG as C
from app.routing.beliefs import (
    add_evidence,
    contribution,
    log_odds,
    register_hazard,
    utc,
)

log = logging.getLogger(__name__)

WINDOW = timedelta(days=30)
NDVI_DROP = 0.2
BRIGHTNESS_RISE = 0.03  # mean visible reflectance (0-1)
MIN_AREA_M2 = 5000  # ~0.5 ha
MAX_SITES = 10  # Gemini calls per run: the job must fit in Cloud Run's 300 s
CHIP_PADDING_M = 150
CHIP_PIXELS = 256
MIN_CONFIDENCE = 0.6
NEAR_PERMIT_DEG = 0.0015  # ~150 m
EVIDENCE_TTL = timedelta(days=45)
ACTIVE_PERMIT_LOG_ODDS = log_odds(0.8) - 1e-6  # City status active / closed
SOURCE_LABEL = "Sentinel-2 + Gemini"
CLOUDY_SCL = [3, 8, 9, 10, 11]  # cloud shadow, clouds (medium, high), cirrus, snow


def composite(ee, aoi, start: datetime, end: datetime):
    def mask(image):
        scl = image.select("SCL")
        clear = scl.neq(CLOUDY_SCL[0])
        for value in CLOUDY_SCL[1:]:
            clear = clear.And(scl.neq(value))
        return image.updateMask(clear).divide(10000)

    return (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(aoi)
            .filterDate(ee.Date(start), ee.Date(end)).map(mask).median())


def build_candidates(ee, now: datetime):
    """(candidate polygons FeatureCollection, before composite, after composite)."""
    aoi = ee.Geometry.Rectangle(MIAMI_BBOX)
    after = composite(ee, aoi, now - WINDOW, now)
    before = composite(ee, aoi, now - WINDOW - timedelta(days=365), now - timedelta(days=365))

    def ndvi(image):
        return image.normalizedDifference(["B8", "B4"])

    def brightness(image):
        return image.select(["B2", "B3", "B4"]).reduce(ee.Reducer.mean())

    water = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").gte(50).unmask(0)
    changed = (ndvi(before).subtract(ndvi(after)).gt(NDVI_DROP)
               .And(brightness(after).subtract(brightness(before)).gt(BRIGHTNESS_RISE))
               .And(water.Not())).selfMask()
    vectors = changed.reduceToVectors(geometry=aoi, scale=10, geometryType="polygon", eightConnected=True,
                                      maxPixels=1e10, bestEffort=True)
    vectors = (vectors.map(lambda f: f.set("area_m2", f.geometry().area(1)))
               .filter(ee.Filter.gte("area_m2", MIN_AREA_M2)).sort("area_m2", False).limit(MAX_SITES))
    return vectors, before, after


def chip_urls(ee, before, after, geometry) -> tuple[str, str]:
    region = ee.Geometry(mapping(geometry)).buffer(CHIP_PADDING_M).bounds()
    params = {"region": region, "dimensions": CHIP_PIXELS, "format": "png"}

    def url(image):
        return image.visualize(bands=["B4", "B3", "B2"], min=0, max=0.3).getThumbURL(params)

    return url(before), url(after)


def _detect_blocking(now: datetime) -> list[dict]:
    ee = initialize()
    vectors, before, after = build_candidates(ee, now)
    features = vectors.getInfo().get("features", [])
    sites = []
    for feature in features:
        geometry = shape(feature["geometry"])
        before_url, after_url = chip_urls(ee, before, after, geometry)
        sites.append({"geometry": geometry, "area_m2": feature.get("properties", {}).get("area_m2"),
                      "before_url": before_url, "after_url": after_url, "hazard_id": None})
    return sites


def _permit_chips_blocking(permits: list[dict], now: datetime) -> list[dict]:
    ee = initialize()
    aoi = ee.Geometry.Rectangle(MIAMI_BBOX)
    after = composite(ee, aoi, now - WINDOW, now)
    before = composite(ee, aoi, now - WINDOW - timedelta(days=365), now - timedelta(days=365))
    sites = []
    for permit in permits:
        geometry = shape(permit["geometry"])
        before_url, after_url = chip_urls(ee, before, after, geometry)
        sites.append({"geometry": geometry, "before_url": before_url, "after_url": after_url,
                      "hazard_id": permit["hazard_id"], "context": (permit.get("properties") or {}).get("title", "")})
    return sites


async def active_permits(db, limit: int = MAX_SITES) -> list[dict]:
    """The City's active construction projects/permits, largest first."""
    docs = await db.intel_cache.find({"type": "hazard_belief", "hazard_type": "construction",
                                      "hazard_id": {"$regex": "^city:"}}).to_list(length=None)
    active = [d for d in docs if d.get("prior_log_odds", -99) >= ACTIVE_PERMIT_LOG_ODDS]
    return sorted(active, key=lambda d: shape(d["geometry"]).area, reverse=True)[:limit]


def site_key(geometry) -> str:
    return hashlib.sha1(geometry.simplify(0.0001).wkt.encode()).hexdigest()[:12]


async def confirm_and_apply(db, sites: list[dict], now: datetime, client: httpx.AsyncClient, run_id: str) -> dict:
    permits = await db.intel_cache.find({"type": "hazard_belief", "hazard_id": {"$regex": "^city:"}}).to_list(
        length=None)
    nearby_index = [(d["hazard_id"], shape(d["geometry"]).buffer(NEAR_PERMIT_DEG)) for d in permits
                    if d.get("hazard_type") in ("construction", "closure")]
    confirmed, evidence_added, registered = 0, set(), set()
    for site in sites:
        try:
            before = (await client.get(site["before_url"])).raise_for_status().content
            after = (await client.get(site["after_url"])).raise_for_status().content
        except httpx.HTTPError:
            log.warning("Couldn't download Sentinel-2 chips", exc_info=True)
            continue
        check = await check_site(before, after, site.get("context", ""))
        if not check or not check["is_construction"] or check["confidence"] < MIN_CONFIDENCE:
            continue
        confirmed += 1
        key = site_key(site["geometry"])
        targets = [site["hazard_id"]] if site.get("hazard_id") else \
            [hazard_id for hazard_id, area in nearby_index if area.intersects(site["geometry"])]
        for hazard_id in targets:
            evidence_id = f"evidence:satellite:s2:{run_id}:{key}:{hazard_id}"
            await db.intel_cache.update_one({"_id": evidence_id}, {"$setOnInsert": {
                "_id": evidence_id, "type": "satellite_check", "source": "s2", "hazard_id": hazard_id,
                "title": f"{SOURCE_LABEL}: {check['description']}", "summary": check["description"],
                "confidence": check["confidence"], "before_image_url": site["before_url"],
                "after_image_url": site["after_url"], "source_url": site["after_url"], "created_at": utc(now),
                "expires_at": utc(now) + EVIDENCE_TTL, "log_odds": contribution("satellite", now, now),
                "geometry": mapping(site["geometry"])}}, upsert=True)
            await add_evidence(db, hazard_id, evidence_id, "satellite", now, now)
            evidence_added.add(hazard_id)
        if not targets:
            hazard_id = f"s2:{key}"
            await register_hazard(db, hazard_id, "construction", mapping(site["geometry"]), {
                "probability": C["satellite_construction_probability"], "severity": 2,
                "title": "Construction seen by satellite", "description": check["description"],
                "source_label": SOURCE_LABEL, "source_url": site["after_url"]}, now)
            registered.add(hazard_id)
    return {"sites_checked": len(sites), "confirmed": confirmed, "permits_confirmed": len(evidence_added),
            "new_hazards": len(registered), "registered_ids": registered}


async def run(db, now: datetime | None = None, mode: str = "detect",
              client: httpx.AsyncClient | None = None) -> dict:
    """mode "detect": change detection over Miami-Dade; "permits": chips at active City permits only."""
    now = utc(now or datetime.now(timezone.utc))
    if mode == "permits":
        sites = await asyncio.to_thread(_permit_chips_blocking, await active_permits(db), now)
    else:
        sites = await asyncio.to_thread(_detect_blocking, now)
    owned = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        result = await confirm_and_apply(db, sites, now, client, now.strftime("%Y%m%d"))
    finally:
        if owned:
            await client.aclose()
    registered = result.pop("registered_ids")
    # Detect mode sees the whole county, so a satellite-only site it no longer confirms fades out.
    result["cleared"] = await clear_missing(db, "s2:", registered, now) if mode == "detect" else 0
    return {"source": "s2", "mode": mode, **result}
