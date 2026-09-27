"""Satellite flood extents → hazard beliefs (#9), shared by GFM and the Earth Engine fallback.

A flood polygon that overlaps a registered flood hazard (a tide hotspot, a news flood) adds
`satellite` evidence to it, once per pass and polygon. A polygon anywhere else registers a new
`flood` hazard with a fixed prior; those are replaced pass by pass (a polygon absent from the
latest pass drops to a low prior). Every item carries the satellite pass time, because a pass
is hours to ~2 days old by the time it arrives (AGENTS.md › Satellite).
"""
import hashlib
import logging
from datetime import datetime, timedelta

from shapely.geometry import mapping, shape

from app.ingestion.here_incidents import clear_missing
from app.routing.belief_config import BELIEF_CONFIG as C
from app.routing.beliefs import add_evidence, contribution, register_hazard, utc

log = logging.getLogger(__name__)

MATCH_BUFFER_DEG = 0.0005  # ~50 m: a hotspot point next to a flooded block counts
MAX_POLYGONS = 300  # largest first; a big event shouldn't write thousands of beliefs
EVIDENCE_TTL = timedelta(days=3)
SOURCES = {
    "gfm": {"label": "Copernicus GFM (Sentinel-1)", "url": "https://global-flood.emergency.copernicus.eu/"},
    "s1": {"label": "Sentinel-1 via Earth Engine", "url": "https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S1_GRD"},
}


def polygon_key(polygon) -> str:
    """Stable id for a polygon within a pass (rounded geometry)."""
    rounded = shape(mapping(polygon)).simplify(0.0001)
    return hashlib.sha1(rounded.wkt.encode()).hexdigest()[:12]


async def apply_flood_polygons(db, polygons: list, pass_time: datetime, source: str, pass_id: str,
                               now: datetime) -> dict:
    meta = SOURCES[source]
    pass_time = utc(pass_time)
    polygons = sorted((p for p in polygons if not p.is_empty), key=lambda p: p.area, reverse=True)[:MAX_POLYGONS]
    floods = await db.intel_cache.find({"type": "hazard_belief", "hazard_type": "flood"}).to_list(length=None)
    known = []
    for doc in floods:
        if doc["hazard_id"].startswith(f"{source}:"):
            continue  # our own earlier polygons are replaced below, not confirmed
        try:
            known.append((doc["hazard_id"], shape(doc["geometry"]).buffer(MATCH_BUFFER_DEG)))
        except Exception:  # noqa: BLE001 - one malformed belief must not stop the pass
            log.warning("Skipping flood belief with bad geometry: %s", doc["hazard_id"])
    when = pass_time.strftime("%b %d, %H:%M UTC")
    matched, registered = set(), set()
    for polygon in polygons:
        key = polygon_key(polygon)
        hits = [hazard_id for hazard_id, area in known if area.intersects(polygon)]
        for hazard_id in hits:
            evidence_id = f"evidence:satellite:{source}:{pass_id}:{key}:{hazard_id}"
            await db.intel_cache.update_one({"_id": evidence_id}, {"$setOnInsert": {
                "_id": evidence_id, "type": "satellite_check", "source": source, "hazard_id": hazard_id,
                "title": f"{meta['label']}: water seen on the {when} pass", "summary": f"Flood extent, pass {when}",
                "source_url": meta["url"], "pass_time": pass_time, "created_at": pass_time,
                "expires_at": pass_time + EVIDENCE_TTL, "log_odds": contribution("satellite", pass_time, now),
                "geometry": mapping(polygon)}}, upsert=True)
            await add_evidence(db, hazard_id, evidence_id, "satellite", pass_time, now)
            matched.add(hazard_id)
        if not hits:
            hazard_id = f"{source}:{key}"
            await register_hazard(db, hazard_id, "flood", mapping(polygon), {
                "probability": C["satellite_flood_probability"], "severity": 3,
                "title": "Flooding seen by satellite", "description": f"{meta['label']}, pass {when}",
                "start_time": pass_time.isoformat(), "source_url": meta["url"], "source_label": meta["label"]},
                now)
            registered.add(hazard_id)
    cleared = await clear_missing(db, f"{source}:", registered, now)
    return {"pass_time": pass_time.isoformat(), "pass_id": pass_id, "polygons": len(polygons),
            "confirmed_hazards": len(matched), "new_hazards": len(registered), "cleared": cleared}
