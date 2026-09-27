"""Ingestion: Copernicus Global Flood Monitoring (GFM) → observed flood extent (#9).

GFM runs an automatic flood-mapping ensemble on every Sentinel-1 radar pass and serves it through
its v2 API (https://api.gfm.eodc.eu/v2/, a free account). Flow: log in → find or create the Miami
area of interest → latest product in the last two weeks (its time is the satellite pass time) →
download link → GeoTIFF flood mask (the ENSEMBLE_FLOOD layer; GFM already excludes the pixels it
can't judge, e.g. between buildings) → polygons in lat/lng → satellite.apply_flood_polygons.
A product is processed once; the hourly job only downloads when a new pass appears.
"""
import io
import logging
import zipfile
from datetime import datetime, timedelta, timezone

import httpx
from shapely.geometry import box, shape

from app.config import get_settings
from app.ingestion.satellite import apply_flood_polygons
from app.routing.beliefs import utc

log = logging.getLogger(__name__)

API = "https://api.gfm.eodc.eu/v2"
AOI_NAME = "mapay-miami"
MIAMI_BBOX = (-80.45, 25.55, -80.10, 25.98)  # west, south, east, north
LOOKBACK = timedelta(days=14)
MIN_AREA_M2 = 1500  # a few 20 m pixels: drop speckle
FLOOD_LAYER = "ENSEMBLE_FLOOD"


class GfmNotConfigured(RuntimeError):
    """No GFM account in the settings."""


def configured() -> bool:
    s = get_settings()
    return bool(s.gfm_email and s.gfm_password)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def login(client: httpx.AsyncClient) -> tuple[str, str]:
    """(bearer token, user id). GFM returns the user id as client_id."""
    s = get_settings()
    if not configured():
        raise GfmNotConfigured("GFM_EMAIL / GFM_PASSWORD are not set")
    response = await client.post(f"{API}/auth/login", json={"email": s.gfm_email, "password": s.gfm_password})
    response.raise_for_status()
    body = response.json()
    return body["access_token"], body["client_id"]


async def ensure_aoi(client: httpx.AsyncClient, token: str, user_id: str) -> str:
    pinned = get_settings().gfm_aoi_id
    if pinned:
        return pinned
    response = await client.get(f"{API}/aoi/user/{user_id}", headers=_auth(token))
    response.raise_for_status()
    for aoi in response.json().get("aois", []):
        if aoi.get("aoi_name") == AOI_NAME:
            return aoi["aoi_id"]
    west, south, east, north = MIAMI_BBOX
    geojson = {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north], [west, north],
                                                   [west, south]]]}
    response = await client.post(f"{API}/aoi/create", headers=_auth(token), json={
        "aoi_name": AOI_NAME, "description": "Mapay: Miami-Dade street flooding", "user_id": user_id,
        "geoJSON": geojson})
    response.raise_for_status()
    return response.json()["aoi_id"]


def _parse_time(value: str) -> datetime:
    return utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


async def latest_product(client: httpx.AsyncClient, token: str, aoi_id: str, now: datetime) -> dict | None:
    params = {"time": "range", "from": (now - LOOKBACK).strftime("%Y-%m-%dT%H:%M:%S"),
              "to": now.strftime("%Y-%m-%dT%H:%M:%S")}
    response = await client.get(f"{API}/aoi/{aoi_id}/products", headers=_auth(token), params=params)
    response.raise_for_status()
    products = response.json().get("products") or []
    if not products:
        return None
    latest = max(products, key=lambda p: _parse_time(p["product_time"]))
    return {"product_id": str(latest["product_id"]), "pass_time": _parse_time(latest["product_time"])}


async def download(client: httpx.AsyncClient, token: str, product_id: str, user_id: str) -> bytes:
    response = await client.get(f"{API}/download/product/{product_id}/{user_id}", headers=_auth(token))
    response.raise_for_status()
    archive = await client.get(response.json()["download_link"], timeout=180)
    archive.raise_for_status()
    return archive.content


def flood_raster(content: bytes) -> bytes:
    """The flood-extent GeoTIFF: the file itself, or the ENSEMBLE_FLOOD member of a zip."""
    if not zipfile.is_zipfile(io.BytesIO(content)):
        return content
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith((".tif", ".tiff"))]
        flood = [n for n in names if FLOOD_LAYER in n.upper() and "LIKELIHOOD" not in n.upper()]
        if not flood:
            raise ValueError(f"No {FLOOD_LAYER} layer in the GFM product: {names}")
        return archive.read(flood[0])


def polygons_from_geotiff(content: bytes) -> list:
    """Flooded pixels (value 1) → lat/lng polygons clipped to Miami, speckle dropped."""
    import rasterio
    from rasterio.features import shapes
    from rasterio.warp import transform_geom

    miami = box(*MIAMI_BBOX)
    polygons = []
    with rasterio.MemoryFile(content) as memory, memory.open() as dataset:
        band = dataset.read(1)
        projected = dataset.crs is not None and not dataset.crs.is_geographic  # GFM: Equi7Grid, metres
        for geometry, value in shapes(band, mask=band == 1, transform=dataset.transform):
            if value != 1:
                continue
            if projected and shape(geometry).area < MIN_AREA_M2:
                continue
            lnglat = shape(transform_geom(dataset.crs, "EPSG:4326", geometry))
            clipped = lnglat.intersection(miami)
            if not clipped.is_empty:
                polygons.append(clipped.simplify(0.00005))
    return polygons


async def fetch(db, now: datetime, client: httpx.AsyncClient | None = None) -> dict | None:
    """The latest unprocessed product: {product_id, pass_time, polygons}, or None."""
    owned = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        token, user_id = await login(client)
        aoi_id = await ensure_aoi(client, token, user_id)
        product = await latest_product(client, token, aoi_id, now)
        if product is None or await db.intel_cache.find_one({"_id": f"satellite_pass:gfm:{product['product_id']}"}):
            return None
        raster = flood_raster(await download(client, token, product["product_id"], user_id))
        return {**product, "polygons": polygons_from_geotiff(raster)}
    finally:
        if owned:
            await client.aclose()


async def run(db, now: datetime | None = None, client: httpx.AsyncClient | None = None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    product = await fetch(db, now, client)
    if product is None:
        return {"source": "gfm", "new_pass": False}
    result = await apply_flood_polygons(db, product["polygons"], product["pass_time"], "gfm",
                                        product["product_id"], now)
    await db.intel_cache.update_one({"_id": f"satellite_pass:gfm:{product['product_id']}"}, {"$setOnInsert": {
        "type": "satellite_pass", "source": "gfm", "pass_time": product["pass_time"], "created_at": now,
        "expires_at": now + timedelta(days=30)}}, upsert=True)
    return {"source": "gfm", "new_pass": True, **result}
