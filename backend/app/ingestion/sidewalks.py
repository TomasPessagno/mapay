"""Ingestion: OpenStreetMap no-sidewalk ways via Overpass. See AGENTS.md data sources table.

Only ways explicitly tagged as sidewalk-free count: ``sidewalk=no`` / ``sidewalk=none``
or ``sidewalk:both=no``. A missing tag means *unknown*, not "no sidewalk", so it is
deliberately not fetched. The Overpass usage policy allows one query per day, so the
raw response is cached to ``backend/app/data/cache/sidewalks.geojson`` (gitignored)
and reused until it is a day old.

Every way becomes a ``no_sidewalk`` belief with a fixed ``probability`` prior of 0.9
(the upstream tag is explicit) and the stable id ``osm:way:<id>``. Priors never
change, so the registration is a single bulk upsert that leaves existing evidence
untouched.
"""
import asyncio
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pymongo import UpdateOne

from app.routing.beliefs import log_odds, utc

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_URLS = (OVERPASS_URL, "https://overpass.private.coffee/api/interpreter")
# overpass-api.de rejects placeholder contacts (contact@example.com) with 406.
USER_AGENT = "MAPAY/0.1 (FIU ShellHacks 2026 hazard map; no-sidewalk layer; https://github.com/TomasPessagno/mapay)"
REFRESH_SECONDS = 24 * 60 * 60
NO_SIDEWALK_PROBABILITY = 0.9

# West, south, east, north. Covers Miami-Dade including both FIU campuses.
MIAMI_DADE_BBOX = (-80.45, 25.55, -80.10, 25.98)

CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "cache" / "sidewalks.geojson"

# Coverage check targets, in metres from the campus.
MMC = {"name": "MMC", "lat": 25.7574, "lon": -80.3739}
BBC = {"name": "BBC", "lat": 25.9106, "lon": -80.1387}
COVERAGE_RADIUS_M = 2000.0


def build_query(bbox: tuple[float, float, float, float] = MIAMI_DADE_BBOX) -> str:
    west, south, east, north = bbox
    area = f"{south},{west},{north},{east}"
    return (
        "[out:json][timeout:180];\n"
        "(\n"
        f'  way["sidewalk"~"^(no|none)$"]({area});\n'
        f'  way["sidewalk:both"="no"]({area});\n'
        ");\n"
        "out tags geom;\n"
    )


def parse_response(payload: dict) -> dict:
    """Convert an Overpass JSON response to a GeoJSON FeatureCollection of LineStrings."""
    features = []
    for element in payload.get("elements", []):
        geometry = element.get("geometry") or []
        if element.get("type") != "way" or len(geometry) < 2:
            continue
        hazard_id = f"osm:way:{element['id']}"
        tags = element.get("tags", {})
        features.append({
            "type": "Feature",
            "id": hazard_id,
            "geometry": {
                "type": "LineString",
                "coordinates": [[node["lon"], node["lat"]] for node in geometry],
            },
            "properties": {
                "hazard_id": hazard_id,
                "kind": "no_sidewalk",
                "probability": NO_SIDEWALK_PROBABILITY,
                "name": tags.get("name"),
                "sidewalk": tags.get("sidewalk"),
                "sidewalk_both": tags.get("sidewalk:both"),
            },
        })
    return {"type": "FeatureCollection", "features": features}


async def query_overpass(query: str, *, client: httpx.AsyncClient | None = None) -> dict:
    """POST the query, trying each Overpass server in turn: the public ones often answer 504/429."""
    headers = {"User-Agent": USER_AGENT}
    owned = client is None
    client = client or httpx.AsyncClient(timeout=200.0)
    error: Exception | None = None
    try:
        for url in OVERPASS_URLS:
            try:
                response = await client.post(url, data={"data": query}, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as exc:
                error = exc
        raise error
    finally:
        if owned:
            await client.aclose()


def load_cache(path: Path = CACHE_PATH) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(collection: dict, path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(collection, separators=(",", ":")), encoding="utf-8")


def cache_is_fresh(path: Path = CACHE_PATH, now: datetime | None = None) -> bool:
    if not path.exists():
        return False
    moment = utc(now or datetime.now(timezone.utc))
    written = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (moment - written).total_seconds() < REFRESH_SECONDS


async def register_ways(db, features: list[dict], now: datetime) -> int:
    """One bulk upsert for the whole batch. ``$setOnInsert`` preserves existing evidence."""
    value = log_odds(NO_SIDEWALK_PROBABILITY)
    moment = utc(now)
    operations = [
        UpdateOne(
            {"_id": f"belief:{feature['properties']['hazard_id']}"},
            {"$setOnInsert": {
                "type": "hazard_belief",
                "hazard_id": feature["properties"]["hazard_id"],
                "hazard_type": "no_sidewalk",
                "geometry": feature["geometry"],
                "severity": feature["properties"].get("severity", 1),
                "prior_log_odds": value,
                "log_odds": value,
                "evidence": {},
                "created_at": moment,
                "last_updated": moment,
            }},
            upsert=True,
        )
        for feature in features
    ]
    if not operations:
        return 0
    result = await db.intel_cache.bulk_write(operations, ordered=False)
    return result.upserted_count


async def fetch(*, db=None, now: datetime | None = None, force: bool = False,
                path: Path = CACHE_PATH) -> dict:
    """Return the no-sidewalk FeatureCollection, querying Overpass at most once a day."""
    moment = utc(now or datetime.now(timezone.utc))
    if not force and cache_is_fresh(path, moment):
        collection = load_cache(path)
    else:
        collection = parse_response(await query_overpass(build_query()))
        save_cache(collection, path)
    if db is not None:
        await register_ways(db, collection["features"], moment)
    return collection


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def coverage_counts(collection: dict, centers: tuple = (MMC, BBC),
                    radius_m: float = COVERAGE_RADIUS_M) -> dict:
    """Count ways whose nearest vertex is within ``radius_m`` of each campus."""
    counts = {}
    for center in centers:
        counts[center["name"]] = sum(
            1 for feature in collection.get("features", [])
            if min(
                (haversine_m(center["lat"], center["lon"], lat, lon)
                 for lon, lat in feature["geometry"]["coordinates"]),
                default=math.inf,
            ) <= radius_m
        )
    return counts


async def main() -> None:
    from app.db.mongo import close_client, get_db

    collection = await fetch(db=get_db())
    counts = coverage_counts(collection)
    print(f"Fetched {len(collection['features'])} no-sidewalk ways")
    print(f"Near MMC: {counts['MMC']}, near BBC: {counts['BBC']}")
    close_client()


if __name__ == "__main__":
    asyncio.run(main())
