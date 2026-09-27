"""Ingestion: typical congestion per hour of the week from Google Routes predictions (#23).

AGENTS.md › Maps APIs, "Typical congestion": computeRoutes with TRAFFIC_AWARE_OPTIMAL and a future
departureTime returns Google's predicted duration for that hour, from its historical traffic;
duration / staticDuration is the congestion ratio. Each hourly run samples the next hours of the
week for the key corridors and every active routine leg, skipping buckets sampled in the last week,
so the week fills in gradually at about a dozen Routes calls per run. Samples live 8 days (a TTL
index; we resample weekly and keep Google data only briefly, per the Maps Platform caching terms).
Corridors usually congested at the current hour become predicted `congestion` hazards.
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.ingestion.here_incidents import clear_missing
from app.routing.beliefs import register_hazard, utc
from app.routing.google_routes import NoRouteFound, RoutesApiError, compute_routes

log = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
AHEAD_HOURS = 2  # buckets sampled per run: the next two hours of the week
RESAMPLE_AFTER = timedelta(days=7)
SAMPLE_TTL = timedelta(days=8)
ID_PREFIX = "typical:"
# (lower ratio bound, level, severity): typical traffic, not live, so one step milder than HERE's.
LEVELS = [(2.0, "severe", 3), (1.6, "heavy", 2), (1.3, "moderate", 1)]
TYPICAL_PROBABILITY = 0.6  # a pattern, not an observation: shown as predicted, below the 0.73 bar

# Key corridors: (id, label, origin (lat, lng), destination) with endpoints on the road itself.
CORRIDORS = [
    ("i95-nb", "I-95 northbound, downtown → Golden Glades", (25.7695, -80.2045), (25.9200, -80.2095)),
    ("i95-sb", "I-95 southbound, Golden Glades → downtown", (25.9200, -80.2095), (25.7695, -80.2045)),
    ("sr836-eb", "SR 836 eastbound, FIU → downtown", (25.7815, -80.3700), (25.7860, -80.2060)),
    ("sr836-wb", "SR 836 westbound, downtown → FIU", (25.7860, -80.2060), (25.7815, -80.3700)),
    ("sr826-nb", "SR 826 northbound, Dadeland → Golden Glades", (25.6905, -80.3125), (25.9225, -80.2170)),
    ("sr826-sb", "SR 826 southbound, Golden Glades → Dadeland", (25.9225, -80.2170), (25.6905, -80.3125)),
    ("us1-nb", "US 1 northbound, Dadeland → Brickell", (25.6890, -80.3130), (25.7560, -80.2060)),
    ("us1-sb", "US 1 southbound, Brickell → Dadeland", (25.7560, -80.2060), (25.6890, -80.3130)),
    ("brickell-ave", "Brickell Ave", (25.7470, -80.2090), (25.7715, -80.1900)),
    ("biscayne-blvd", "Biscayne Blvd, downtown → NE 79th St", (25.7780, -80.1885), (25.8480, -80.1845)),
]


def hour_of_week(moment: datetime) -> int:
    local = moment.astimezone(NY)
    return local.weekday() * 24 + local.hour


def upcoming_buckets(now: datetime, hours: int = AHEAD_HOURS) -> list[tuple[int, datetime]]:
    """(hour_of_week, a departure in the middle of that hour) for the next `hours` whole hours."""
    local = now.astimezone(NY).replace(minute=0, second=0, microsecond=0)
    return [(hour_of_week(local + timedelta(hours=h)), local + timedelta(hours=h, minutes=30))
            for h in range(1, hours + 1)]


def level_for(ratio: float) -> tuple[str, int] | None:
    for bound, level, severity in LEVELS:
        if ratio >= bound:
            return level, severity
    return None


async def routine_legs(db) -> list[tuple[str, str, tuple, tuple]]:
    """Every active routine leg as a corridor: ("leg:<routine>:<i>", label, origin, destination)."""
    legs = []
    routines = await db.routines.find({"active": True}).to_list(length=None)
    for routine in routines:
        for index, leg in enumerate(routine.get("legs", [])):
            ends = []
            for key in ("from_place", "to_place"):
                place = await db.places.find_one({"_id": leg[key]})
                if place:
                    lng, lat = place["location"]["coordinates"]
                    ends.append((lat, lng, place.get("name") or key))
            if len(ends) == 2:
                legs.append((f"leg:{routine['_id']}:{index}", f"{ends[0][2]} → {ends[1][2]}",
                             ends[0][:2], ends[1][:2]))
    return legs


async def sample(db, corridor: tuple, bucket: int, departure: datetime, now: datetime) -> dict | None:
    corridor_id, label, origin, destination = corridor
    try:
        [route] = (await compute_routes(origin, destination, depart_at=departure))[:1]
    except (NoRouteFound, RoutesApiError) as exc:
        log.warning("Traffic sample failed for %s at %s: %s", corridor_id, bucket, exc)
        return None
    ratio = round(route["duration_s"] / max(route["static_duration_s"], 1), 3)
    doc = {"_id": f"{corridor_id}:{bucket}", "corridor_id": corridor_id, "label": label, "hour_of_week": bucket,
           "duration_s": route["duration_s"], "static_duration_s": route["static_duration_s"],
           "congestion_ratio": ratio, "departure_at": departure.astimezone(timezone.utc),
           "geometry": route["route_geojson"]["features"][0]["geometry"], "sampled_at": utc(now),
           "expires_at": utc(now) + SAMPLE_TTL}
    await db.traffic_samples.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return doc


async def run(db, now: datetime | None = None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    corridors = CORRIDORS + await routine_legs(db)
    sampled = 0
    for bucket, departure in upcoming_buckets(now):
        existing = await db.traffic_samples.find({"hour_of_week": bucket}).to_list(length=None)
        fresh = {d["corridor_id"] for d in existing if utc(d["sampled_at"]) > now - RESAMPLE_AFTER}
        for corridor in corridors:
            if corridor[0] not in fresh and await sample(db, corridor, bucket, departure, now):
                sampled += 1
    # Hazards for the current hour: key corridors only (a routine leg isn't a street segment).
    current = hour_of_week(now)
    samples = await db.traffic_samples.find({"hour_of_week": current}).to_list(length=None)
    keys = {c[0] for c in CORRIDORS}
    active = set()
    for doc in samples:
        level = level_for(doc["congestion_ratio"])
        if doc["corridor_id"] not in keys or level is None:
            continue
        hazard_id = f"{ID_PREFIX}{doc['corridor_id']}"
        await register_hazard(db, hazard_id, "congestion", doc["geometry"], {
            "probability": TYPICAL_PROBABILITY, "severity": level[1], "level": level[0],
            "title": f"Usually {level[0]} traffic at this hour", "place": doc["label"],
            "description": f"Google's typical travel time is {doc['congestion_ratio']:.1f}x the free-flow time",
            "source_label": "Google typical traffic"}, now)
        active.add(hazard_id)
    cleared = await clear_missing(db, ID_PREFIX, active, now)
    return {"corridors": len(corridors), "sampled": sampled, "congested_now": len(active), "cleared": cleared}
