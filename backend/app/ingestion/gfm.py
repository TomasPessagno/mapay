"""Ingestion: Copernicus Global Flood Monitoring (GFM) → observed flood extent (#9).

GFM runs an automatic flood-mapping ensemble on every Sentinel-1 radar pass. EODC publishes the
products in an open STAC catalog (https://stac.eodc.eu/api/v1, collection `GFM`; no account), each
with an `ensemble_flood_extent` cloud-optimised GeoTIFF (Equi7Grid, 20 m; 1 = flooded, 0 = dry,
255 = not observed or excluded, e.g. between buildings). The catalog matches on 300 km tiles, and
most passes over the tile don't actually see Miami, so the job walks back from the newest pass,
reads only the Miami window of each COG over HTTP, skips passes that observed under 5 % of it, and
applies the newest one that did (polygons in lat/lng → satellite.apply_flood_polygons). Every pass
is read once (a marker remembers it, with its coverage).
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx
from shapely.geometry import box, shape

from app.ingestion.satellite import apply_flood_polygons
from app.routing.beliefs import utc

log = logging.getLogger(__name__)

STAC_SEARCH = "https://stac.eodc.eu/api/v1/search"
COLLECTION = "GFM"
ASSET = "ensemble_flood_extent"
MIAMI_BBOX = (-80.45, 25.55, -80.10, 25.98)  # west, south, east, north
LOOKBACK = timedelta(days=14)  # older passes aren't "current" flooding
MIN_AREA_M2 = 1500  # a few 20 m pixels: drop speckle
MIN_COVERAGE = 0.05  # share of the Miami window the pass must have observed


def _parse_time(value: str) -> datetime:
    return utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


async def recent_passes(client: httpx.AsyncClient, now: datetime, lookback: timedelta = LOOKBACK) -> list[dict]:
    """GFM passes over the Miami tile in `lookback`, newest first: [{id, pass_time, urls}]. One pass
    can be split across neighbouring scenes seconds apart; they're grouped."""
    body = {"collections": [COLLECTION], "bbox": list(MIAMI_BBOX), "limit": 100,
            "datetime": f"{(now - lookback).strftime('%Y-%m-%dT%H:%M:%SZ')}/{now.strftime('%Y-%m-%dT%H:%M:%SZ')}"}
    response = await client.post(STAC_SEARCH, json=body)
    response.raise_for_status()
    items = sorted((f for f in response.json().get("features", []) if ASSET in f.get("assets", {})),
                   key=lambda f: _parse_time(f["properties"]["datetime"]), reverse=True)
    passes: list[dict] = []
    for item in items:
        when = _parse_time(item["properties"]["datetime"])
        if passes and passes[-1]["pass_time"] - when <= timedelta(minutes=5):
            passes[-1]["urls"].append(item["assets"][ASSET]["href"])
            passes[-1]["ids"].append(item["id"])
        else:
            passes.append({"pass_time": when, "urls": [item["assets"][ASSET]["href"]], "ids": [item["id"]]})
    return [{"id": max(p["ids"]), "pass_time": p["pass_time"], "urls": sorted(set(p["urls"]))} for p in passes]


def polygons_from_cog(path: str) -> tuple[list, float]:
    """(polygons, observed share) for the Miami window of a GeoTIFF (a URL or a file): flooded pixels
    (value 1) → lat/lng polygons clipped to Miami, speckle dropped; the share of the window that
    was observed (not 255). Only the window's bytes are read from a COG."""
    import rasterio
    from rasterio.features import shapes
    from rasterio.warp import transform_bounds, transform_geom
    from rasterio.windows import from_bounds

    miami = box(*MIAMI_BBOX)
    polygons = []
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"), rasterio.open(path) as dataset:
        left, bottom, right, top = transform_bounds("EPSG:4326", dataset.crs, *MIAMI_BBOX)
        window = from_bounds(left, bottom, right, top, dataset.transform).round_offsets().round_lengths()
        window = window.intersection(rasterio.windows.Window(0, 0, dataset.width, dataset.height))
        band = dataset.read(1, window=window)
        observed = float((band != 255).mean()) if band.size else 0.0
        transform = dataset.window_transform(window)
        projected = dataset.crs is not None and not dataset.crs.is_geographic  # Equi7Grid: metres
        for geometry, value in shapes(band, mask=band == 1, transform=transform):
            if value != 1:
                continue
            if projected and shape(geometry).area < MIN_AREA_M2:
                continue
            clipped = shape(transform_geom(dataset.crs, "EPSG:4326", geometry)).intersection(miami)
            if not clipped.is_empty:
                polygons.append(clipped.simplify(0.00005))
    return polygons, observed


async def run(db, now: datetime | None = None, client: httpx.AsyncClient | None = None,
              lookback: timedelta = LOOKBACK) -> dict:
    """Apply the newest pass that observed Miami (if not applied yet). `lookback` is longer only
    for a one-off demo pre-run."""
    now = utc(now or datetime.now(timezone.utc))
    owned = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        passes = await recent_passes(client, now, lookback)
    finally:
        if owned:
            await client.aclose()
    skipped = 0
    for candidate in passes:
        marker = f"satellite_pass:gfm:{candidate['id']}"
        seen = await db.intel_cache.find_one({"_id": marker})
        if seen and seen.get("observed", 1.0) >= MIN_COVERAGE:
            return {"source": "gfm", "new_pass": False, "pass_time": candidate["pass_time"].isoformat(),
                    "skipped_without_coverage": skipped}
        if seen:  # read before: it didn't see Miami
            skipped += 1
            continue
        polygons, observed = [], 0.0
        for url in candidate["urls"]:
            found, share = polygons_from_cog(url)
            polygons += found
            observed = max(observed, share)
        await db.intel_cache.update_one({"_id": marker}, {"$setOnInsert": {
            "type": "satellite_pass", "source": "gfm", "pass_time": candidate["pass_time"], "observed": observed,
            "created_at": now, "expires_at": now + timedelta(days=30)}}, upsert=True)
        if observed < MIN_COVERAGE:
            skipped += 1
            continue
        result = await apply_flood_polygons(db, polygons, candidate["pass_time"], "gfm", candidate["id"], now)
        return {"source": "gfm", "new_pass": True, "observed": round(observed, 3),
                "skipped_without_coverage": skipped, **result}
    return {"source": "gfm", "new_pass": False, "skipped_without_coverage": skipped}
