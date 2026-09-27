"""GET /layers: one colour-coded FeatureCollection per legend category, read from the belief store.

Read-only: probabilities for time `t` are computed from each belief's evidence without writing
decay back (refresh_belief persists decay only for "now"). Shape: frontend/public/mocks/layers.json.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from shapely.geometry import box, shape

from app.db.mongo import get_db
from app.routing.beliefs import contribution, probability, utc

log = logging.getLogger(__name__)
router = APIRouter(prefix="/layers", tags=["layers"])

CATEGORIES = ("flood", "weather", "construction", "closure", "congestion", "no_sidewalk", "pothole",
              "incident", "event")
# NOAA/NWS NEXRAD base-reflectivity composite as an XYZ tile template the map overlays.
# The Iowa Environmental Mesonet serves it; attribution is required and no API key is needed.
RADAR_OVERLAY = {
    "type": "xyz",
    "url_template": "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png",
    "attribution": "NOAA/NWS NEXRAD composite via Iowa Environmental Mesonet",
    "min_zoom": 0,
    "max_zoom": 12,
    "tile_size": 256,
    "opacity": 0.6,
}
# Stable id prefix → source key used in `sources[].kind` and `freshness` (longest prefix wins).
SOURCE_PREFIXES = {
    "incident:news-": "news", "flood:": "tides", "here-flow:": "here", "here:": "here", "nws:": "nws",
    "city:": "city_gis", "osm:": "osm", "gfm:": "gfm", "s1:": "gfm", "s2:": "s2", "311:": "311",
    "pothole:": "311", "event:": "ticketmaster",
}
SOURCE_LABELS = {
    "tides": "NOAA tide prediction + FEMA flood zone", "here": "HERE live traffic", "nws": "NWS Miami alert",
    "city_gis": "City of Miami Public Works", "osm": "OpenStreetMap", "gfm": "Copernicus GFM (Sentinel-1)",
    "s2": "Sentinel-2", "311": "Miami-Dade 311", "news": "Local news", "ticketmaster": "Ticketmaster",
}
# Modelled rather than measured: with no evidence on top, these hazards are "predicted".
PREDICTIVE_SOURCES = {"tides", "311"}
EVIDENCE_LABELS = {"crowd": "User report", "cleared": "Reported cleared"}
TITLES = {"flood": "Flooded street", "weather": "Weather alert", "construction": "Construction",
          "closure": "Road closed", "congestion": "Heavy traffic", "no_sidewalk": "No sidewalk",
          "pothole": "Potholes", "incident": "Incident", "event": "Event"}
# AGENTS.md › News → Gemini: news-only hazards leave the map after these windows.
NEWS_WINDOWS = {"incident": timedelta(hours=3), "flood": timedelta(hours=12), "closure": timedelta(hours=24),
                "construction": timedelta(days=30)}
# Cleared / ended hazards drop to p ≈ 0.05; keep them off the map.
MIN_PROBABILITY = 0.1


def source_kind(hazard_id: str) -> str:
    for prefix in sorted(SOURCE_PREFIXES, key=len, reverse=True):
        if hazard_id.startswith(prefix):
            return SOURCE_PREFIXES[prefix]
    return hazard_id.split(":", 1)[0]


def log_odds_at(doc: dict, t: datetime) -> float:
    """The belief's log-odds at `t`: decaying evidence re-evaluated, nothing persisted."""
    value = doc["log_odds"]
    for evidence in doc.get("evidence", {}).values():
        value += contribution(evidence["source"], evidence["observed_at"], t) - evidence["applied"]
    return value


def parse_bbox(bbox: str | None):
    if not bbox:
        return None
    try:
        west, south, east, north = (float(v) for v in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(422, "bbox must be west,south,east,north") from exc
    if west >= east or south >= north:
        raise HTTPException(422, "bbox must be west,south,east,north")
    return box(west, south, east, north)


def _iso(value: datetime | None) -> str | None:
    return utc(value).isoformat() if isinstance(value, datetime) else value


def _parse(value) -> datetime | None:
    if isinstance(value, datetime):
        return utc(value)
    if isinstance(value, str) and value:
        return utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    return None


def feature_for(doc: dict, evidence_docs: list[dict], t: datetime) -> dict | None:
    kind = doc["hazard_type"]
    props = doc.get("properties") or {}
    hazard_id = doc["hazard_id"]
    source = source_kind(hazard_id)
    last_updated = doc.get("last_updated")
    news_only = source == "news"
    if news_only and kind in NEWS_WINDOWS and last_updated and utc(t) - utc(last_updated) > NEWS_WINDOWS[kind]:
        return None
    p = probability(log_odds_at(doc, t))
    if p < MIN_PROBABILITY:
        return None
    evidence = doc.get("evidence", {})
    sources = [] if news_only else [{"kind": source, "label": props.get("source_label") or SOURCE_LABELS.get(source, source),
                                     "url": props.get("source_url"), "observed_at": _iso(doc.get("created_at"))}]
    for item in evidence_docs:
        sources.append({"kind": item.get("type") if item.get("type") != "satellite_check" else "satellite",
                        "label": item.get("title") or item.get("summary") or "",
                        "url": item.get("source_url"), "observed_at": _iso(item.get("created_at"))})
    # Crowd reports have no evidence document; news and satellite checks are listed above.
    for entry in evidence.values():
        if entry["source"] in ("crowd", "cleared"):
            sources.append({"kind": entry["source"], "label": EVIDENCE_LABELS[entry["source"]], "url": None,
                            "observed_at": _iso(entry.get("observed_at"))})
    expiries = [e for e in (_parse(props.get("end_time")), *(_parse(i.get("expires_at")) for i in evidence_docs)) if e]
    level = props.get("level")
    title = props.get("title") or (f"{level.capitalize()} traffic" if kind == "congestion" and level else None)
    if not title:
        title = "Flooding expected" if kind == "flood" and source == "tides" and not evidence else TITLES.get(kind, kind)
    predicted = source in PREDICTIVE_SOURCES and not evidence
    properties = {
        "hazard_id": hazard_id, "hazard_type": kind, "title": title,
        "place": props.get("place") or props.get("description"),
        "probability": round(p, 2), "status": "predicted" if predicted else "observed",
        "severity": doc.get("severity", 1), "sources": sources, "last_updated": _iso(last_updated),
        "expires_at": _iso(max(expiries)) if expiries else None,
    }
    if kind == "congestion":
        properties["level"] = level
    return {"type": "Feature", "geometry": doc["geometry"], "properties": properties}


async def build_layers(db, t: datetime, area=None) -> dict:
    beliefs = await db.intel_cache.find({"type": "hazard_belief"}).to_list(length=None)
    evidence_docs = await db.intel_cache.find({"_id": {"$regex": "^evidence:"}}).to_list(length=None)
    by_hazard: dict[str, list[dict]] = {}
    for item in evidence_docs:
        if item.get("hazard_id"):
            by_hazard.setdefault(item["hazard_id"], []).append(item)
    layers = {key: {"type": "FeatureCollection", "features": []} for key in CATEGORIES}
    freshness: dict[str, datetime] = {}
    for doc in beliefs:
        source = source_kind(doc["hazard_id"])
        if doc.get("last_updated"):
            freshness[source] = max(freshness.get(source, utc(doc["last_updated"])), utc(doc["last_updated"]))
        if doc.get("hazard_type") not in layers:
            continue
        try:
            geometry = shape(doc["geometry"])
        except Exception:  # noqa: BLE001 - one malformed belief must not break the map
            log.warning("Skipping belief with malformed geometry: %s", doc["hazard_id"])
            continue
        if area is not None and not geometry.intersects(area):
            continue
        feature = feature_for(doc, by_hazard.get(doc["hazard_id"], []), t)
        if feature:
            layers[doc["hazard_type"]]["features"].append(feature)
    for item in evidence_docs:
        created = _parse(item.get("created_at"))
        kind = "news" if item.get("type") == "news" else item.get("type")
        if created and kind:
            freshness[kind] = max(freshness.get(kind, created), created)
    return {"t": t.isoformat(), "freshness": {k: v.isoformat() for k, v in sorted(freshness.items())},
            "radar": RADAR_OVERLAY, **layers}


@router.get("")
async def get_layers(t: Annotated[datetime | None, Query(description="Departure time; defaults to now")] = None,
                     bbox: Annotated[str | None, Query(description="west,south,east,north")] = None):
    when = utc(t) if t and t.tzinfo else (t.replace(tzinfo=timezone.utc) if t else datetime.now(timezone.utc))
    return await build_layers(get_db(), when, parse_bbox(bbox))
