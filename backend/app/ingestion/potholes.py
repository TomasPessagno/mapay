"""Ingestion: chronic pothole corridors from Miami-Dade 311 (2023) -> `pothole` beliefs.

The 2023 311 extract is a non-spatial ArcGIS table (`latitude` / `longitude` columns),
so complaints are queried with a lat/lon `where` clause rather than a spatial filter.
This is historical data: a handful of complaints is noise, so only streets where at
least ``MIN_COMPLAINTS`` tickets cluster together are registered, as "chronic corridors".
The map shows them as predicted, not live (AGENTS.md › Data sources › Potholes).

A corridor is one street name (house number stripped from ``street_address``), split
into segments wherever consecutive complaints are more than ``SEGMENT_GAP_M`` apart.
The street's complaint density (``complaints_per_km``) feeds the pothole prior in
``belief_config.py``; ids stay stable as ``pothole:311-corridor-<street>[-<n>]``.

``python -m app.ingestion.potholes`` refreshes the beliefs against the live table.
"""
import asyncio
import itertools
import math
import re
from datetime import datetime

import httpx

from app.routing.beliefs import register_hazard, utc

POTHOLES_QUERY_URL = (
    "https://services.arcgis.com/8Pc9XBTAsYuxx9Ny/arcgis/rest/services/"
    "data_311_2023/FeatureServer/0/query"
)
ID_PREFIX = "pothole:311-corridor-"
SOURCE_LABEL = "Miami-Dade 311 (2023)"
TITLE = "Chronic potholes"
# Same core Miami bounding box as HERE / OSM / City GIS: west, south, east, north.
MIAMI_BBOX = (-80.45, 25.55, -80.10, 25.98)
PAGE_SIZE = 1000
MAX_PAGES = 25
# 2023 data: fewer than this many complaints on a segment is not a chronic corridor.
MIN_COMPLAINTS = 3
# Complaints further apart than this belong to a different segment of the same street.
SEGMENT_GAP_M = 500.0
# Density floor so a tight cluster is not divided by (almost) zero.
MIN_CORRIDOR_KM = 0.25
EARTH_RADIUS_M = 6371000.0
# (minimum complaints/km, severity), highest first. Potholes are a minor hazard, so 3 caps it.
SEVERITY_BY_DENSITY = ((15.0, 3), (5.0, 2))
DEFAULT_SEVERITY = 1


def build_query(offset: int = 0, page_size: int = PAGE_SIZE,
                bbox: tuple[float, float, float, float] = MIAMI_BBOX) -> dict:
    """One ArcGIS table query page: potholes inside the bbox, oldest object ids first."""
    west, south, east, north = bbox
    return {
        "where": ("UPPER(issue_type) = 'POTHOLE' "
                  f"AND latitude >= {south} AND latitude <= {north} "
                  f"AND longitude >= {west} AND longitude <= {east}"),
        "outFields": "ticket_id,issue_type,street_address,city,latitude,longitude",
        "returnGeometry": "false",
        "orderByFields": "ObjectId",
        "resultOffset": offset,
        "resultRecordCount": page_size,
        "f": "json",
    }


def normalise_street(address) -> str | None:
    """Drop the house number and normalise casing/whitespace: '13296 SW 8TH ST' -> 'SW 8TH ST'."""
    text = re.sub(r"^\s*\d+[a-z]?\s+", "", str(address or "").strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text or None


def display_street(street: str) -> str:
    """'SW 328TH ST' -> 'SW 328th St', for the map's place label."""
    parts = []
    for word in street.split():
        match = re.fullmatch(r"(\d+)(ST|ND|RD|TH)", word)
        if word in {"NW", "NE", "SW", "SE"}:
            parts.append(word)
        elif match:
            parts.append(f"{match.group(1)}{match.group(2).lower()}")
        else:
            parts.append(word.capitalize())
    return " ".join(parts)


def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def parse_records(payload: dict) -> list[dict]:
    """Pothole tickets with a usable street and coordinates; anything else is dropped."""
    records = []
    for feature in payload.get("features", []):
        attrs = feature.get("attributes") or feature.get("properties") or {}
        if "POTHOLE" not in str(attrs.get("issue_type") or "").upper():
            continue
        street = normalise_street(attrs.get("street_address"))
        if street is None:
            continue
        try:
            lat, lng = float(attrs["latitude"]), float(attrs["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        west, south, east, north = MIAMI_BBOX
        if not (south <= lat <= north and west <= lng <= east):
            continue
        records.append({"ticket_id": attrs.get("ticket_id"), "street": street,
                        "lat": lat, "lng": lng})
    return records


def distance_m(a: dict, b: dict) -> float:
    """Local equirectangular approximation, plenty for a 500 m split."""
    mean_lat = math.radians((a["lat"] + b["lat"]) / 2)
    dy = math.radians(b["lat"] - a["lat"]) * EARTH_RADIUS_M
    dx = math.radians(b["lng"] - a["lng"]) * EARTH_RADIUS_M * math.cos(mean_lat)
    return math.hypot(dx, dy)


def segment_length_m(points: list[dict]) -> float:
    return sum(distance_m(a, b) for a, b in itertools.pairwise(points))


def severity_for(density: float) -> int:
    for bound, severity in SEVERITY_BY_DENSITY:
        if density >= bound:
            return severity
    return DEFAULT_SEVERITY


def _order(points: list[dict]) -> list[dict]:
    """Sort along the street's dominant axis so splits follow the road, not ticket order."""
    lats = [p["lat"] for p in points]
    lngs = [p["lng"] for p in points]
    lat_span = max(lats) - min(lats)
    lng_span = (max(lngs) - min(lngs)) * math.cos(math.radians(sum(lats) / len(lats)))
    if lng_span >= lat_span:
        return sorted(points, key=lambda p: (p["lng"], p["lat"]))
    return sorted(points, key=lambda p: (p["lat"], p["lng"]))


def _split(points: list[dict], gap_m: float = SEGMENT_GAP_M) -> list[list[dict]]:
    segments: list[list[dict]] = []
    current: list[dict] = []
    for point in points:
        if current and distance_m(current[-1], point) > gap_m:
            segments.append(current)
            current = []
        current.append(point)
    if current:
        segments.append(current)
    return segments


def _geometry(points: list[dict]) -> dict:
    if len(points) == 1:
        return {"type": "Point", "coordinates": [points[0]["lng"], points[0]["lat"]]}
    return {"type": "LineString",
            "coordinates": [[p["lng"], p["lat"]] for p in points]}


def aggregate(records: list[dict], min_complaints: int = MIN_COMPLAINTS) -> list[dict]:
    """Street complaint clusters -> chronic corridor hazards with stable ids."""
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(record["street"], []).append(record)

    corridors = []
    for street, group in sorted(groups.items()):
        segments = _split(_order(group))
        suffix = len(segments) > 1
        for index, segment in enumerate(segments, start=1):
            if len(segment) < min_complaints:
                continue
            length_km = max(segment_length_m(segment) / 1000, MIN_CORRIDOR_KM)
            density = round(len(segment) / length_km, 1)
            hazard_id = f"{ID_PREFIX}{slugify(street)}" + (f"-{index}" if suffix else "")
            corridors.append({
                "hazard_id": hazard_id,
                "street": street,
                "place": display_street(street),
                "count": len(segment),
                "length_km": round(length_km, 3),
                "complaints_per_km": density,
                "severity": severity_for(density),
                "geometry": _geometry(segment),
            })
    return corridors


async def fetch(client: httpx.AsyncClient | None = None, page_size: int = PAGE_SIZE,
                max_pages: int = MAX_PAGES) -> dict:
    """All pothole tickets in the bbox, paged by object id, as one ArcGIS-shaped payload."""
    owned = client is None
    client = client or httpx.AsyncClient(timeout=60)
    features: list[dict] = []
    try:
        for page in range(max_pages):
            response = await client.get(POTHOLES_QUERY_URL, params=build_query(page * page_size, page_size))
            response.raise_for_status()
            batch = response.json().get("features") or []
            features.extend(batch)
            if len(batch) < page_size:
                break
    finally:
        if owned:
            await client.aclose()
    return {"features": features}


async def register_corridors(db, corridors: list[dict], now: datetime) -> int:
    """Register each corridor's prior, then attach the presentation fields /layers reads."""
    moment = utc(now)
    for corridor in corridors:
        await register_hazard(db, corridor["hazard_id"], "pothole", corridor["geometry"],
                              {"complaints_per_km": corridor["complaints_per_km"],
                               "severity": corridor["severity"]}, moment)
        await db.intel_cache.update_one(
            {"_id": f"belief:{corridor['hazard_id']}"},
            {"$set": {"properties": {
                "title": TITLE,
                "place": corridor["place"],
                "source_label": f"{SOURCE_LABEL}: {corridor['complaints_per_km']} complaints/km",
            }}})
    return len(corridors)


async def run(db, now: datetime, client: httpx.AsyncClient | None = None, payload: dict | None = None) -> dict:
    """Aggregate pothole tickets into chronic corridors and register them. Returns counts."""
    raw = payload if payload is not None else await fetch(client)
    records = parse_records(raw)
    corridors = aggregate(records)
    registered = await register_corridors(db, corridors, now)
    return {"complaints": len(records), "corridors": registered}


async def main() -> None:
    from app.db.mongo import close_client, get_db

    result = await run(get_db(), datetime.now().astimezone())
    print(f"Parsed {result['complaints']} pothole complaints -> {result['corridors']} corridors")
    close_client()


if __name__ == "__main__":
    asyncio.run(main())
