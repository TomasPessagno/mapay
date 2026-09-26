"""Ingestion: HERE Traffic API v7 flow → `congestion` beliefs.

Segments with a jam factor ≥ 4 (HERE's 0–10 scale, 10 = standstill) are registered with a
`level` of moderate / heavy / severe. Flow segments carry no id, so each gets a stable one from
its road name and end points. Segments that clear are re-registered with a low prior.
"""
import hashlib
from datetime import datetime

import httpx

from app.config import get_settings
from app.ingestion.here_incidents import MIAMI_BBOX, clear_missing, links_geometry
from app.routing.beliefs import register_hazard

FLOW_URL = "https://data.traffic.hereapi.com/v7/flow"
ID_PREFIX = "here-flow:"
MIN_JAM_FACTOR = 4.0
# (lower jam factor bound, level, severity), highest first.
LEVELS = [(8.0, "severe", 4), (6.0, "heavy", 3), (MIN_JAM_FACTOR, "moderate", 2)]
# Measured live speeds, not a forecast; any one sample can still be stale by a few minutes.
CONGESTION_PROBABILITY = 0.85


async def fetch(client: httpx.AsyncClient | None = None) -> dict:
    params = {"in": MIAMI_BBOX, "locationReferencing": "shape", "apiKey": get_settings().here_api_key}
    owned = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        r = await client.get(FLOW_URL, params=params)
        r.raise_for_status()
        return r.json()
    finally:
        if owned:
            await client.aclose()


def level_for(jam_factor: float) -> tuple[str, int] | None:
    for bound, level, severity in LEVELS:
        if jam_factor >= bound:
            return level, severity
    return None


def segment_id(description: str, geometry: dict) -> str:
    coords = geometry["coordinates"] if geometry["type"] == "LineString" else geometry["coordinates"][0]
    key = f"{description}|{coords[0][0]:.5f},{coords[0][1]:.5f}|{coords[-1][0]:.5f},{coords[-1][1]:.5f}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def congested_segments(raw: dict) -> list[dict]:
    features = []
    for result in raw.get("results", []):
        flow = result.get("currentFlow", {})
        jam = float(flow.get("jamFactor", 0))
        level = level_for(jam)
        location = result.get("location", {})
        geometry = links_geometry(location.get("shape", {}).get("links", []))
        if level is None or geometry is None:
            continue
        description = location.get("description", "")
        features.append({"type": "Feature", "geometry": geometry, "properties": {
            "id": segment_id(description, geometry), "description": description, "jam_factor": jam,
            "level": level[0], "severity": level[1], "speed_mps": flow.get("speed"),
            "free_flow_mps": flow.get("freeFlow"), "length_m": location.get("length")}})
    return features


async def run(db, now: datetime, client: httpx.AsyncClient | None = None) -> dict:
    seen = set()
    for feature in congested_segments(await fetch(client)):
        props = feature["properties"]
        hazard_id = f"{ID_PREFIX}{props['id']}"
        if hazard_id in seen:  # the feed can list the same segment twice
            continue
        await register_hazard(db, hazard_id, "congestion", feature["geometry"], {
            "probability": CONGESTION_PROBABILITY, "severity": props["severity"], "level": props["level"],
            "jam_factor": props["jam_factor"], "title": f"{props['level'].capitalize()} traffic",
            "description": props["description"], "source": "here"}, now)
        seen.add(hazard_id)
    cleared = await clear_missing(db, ID_PREFIX, seen, now)
    return {"registered": len(seen), "cleared": cleared}
