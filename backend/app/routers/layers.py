"""GET /layers: one colour-coded FeatureCollection per legend category, read from the belief store.

Read-only: probabilities for time `t` are computed from each belief's evidence without writing
decay back (refresh_belief persists decay only for "now"). Shape: frontend/public/mocks/layers.json.

Serving is snapshot-first (A26): `collect_features` runs `feature_for` over every belief once and
keeps the result with bounds precomputed per feature. A request whose `t` is within
SNAPSHOT_FRESH_SECONDS of now filters that in-process snapshot (a plain bounds check, no Mongo
round-trip, no per-request Shapely parsing); once the snapshot is older than SNAPSHOT_TTL_SECONDS
it is rebuilt in the background while the stale copy keeps serving (stale-while-revalidate), and
`/internal/ingest/*` marks it stale and rebuilds it in the background when a job finishes. Only a
request that finds no snapshot at all waits for a build. `t` further away keeps the exact slow
path, since only time-dependent predictions (crowd decay, news windows) care about it.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from shapely.geometry import box, mapping, shape

from app.db.mongo import get_db
from app.routing.beliefs import belief_at, probability, utc
from app.routing.pre_route import belief_docs

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
    "incident:news-": "news", "news:": "news", "flood:": "tides", "here-flow:": "here",
    "here:": "here", "nws:": "nws", "city:": "city_gis", "osm:": "osm", "gfm:": "gfm", "s1:": "gfm",
    "s2:": "s2", "311:": "311", "pothole:": "311", "event:": "ticketmaster",
    "typical:": "google_typical",
}
SOURCE_LABELS = {
    "tides": "NOAA tide prediction + FEMA flood zone", "here": "HERE live traffic", "nws": "NWS Miami alert",
    "city_gis": "City of Miami Public Works", "osm": "OpenStreetMap", "gfm": "Copernicus GFM (Sentinel-1)",
    "s2": "Sentinel-2", "311": "Miami-Dade 311", "news": "Local news", "ticketmaster": "Ticketmaster",
    "google_typical": "Google typical traffic",
}
# Modelled rather than measured: with no evidence on top, these hazards are "predicted".
PREDICTIVE_SOURCES = {"tides", "311", "google_typical"}
EVIDENCE_LABELS = {"crowd": "User report", "cleared": "Reported cleared"}
TITLES = {"flood": "Flooded street", "weather": "Weather alert", "construction": "Construction",
          "closure": "Road closed", "congestion": "Heavy traffic", "no_sidewalk": "No sidewalk",
          "pothole": "Potholes", "incident": "Incident", "event": "Event"}
# AGENTS.md › News → Gemini: news-only hazards leave the map after these windows.
NEWS_WINDOWS = {"incident": timedelta(hours=3), "flood": timedelta(hours=12), "closure": timedelta(hours=24),
                "construction": timedelta(days=30)}
# Cleared / ended hazards drop to p ≈ 0.05; keep them off the map.
MIN_PROBABILITY = 0.1

# Snapshot tuning (A26): rebuild when older than 5 min, but serve `t` within 15 min of now from it.
SNAPSHOT_TTL_SECONDS = 300
SNAPSHOT_FRESH_SECONDS = 15 * 60


def source_kind(hazard_id: str) -> str:
    for prefix in sorted(SOURCE_PREFIXES, key=len, reverse=True):
        if hazard_id.startswith(prefix):
            return SOURCE_PREFIXES[prefix]
    return hazard_id.split(":", 1)[0]


SIMPLIFY_DEG = 0.00003  # ~3 m: invisible on the map, halves long street geometries
COORD_DECIMALS = 5  # ~1 m


def slim_geometry(geometry: dict) -> dict:
    """Simplified, rounded geometry for the map (the stored belief keeps the full one)."""
    try:
        simplified = mapping(shape(geometry).simplify(SIMPLIFY_DEG, preserve_topology=True))
    except Exception:  # noqa: BLE001 - odd geometries are sent as they are
        return geometry

    def rounded(coords):
        if coords and isinstance(coords[0], (int, float)):
            return [round(coords[0], COORD_DECIMALS), round(coords[1], COORD_DECIMALS)]
        return [rounded(c) for c in coords]

    if "coordinates" not in simplified:
        return geometry
    return {"type": simplified["type"], "coordinates": rounded(simplified["coordinates"])}


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


RUN_FIELDS = ("items_seen", "items_new", "hazards_added", "hazards_updated")


def run_summary(doc: dict) -> dict:
    """JSON-ready `ingest_runs` doc: one job's last successful run (A28)."""
    job = doc.get("job") or str(doc.get("_id", "")).removeprefix("run:")
    return {"job": job, "last_run_at": _iso(doc.get("last_run_at")),
            **{field: doc[field] for field in RUN_FIELDS if isinstance(doc.get(field), int)}}


async def latest_runs(db) -> dict[str, dict]:
    """{job: run_summary} from `ingest_runs`, read separately from the last hazard change:
    a job that runs on schedule without adding hazards still shows a fresh `last_run_at`."""
    collection = getattr(db, "ingest_runs", None)
    if collection is None:
        return {}
    docs = await collection.find({"job": {"$exists": True}}).to_list(length=None)
    return {doc["job"]: run_summary(doc) for doc in docs if doc.get("job")}


def feature_for(doc: dict, evidence_docs: list[dict], t: datetime) -> dict | None:
    kind = doc["hazard_type"]
    props = doc.get("properties") or {}
    hazard_id = doc["hazard_id"]
    source = source_kind(hazard_id)
    last_updated = doc.get("last_updated")
    news_only = source == "news"
    if news_only and kind in NEWS_WINDOWS and last_updated and utc(t) - utc(last_updated) > NEWS_WINDOWS[kind]:
        return None
    p = probability(belief_at(doc, t)["log_odds"])
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
    return {"type": "Feature", "geometry": slim_geometry(doc["geometry"]), "properties": properties}


Bounds = tuple[float, float, float, float]
Feature = tuple[dict, Bounds]


def geometry_bounds(geometry: dict) -> Bounds:
    """(west, south, east, north) walked straight from the GeoJSON coordinates (no Shapely)."""
    coords = geometry.get("coordinates")
    if coords is None:  # GeometryCollection and friends: let Shapely handle it (build time only)
        return shape(geometry).bounds

    def walk(part):
        if part and isinstance(part[0], (int, float)):
            return part[0], part[1], part[0], part[1]
        boxes = [walk(c) for c in part]
        if not boxes:  # empty geometry: bounds that never intersect a bbox
            return 180.0, 90.0, -180.0, -90.0
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    return walk(coords)


def _intersects(bounds: Bounds, area: Bounds) -> bool:
    west, south, east, north = area
    minx, miny, maxx, maxy = bounds
    return minx <= east and maxx >= west and miny <= north and maxy >= south


async def collect_features(db, t: datetime) -> tuple[dict[str, list[Feature]], dict[str, object]]:
    """Every belief at `t` as a map feature with its bounds, plus per-source freshness
    (`<source>` = last hazard change, `<job>_run` = last successful ingest run).

    This is the expensive step (one Mongo read of beliefs + evidence, Shapely per geometry);
    the snapshot calls it once and reuses the result instead of running it per request.
    """
    beliefs = await belief_docs(db)
    evidence_docs = await db.intel_cache.find({"_id": {"$regex": "^evidence:"}}).to_list(length=None)
    by_hazard: dict[str, list[dict]] = {}
    for item in evidence_docs:
        if item.get("hazard_id"):
            by_hazard.setdefault(item["hazard_id"], []).append(item)
    features: dict[str, list[Feature]] = {key: [] for key in CATEGORIES}
    freshness: dict[str, datetime] = {}
    for doc in beliefs:
        source = source_kind(doc["hazard_id"])
        if doc.get("last_updated"):
            freshness[source] = max(freshness.get(source, utc(doc["last_updated"])), utc(doc["last_updated"]))
        if doc.get("hazard_type") not in features:
            continue
        try:
            shape(doc["geometry"])
        except Exception:  # noqa: BLE001 - one malformed belief must not break the map
            log.warning("Skipping belief with malformed geometry: %s", doc["hazard_id"])
            continue
        feature = feature_for(doc, by_hazard.get(doc["hazard_id"], []), t)
        if feature:
            features[doc["hazard_type"]].append((feature, geometry_bounds(feature["geometry"])))
    for item in evidence_docs:
        created = _parse(item.get("created_at"))
        kind = "news" if item.get("type") == "news" else item.get("type")
        if created and kind:
            freshness[kind] = max(freshness.get(kind, created), created)
    for job, run in (await latest_runs(db)).items():
        freshness[f"{job}_run"] = run
    return features, freshness


def _render(t: datetime, features: dict[str, list[Feature]], freshness: dict[str, object],
            area: Bounds | None = None) -> dict:
    layers = {key: {"type": "FeatureCollection",
                    "features": [feature for feature, bounds in entries
                                 if area is None or _intersects(bounds, area)]}
              for key, entries in features.items()}
    rendered = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in sorted(freshness.items())}
    return {"t": t.isoformat(), "freshness": rendered, "radar": RADAR_OVERLAY, **layers}


async def build_layers(db, t: datetime, area=None) -> dict:
    """Slow path: read and convert everything for this exact `t` (used when `t` is far from now)."""
    features, freshness = await collect_features(db, t)
    return _render(t, features, freshness, area.bounds if area is not None else None)


class Snapshot:
    """All map features at one build time, each with precomputed bounds; read-only once built."""

    __slots__ = ("built_at", "built_monotonic", "count", "features", "freshness")

    def __init__(self, built_at: datetime, features: dict[str, list[Feature]], freshness: dict[str, datetime]):
        self.built_at = built_at
        self.built_monotonic = time.monotonic()
        self.features = features
        self.freshness = freshness
        self.count = sum(len(entries) for entries in features.values())

    def mark_stale(self) -> None:
        """Force the age past SNAPSHOT_TTL_SECONDS: requests serve it once more and rebuild."""
        self.built_monotonic = time.monotonic() - SNAPSHOT_TTL_SECONDS - 1


LAYERS_CACHE_SECONDS = 60
_layers_cache: dict[tuple, tuple[float, bytes]] = {}

_snapshot: Snapshot | None = None
_rebuild_task: asyncio.Task | None = None
_generation = 0


def invalidate_snapshot(db=None) -> None:
    """Ingestion finished: mark the snapshot stale and rebuild it in the background.

    The old snapshot keeps serving requests while the rebuild runs (stale-while-revalidate);
    only a request that finds no snapshot at all waits for a build.
    """
    global _generation
    _generation += 1
    _layers_cache.clear()
    if _snapshot is None:
        return
    _snapshot.mark_stale()
    if db is not None:
        _kick_rebuild(db)


def clear_snapshot() -> None:
    """Drop the snapshot entirely (tests need each fake database to build its own)."""
    global _snapshot, _generation
    _snapshot = None
    _generation += 1
    _layers_cache.clear()


async def _rebuild(db, generation: int) -> None:
    global _snapshot
    started = time.monotonic()
    built_at = datetime.now(timezone.utc)
    try:
        features, freshness = await collect_features(db, built_at)
    except Exception:
        log.exception("Layers snapshot rebuild failed")
        return
    if generation != _generation:
        # Ingest invalidated this build mid-flight: drop it and start over on the newer data.
        log.info("Layers snapshot rebuild discarded (invalidated mid-build); retrying")
        _start_rebuild(db)
        return
    _snapshot = Snapshot(built_at, features, freshness)
    log.info("Layers snapshot rebuilt in %.0f ms: %d features", (time.monotonic() - started) * 1000, _snapshot.count)


def _start_rebuild(db) -> asyncio.Task | None:
    """Always start a fresh build task (or return None without a running event loop)."""
    global _rebuild_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no running loop; callers fall back to the slow path
        return None
    _rebuild_task = loop.create_task(_rebuild(db, _generation))
    return _rebuild_task


def _kick_rebuild(db) -> asyncio.Task | None:
    if _rebuild_task is not None and not _rebuild_task.done():
        return _rebuild_task
    return _start_rebuild(db)


async def get_snapshot(db) -> Snapshot | None:
    """The snapshot, rebuilding it in the background when stale. A request only waits when no
    snapshot has ever been built; otherwise it is served the current one immediately."""
    snapshot = _snapshot
    if snapshot is None:
        task = _kick_rebuild(db)
        if task is not None:
            await task
        return _snapshot
    if time.monotonic() - snapshot.built_monotonic >= SNAPSHOT_TTL_SECONDS:
        _kick_rebuild(db)
    return snapshot


def warm_snapshot() -> None:
    """Start the first build in the background; app startup doesn't wait for it (A26)."""
    _kick_rebuild(get_db())


def _response(payload: dict) -> Response:
    body = json.dumps(payload, separators=(",", ":"), default=str).encode()
    return Response(content=body, media_type="application/json",
                    headers={"Cache-Control": "public, max-age=60"})


@router.get("")
async def get_layers(t: Annotated[datetime | None, Query(description="Departure time; defaults to now")] = None,
                     bbox: Annotated[str | None, Query(description="west,south,east,north")] = None):
    when = utc(t) if t and t.tzinfo else (t.replace(tzinfo=timezone.utc) if t else datetime.now(timezone.utc))
    area = parse_bbox(bbox)
    area_bounds = area.bounds if area is not None else None
    # "Now" (and anything within 15 min) is time-independent enough to answer from the snapshot:
    # filter the prebuilt features by their bounds instead of reading all beliefs again.
    if abs((when - datetime.now(timezone.utc)).total_seconds()) <= SNAPSHOT_FRESH_SECONDS:
        snapshot = await get_snapshot(get_db())
        if snapshot is not None:
            return _response(_render(when, snapshot.features, snapshot.freshness, area_bounds))
    # Every other `t` (the time scrubber) keeps the exact slow path, cached by minute + bbox for 60 s.
    key = (when.replace(second=0, microsecond=0), bbox)
    cached = _layers_cache.get(key)
    if cached and time.monotonic() - cached[0] < LAYERS_CACHE_SECONDS:
        return Response(content=cached[1], media_type="application/json",
                        headers={"Cache-Control": "public, max-age=60"})
    body = json.dumps(await build_layers(get_db(), when, area), separators=(",", ":"), default=str).encode()
    now = time.monotonic()
    for stale in [k for k, (at, _) in _layers_cache.items() if now - at >= LAYERS_CACHE_SECONDS]:
        del _layers_cache[stale]
    _layers_cache[key] = (now, body)
    return Response(content=body, media_type="application/json",
                    headers={"Cache-Control": "public, max-age=60"})
