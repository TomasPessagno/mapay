"""GET /layers: one colour-coded FeatureCollection per legend category, read from the belief store.

Read-only: probabilities for time `t` are computed from each belief's evidence without writing
decay back (refresh_belief persists decay only for "now"). Shape: frontend/public/mocks/layers.json.

Serving is snapshot-first (A27): `collect_features` runs `feature_for` over every belief once and
encodes each feature as compact JSON `bytes` with its bounds precomputed. A request whose `t` is
within SNAPSHOT_FRESH_SECONDS of now filters those bytes (a plain bounds check, no Mongo
round-trip, no per-request Shapely parsing).

No user request waits for a rebuild (A30). The app builds the snapshot at startup, before it
listens (`warm_snapshot`). Past SNAPSHOT_TTL_SECONDS, requests keep getting the current snapshot
while one background rebuild runs. `/internal/ingest/*` rebuilds after its job, holding its own
request open (Cloud Run gives CPU only while a request is in flight). Every rebuild does its CPU
work in a worker thread, so the server keeps answering meanwhile, and a failed rebuild keeps the
previous snapshot.

Change detection is a cheap marker, not a content fingerprint (A29): Atlas M0 got throttled by the
old full-collection `hazards_fingerprint`, which streamed every belief and evidence document on
every ingest run (~30k docs, ~19 MB) just to decide whether anything changed. The marker is four
index-covered queries (counts + newest timestamps), and a changed marker rebuilds at most once per
MIN_REBUILD_SECONDS so the weather/HERE jobs every 5 min can't cause a full read each time. The
snapshot and `belief_docs` (routes, pre-route check) share the one full read per rebuild.
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
from app.routing.pre_route import (
    belief_docs,
    read_belief_docs,
    seed_belief_cache,
    touch_belief_cache,
)

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

# Snapshot tuning (A26): serve `t` within 15 min of now from the snapshot. Ingest (weather and
# HERE every 5 min) verifies the content and restarts the age clock, so the TTL is only the
# fallback for an instance that receives no ingest calls at all (A27).
SNAPSHOT_TTL_SECONDS = 30 * 60
SNAPSHOT_FRESH_SECONDS = 15 * 60
# A29: the shortest gap between two full rebuilds. Weather/HERE re-register hazards every 5 min,
# bumping `last_updated`, so without this the marker would trigger a full read every 5 min.
MIN_REBUILD_SECONDS = 15 * 60


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


# Run metadata lives outside the snapshot on purpose (A28): the snapshot is only rebuilt when a
# hazard changes, so run freshness frozen inside it would hide a quiet job. The cache is loaded
# lazily by the first /layers request and refreshed by /internal/ingest after every run, so
# /layers never queries `ingest_runs` per request.
_runs_cache: dict[str, dict] | None = None


async def runs_freshness(db) -> dict[str, dict]:
    """{job: run_summary}, read once per process and merged into `freshness` at render time."""
    global _runs_cache
    if _runs_cache is None:
        _runs_cache = await latest_runs(db)
    return _runs_cache


async def refresh_runs(db) -> dict[str, dict]:
    """Called by /internal/ingest right after recording the run, rebuilt or not."""
    global _runs_cache
    _runs_cache = await latest_runs(db)
    return _runs_cache


def clear_runs() -> None:
    """Drop the run cache (tests need each fake database to load its own)."""
    global _runs_cache
    _runs_cache = None


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
Feature = tuple[bytes, Bounds]  # compact JSON bytes + (west, south, east, north)


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


# Only the evidence fields `feature_for` reads; the stored polygon (`geometry`, kept for the
# 2dsphere index), contribution and pass metadata stay on the server (A29).
EVIDENCE_PROJECTION = {
    "_id": 0, "hazard_id": 1, "type": 1, "title": 1, "summary": 1,
    "source_url": 1, "created_at": 1, "expires_at": 1,
}


async def _newest(db, query: dict, field: str) -> datetime | None:
    """Newest `field` among `query`: one index-covered document, no bodies streamed."""
    cursor = db.intel_cache.find(query, {field: 1}).sort(field, -1).limit(1)
    docs = await cursor.to_list(length=1)
    return docs[0].get(field) if docs else None


async def hazards_marker(db) -> tuple:
    """Cheap change marker: (belief count, newest belief `last_updated`, evidence count, newest
    evidence `created_at`), four index-covered queries (A29).

    It replaces the full-collection fingerprint, which streamed every document on every ingest run
    and got the M0 cluster throttled. Trade-off: a change that keeps both the count and the newest
    timestamp is missed (register_hazard always bumps `last_updated`, evidence documents are
    insert-only), and a re-registration that only bumps `last_updated` looks like a change.
    MIN_REBUILD_SECONDS caps how often that can trigger a full rebuild.
    """
    beliefs = await db.intel_cache.count_documents({"type": "hazard_belief"})
    evidence = await db.intel_cache.count_documents({"_id": {"$regex": "^evidence:"}})
    return (beliefs, await _newest(db, {"type": "hazard_belief"}, "last_updated"),
            evidence, await _newest(db, {"_id": {"$regex": "^evidence:"}}, "created_at"))


async def collect_features(db, t: datetime,
                           beliefs: list[dict]) -> tuple[dict[str, list[Feature]], dict[str, datetime]]:
    """Every belief at `t` as encoded map feature bytes with bounds and per-source freshness
    (`<source>` = last hazard change; `<job>_run` is merged from the runs cache at render time).

    This is the expensive step (one Mongo read of evidence plus the caller's one read of beliefs,
    Shapely per geometry); the snapshot calls it once and reuses the result instead of running it
    per request. `beliefs` is the rebuild's one full belief read, shared with the router (A29).

    The Mongo read stays on the event loop (it's async I/O); the CPU part (Shapely per geometry,
    JSON encoding of ~30k features) runs in a worker thread, so a rebuild never stops the server
    from answering /route and /layers meanwhile.
    """
    evidence_docs = await db.intel_cache.find({"_id": {"$regex": "^evidence:"}},
                                              EVIDENCE_PROJECTION).to_list(length=None)
    return await asyncio.to_thread(_encode_features, beliefs, evidence_docs, t)


def _encode_features(beliefs: list[dict], evidence_docs: list[dict],
                     t: datetime) -> tuple[dict[str, list[Feature]], dict[str, datetime]]:
    """The CPU-bound half of collect_features: pure, so it can run off the event loop."""
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
            encoded = json.dumps(feature, separators=(",", ":"), default=str).encode()
            features[doc["hazard_type"]].append((encoded, geometry_bounds(feature["geometry"])))
    for item in evidence_docs:
        created = _parse(item.get("created_at"))
        kind = "news" if item.get("type") == "news" else item.get("type")
        if created and kind:
            freshness[kind] = max(freshness.get(kind, created), created)
    return features, freshness


_RADAR_BYTES = json.dumps(RADAR_OVERLAY, separators=(",", ":")).encode()


def _render(t: datetime, features: dict[str, list[Feature]], freshness: dict[str, datetime],
            area: Bounds | None = None, runs: dict[str, dict] | None = None) -> bytes:
    """Join the pre-encoded feature bytes into the response JSON, without re-serialising them.

    `freshness` is the snapshot's per-source last-change map; `runs` (the ingest-run cache) is
    merged in at render time as `<job>_run`, so run freshness moves even when the snapshot keeps
    serving without a rebuild.
    """
    merged = {**freshness, **{f"{job}_run": run for job, run in (runs or {}).items()}}
    rendered = json.dumps({key: value.isoformat() if isinstance(value, datetime) else value
                           for key, value in sorted(merged.items())}, separators=(",", ":"))
    parts = [b'{"t":"', t.isoformat().encode(), b'","freshness":', rendered.encode(),
             b',"radar":', _RADAR_BYTES]
    for key in CATEGORIES:
        parts.append(b',"' + key.encode() + b'":{"type":"FeatureCollection","features":[')
        first = True
        for encoded, bounds in features.get(key, ()):
            if area is not None and not _intersects(bounds, area):
                continue
            if not first:
                parts.append(b",")
            first = False
            parts.append(encoded)
        parts.append(b"]}")
    parts.append(b"}")
    return b"".join(parts)


async def build_layers(db, t: datetime, area=None) -> bytes:
    """Slow path: read and convert everything for this exact `t` (used when `t` is far from now)."""
    beliefs = await belief_docs(db)
    features, freshness = await collect_features(db, t, beliefs)
    return _render(t, features, freshness, area.bounds if area is not None else None,
                   await runs_freshness(db))


class Snapshot:
    """Encoded map features at one build time, with bounds and the change marker it was built from.

    Features are compact JSON `bytes`, not nested dicts: the snapshot is a few MB instead of tens
    of MB, and rendering a response is a join instead of a re-serialisation (A27).
    """

    __slots__ = ("built_at", "built_monotonic", "count", "features", "freshness", "marker",
                 "rebuilt_monotonic")

    def __init__(self, built_at: datetime, features: dict[str, list[Feature]],
                 freshness: dict[str, datetime], marker: tuple):
        self.built_at = built_at
        self.built_monotonic = time.monotonic()
        # Moved only by a real rebuild, unlike built_monotonic (mark_fresh restarts the TTL
        # clock): the min rebuild interval must not restart when an ingest finds no change (A29).
        self.rebuilt_monotonic = self.built_monotonic
        self.features = features
        self.freshness = freshness
        self.marker = marker
        self.count = sum(len(entries) for entries in features.values())

    def mark_fresh(self) -> None:
        """An ingest verified the content is unchanged: restart the TTL clock without a rebuild."""
        self.built_monotonic = time.monotonic()


LAYERS_CACHE_SECONDS = 60
_layers_cache: dict[tuple, tuple[float, bytes]] = {}

_snapshot: Snapshot | None = None
_snapshot_locks: dict[int, asyncio.Lock] = {}


def _snapshot_lock() -> asyncio.Lock:
    """One lock per running event loop: the app has a single loop, tests create several."""
    loop = asyncio.get_running_loop()
    lock = _snapshot_locks.get(id(loop))
    if lock is None:
        lock = asyncio.Lock()
        _snapshot_locks[id(loop)] = lock
    return lock


def clear_snapshot() -> None:
    """Drop the snapshot and the runs cache (tests need each fake database to build its own)."""
    global _snapshot
    _snapshot = None
    _layers_cache.clear()
    _rebuild_tasks.clear()
    clear_runs()


async def _build_snapshot(db, marker: tuple | None = None) -> Snapshot:
    started = time.monotonic()
    built_at = datetime.now(timezone.utc)
    if marker is None:
        marker = await hazards_marker(db)
    # Its own fresh read, not the shared belief cache (up to BELIEF_CACHE_SECONDS old). Routes keep
    # the previous cache while this runs, and it's replaced below only once the build succeeded, so
    # routes and the map still share one query per rebuild (A29) and no route waits on a rebuild.
    beliefs = await read_belief_docs(db)
    features, freshness = await collect_features(db, built_at, beliefs)
    snapshot = Snapshot(built_at, features, freshness, marker)
    seed_belief_cache(db, beliefs)
    # Far-`t` answers cached before this build are based on the old hazards.
    _layers_cache.clear()
    log.info("Layers snapshot rebuilt in %.0f ms: %d features", (time.monotonic() - started) * 1000,
             snapshot.count)
    return snapshot


async def refresh_snapshot_if_changed(db) -> bool:
    """Rebuild the snapshot inline when the belief store changed since it was built.

    Called from inside `/internal/ingest/*` (Cloud Run has CPU while the request runs) after the
    job. The cheap marker (A29: counts + newest timestamps, not a full read) decides whether
    anything changed; an unchanged marker restarts the snapshot's and the belief cache's age clocks
    (the ingest request just verified them), so the TTL only expires on an instance that never
    receives ingest calls. A changed marker rebuilds at most once per MIN_REBUILD_SECONDS, because
    weather/HERE re-registrations bump `last_updated` every 5 min and a full read each time is what
    throttled Atlas M0. The build's CPU work runs in a thread, so user requests keep being served
    from the current snapshot meanwhile. Run freshness is not part of the snapshot (A28):
    `/internal/ingest` refreshes the runs cache separately. Never raises: a failed check or rebuild
    keeps the current snapshot serving. Returns whether the snapshot was rebuilt.
    """
    global _snapshot
    async with _snapshot_lock():
        snapshot = _snapshot
        try:
            marker = await hazards_marker(db)
        except Exception:
            log.exception("Layers change marker failed; keeping the current snapshot")
            return False
        if snapshot is not None:
            if marker == snapshot.marker:
                snapshot.mark_fresh()
                touch_belief_cache(db)
                log.info("Layers snapshot kept (%d features): no hazard change", snapshot.count)
                return False
            age = time.monotonic() - snapshot.rebuilt_monotonic
            if age < MIN_REBUILD_SECONDS:
                log.info("Layers snapshot kept (%d features): changed, but rebuilt %.0f s ago",
                         snapshot.count, age)
                return False
        try:
            _snapshot = await _build_snapshot(db, marker)
        except Exception:
            log.exception("Layers snapshot rebuild failed; keeping the current snapshot")
            return False
        return True


def _is_fresh(snapshot: Snapshot | None) -> bool:
    return snapshot is not None and time.monotonic() - snapshot.built_monotonic < SNAPSHOT_TTL_SECONDS


async def _rebuild_if_stale(db) -> None:
    """One rebuild under the lock, skipped if another one already made the snapshot fresh."""
    global _snapshot
    async with _snapshot_lock():
        if _is_fresh(_snapshot):
            return
        try:
            _snapshot = await _build_snapshot(db)
        except Exception:
            log.exception("Layers snapshot rebuild failed; keeping the current snapshot")


# The background rebuild per event loop (one loop in the app, several in tests). Kept referenced
# so it isn't garbage-collected mid-build; at most one runs at a time.
_rebuild_tasks: dict[int, asyncio.Task] = {}


def rebuild_in_background(db) -> asyncio.Task:
    """Start a background rebuild unless one is already running, and return it."""
    loop = asyncio.get_running_loop()
    task = _rebuild_tasks.get(id(loop))
    if task is None or task.done():
        task = loop.create_task(_rebuild_if_stale(db))
        _rebuild_tasks[id(loop)] = task
    return task


async def get_snapshot(db) -> Snapshot | None:
    """The snapshot, never waiting for a rebuild when one exists (stale-while-revalidate).

    Past the TTL, the current snapshot is served straight away and one background rebuild starts;
    the next requests get the new one once it's ready. Only an instance with no snapshot at all
    builds inline, and the startup warm-up (`warm_snapshot`) makes that rare. Cloud Run only gives
    CPU while a request is in flight, so a background rebuild may pause between requests; that only
    delays it, and the old snapshot serves meanwhile. A failed rebuild keeps the previous snapshot.
    """
    snapshot = _snapshot
    if snapshot is not None:
        if not _is_fresh(snapshot):
            rebuild_in_background(db)
        return snapshot
    await _rebuild_if_stale(db)
    return _snapshot


# Cloud Run's default startup probe gives the container 240 s to start listening; stay well inside.
WARM_TIMEOUT_SECONDS = 120


async def warm_snapshot(db=None) -> None:
    """Build the snapshot before the server accepts traffic (awaited from the app's lifespan).

    Cloud Run routes requests to a new instance only once it's listening, and uvicorn listens only
    after startup, so no user request meets a cold instance. On a deploy the old revision keeps
    serving until then. Never raises: past WARM_TIMEOUT_SECONDS startup goes on and the build
    finishes in the background; if it fails, the first /layers request builds it instead.
    """
    try:
        task = asyncio.ensure_future(_rebuild_if_stale(db if db is not None else get_db()))
        await asyncio.wait_for(asyncio.shield(task), WARM_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        log.warning("Layers snapshot warm-up still running after %d s; starting anyway",
                    WARM_TIMEOUT_SECONDS)
        _rebuild_tasks[id(asyncio.get_running_loop())] = task
    except Exception:
        log.exception("Layers snapshot warm-up failed; the first /layers request will build it")


def _response(body: bytes) -> Response:
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
        db = get_db()
        snapshot = await get_snapshot(db)
        if snapshot is not None:
            return _response(_render(when, snapshot.features, snapshot.freshness, area_bounds,
                                     await runs_freshness(db)))
    # Every other `t` (the time scrubber) keeps the exact slow path, cached by minute + bbox for 60 s.
    key = (when.replace(second=0, microsecond=0), bbox)
    cached = _layers_cache.get(key)
    if cached and time.monotonic() - cached[0] < LAYERS_CACHE_SECONDS:
        return Response(content=cached[1], media_type="application/json",
                        headers={"Cache-Control": "public, max-age=60"})
    body = await build_layers(get_db(), when, area)
    now = time.monotonic()
    for stale in [k for k, (at, _) in _layers_cache.items() if now - at >= LAYERS_CACHE_SECONDS]:
        del _layers_cache[stale]
    _layers_cache[key] = (now, body)
    return Response(content=body, media_type="application/json",
                    headers={"Cache-Control": "public, max-age=60"})
