"""Ingestion: live traffic incidents/closures from HERE Traffic API v7 (replaces FL511, which has no public API).

Incidents become `closure`, `construction` or `incident` beliefs with a `probability` prior by
criticality, under the stable id `here:<incident id>`. Incidents that drop out of the feed are
re-registered with a low prior so an old closure doesn't keep steering routes.
"""
from datetime import datetime

import httpx

from app.config import get_settings
from app.routing.beliefs import register_hazard, utc

INCIDENTS_URL = "https://data.traffic.hereapi.com/v7/incidents"
MIAMI_BBOX = "bbox:-80.45,25.55,-80.10,25.98"  # west,south,east,north
ID_PREFIX = "here:"

# HERE is an authoritative live feed, so even minor items start above the 0.73 routing threshold.
CRITICALITY_PROBABILITY = {"critical": 0.9, "major": 0.85, "minor": 0.75, "lowImpact": 0.6}
CRITICALITY_SEVERITY = {"critical": 4, "major": 4, "minor": 2, "lowImpact": 1}
CLEARED_PROBABILITY = 0.05
# HERE types → legend categories. "congestion" incidents are skipped: the flow feed covers them.
TYPE_KIND = {"roadClosure": "closure", "laneRestriction": "construction", "construction": "construction"}
SKIP_TYPES = {"congestion"}


async def fetch(client: httpx.AsyncClient | None = None) -> dict:
    """Raw HERE response; results[].location.shape.links[].points hold the road geometry."""
    params = {"in": MIAMI_BBOX, "locationReferencing": "shape", "apiKey": get_settings().here_api_key}
    owned = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        r = await client.get(INCIDENTS_URL, params=params)
        r.raise_for_status()
        return r.json()
    finally:
        if owned:
            await client.aclose()


def links_geometry(links: list[dict]) -> dict | None:
    """HERE shape links ({lat, lng} points) → one LineString, or a MultiLineString when they don't join."""
    lines = []
    for link in links:
        points = [[p["lng"], p["lat"]] for p in link.get("points", [])]
        if len(points) < 2:
            continue
        if lines and lines[-1][-1] == points[0]:
            lines[-1].extend(points[1:])
        else:
            lines.append(points)
    if not lines:
        return None
    if len(lines) == 1:
        return {"type": "LineString", "coordinates": lines[0]}
    return {"type": "MultiLineString", "coordinates": lines}


def _text(details: dict, key: str) -> str:
    return (details.get(key) or {}).get("value", "")


def kind_for(details: dict) -> str | None:
    if details.get("type") in SKIP_TYPES:
        return None
    if details.get("roadClosed"):
        return "closure"
    return TYPE_KIND.get(details.get("type"), "incident")


def to_geojson(raw: dict) -> dict:
    """One feature per incident: type, criticality, description, start and end time."""
    features = []
    for result in raw.get("results", []):
        details = result.get("incidentDetails", {})
        geometry = links_geometry(result.get("location", {}).get("shape", {}).get("links", []))
        if geometry is None or not details.get("id"):
            continue
        features.append({"type": "Feature", "geometry": geometry, "properties": {
            "id": details["id"],
            "type": details.get("type"),
            "kind": kind_for(details),
            "criticality": details.get("criticality", "minor"),
            "road_closed": bool(details.get("roadClosed")),
            "description": _text(details, "description"),
            "summary": _text(details, "summary") or _text(details, "typeDescription"),
            "start_time": details.get("startTime"),
            "end_time": details.get("endTime"),
        }})
    return {"type": "FeatureCollection", "features": features}


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def is_current(props: dict, now: datetime) -> bool:
    start, end = _parse_time(props.get("start_time")), _parse_time(props.get("end_time"))
    return (start is None or start <= utc(now)) and (end is None or utc(now) <= end)


# Card titles by category. HERE's own summary is often a bare word ("Closed"), so it only fills in
# for the generic `incident` kind; the location text goes in `place`.
KIND_TITLES = {"closure": "Road closed", "construction": "Roadwork"}


def place_from(description: str) -> str | None:
    """HERE descriptions read "Between A and B - Road construction": keep the location part."""
    place = (description or "").rsplit(" - ", 1)[0].strip()
    return place or None


def hazard_properties(props: dict) -> dict:
    criticality = props["criticality"]
    severity = CRITICALITY_SEVERITY.get(criticality, 2)
    if props["kind"] == "closure" and props["road_closed"]:
        severity = 5
    return {"probability": CRITICALITY_PROBABILITY.get(criticality, 0.75), "severity": severity,
            "title": KIND_TITLES.get(props["kind"]) or props["summary"] or "Incident",
            "place": place_from(props["description"]), "description": props["description"], "source": "here",
            "start_time": props["start_time"], "end_time": props["end_time"]}


async def clear_missing(db, prefix: str, seen: set[str], now: datetime) -> int:
    """Drop the prior of every belief under `prefix` that the latest feed no longer contains."""
    docs = await db.intel_cache.find({"type": "hazard_belief", "hazard_id": {"$regex": f"^{prefix}"}}).to_list(
        length=None)
    cleared = 0
    for doc in docs:
        if doc["hazard_id"] in seen or doc["prior_log_odds"] <= -2.9:  # already cleared (log-odds of 0.05)
            continue
        await register_hazard(db, doc["hazard_id"], doc["hazard_type"], doc["geometry"],
                              {"probability": CLEARED_PROBABILITY, "severity": doc.get("severity", 1)}, now)
        cleared += 1
    return cleared


async def run(db, now: datetime, client: httpx.AsyncClient | None = None) -> dict:
    collection = to_geojson(await fetch(client))
    seen = set()
    for feature in collection["features"]:
        props = feature["properties"]
        if props["kind"] is None or not is_current(props, now):
            continue
        hazard_id = f"{ID_PREFIX}{props['id']}"
        await register_hazard(db, hazard_id, props["kind"], feature["geometry"], hazard_properties(props), now)
        seen.add(hazard_id)
    cleared = await clear_missing(db, ID_PREFIX, seen, now)
    return {"registered": len(seen), "cleared": cleared}
