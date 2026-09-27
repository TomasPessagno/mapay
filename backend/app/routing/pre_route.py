"""Client-timer pre-route checks; no push infrastructure or LLM decisions."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from shapely.geometry import shape
from shapely.ops import unary_union

from app.agents.briefing import explain_recalculation
from app.db.models import leg_days
from app.routing.belief_config import BELIEF_CONFIG as C
from app.routing.beliefs import belief_at, snapshot, threshold_changes, utc
from app.routing.engine import weighted_route
from app.routing.scoring import merge_preferences


def on_route(route: dict, hazards: list[dict]) -> dict:
    corridor = unary_union([shape(f["geometry"]) for f in route["features"]]).buffer(C["route_buffer_degrees"])
    return {h["hazard_id"]: snapshot(h) for h in hazards if corridor.intersects(shape(h["geometry"]))}


# A29: Atlas M0 throttles (~7.7 s for one document), so a full belief read is a last resort:
# route requests and /layers share one read per 15 min, and the snapshot rebuild is the only
# place that drops the cache, seeding it with the documents it just read.
BELIEF_CACHE_SECONDS = 15 * 60
# Only the fields the map and the router read; `_id`, `type` and any future ingestion-only
# field stay on the server, so the read stays as small as it can be (A29).
BELIEF_PROJECTION = {
    "_id": 0, "hazard_id": 1, "hazard_type": 1, "geometry": 1, "severity": 1,
    "prior_log_odds": 1, "log_odds": 1, "evidence": 1, "properties": 1,
    "created_at": 1, "last_updated": 1,
}
_belief_cache: dict[int, tuple[float, list[dict]]] = {}


async def belief_docs(db) -> list[dict]:
    """All stored belief documents, cached per process for BELIEF_CACHE_SECONDS. The /layers
    snapshot rebuild clears the cache before its own read, so the snapshot and the router share
    one query. Callers must not mutate the docs (belief_at returns copies)."""
    cached = _belief_cache.get(id(db))
    if cached and time.monotonic() - cached[0] < BELIEF_CACHE_SECONDS:
        return cached[1]
    docs = await db.intel_cache.find({"type": "hazard_belief"}, BELIEF_PROJECTION).to_list(length=None)
    _belief_cache[id(db)] = (time.monotonic(), docs)
    return docs


def clear_belief_cache() -> None:
    _belief_cache.clear()


async def current_hazards(db, now):
    """Every belief evaluated at `now`: one (cached) query, decay computed in memory (see belief_at)."""
    return [belief_at(doc, now) for doc in await belief_docs(db)]


def check_departure(routine: dict, leg_index: int, departure: datetime) -> dict:
    """The leg, if `departure` is one of its scheduled times (routine tz, DST-safe); else ValueError."""
    if departure.tzinfo is None:
        raise ValueError("departure must include a timezone")
    legs = routine.get("legs") or []
    if not 0 <= leg_index < len(legs):
        raise ValueError(f"Routine has no leg {leg_index}")
    leg = legs[leg_index]
    local = departure.astimezone(ZoneInfo(routine.get("tz") or "America/New_York"))
    if local.strftime("%a").lower() not in leg_days(routine, leg):
        raise ValueError("Departure is not on a scheduled day")
    clock, when = local.strftime("%H:%M"), leg["when"]
    if when["kind"] == "at" and clock != when["time"]:
        raise ValueError(f"Departure is not the leg's {when['time']} time")
    if when["kind"] == "window" and not when["start"] <= clock <= when["end"]:
        raise ValueError("Departure is outside the leg's time window")
    return leg


async def leg_endpoints(db, routine: dict, leg: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    """(lat, lng) of the leg's saved places."""
    points = []
    for place_id in (leg["from_place"], leg["to_place"]):
        place = await db.places.find_one({"_id": place_id, "user_id": routine["user_id"]})
        if place is None:
            raise ValueError(f"Unknown place {place_id}")
        lng, lat = place["location"]["coordinates"]
        points.append((lat, lng))
    return points[0], points[1]


async def check_routine(db, routine: dict, leg_index: int, departure: datetime, now: datetime,
                        demo: bool = False) -> dict:
    """Re-check one leg's saved route 30–60 min before it leaves; recompute only on a crossing.
    `demo`: the departure comes from a /demo/heads-up override, so it skips the schedule check."""
    if demo:
        if not 0 <= leg_index < len(routine.get("legs") or []):
            raise ValueError(f"Routine has no leg {leg_index}")
        leg = routine["legs"][leg_index]
    else:
        leg = check_departure(routine, leg_index, departure)
    minutes = (utc(departure) - utc(now)).total_seconds() / 60
    low, high = C["check_window_minutes"]
    # A demo departure is set exactly heads_up_minutes (30) ahead, and the app checks right after
    # firing it, i.e. at 29.9 min: for demos any departure still ahead is in the window.
    in_window = 0 < minutes <= high if demo else low <= minutes <= high
    if not in_window:
        return {"recalculated": False, "reason": "outside_pre_route_window"}
    hazards = await current_hazards(db, now)
    previous = leg.get("route_state")
    if previous and utc(previous["departure"]) != utc(departure):
        previous = None
    changes = threshold_changes(previous["beliefs"], on_route(previous["route_geojson"], hazards)) if previous else []
    if previous and not changes:
        return {"recalculated": False, "reason": "no_threshold_crossing", "route_geojson": previous["route_geojson"]}
    origin, destination = await leg_endpoints(db, routine, leg)
    user = await db.users.find_one({"_id": routine["user_id"]}) or {}
    preferences = merge_preferences(user.get("preferences"), routine.get("preferences"))
    route = await weighted_route(origin, destination, hazards,
                                 avoid_tolls=preferences["avoid_tolls"], depart_at=departure,
                                 avoid_highways=preferences["avoid_highways"],
                                 mode=preferences.get("mode", "drive"), preferences=preferences)
    state = {"departure": utc(departure), "computed_at": utc(now), "route_geojson": route,
             "beliefs": on_route(route, hazards)}
    # Compare-and-swap on this leg: a concurrent check or an edit to the leg wins over us.
    path = f"legs.{leg_index}"
    result = await db.routines.update_one(
        {"_id": routine["_id"], f"{path}.route_state": leg.get("route_state"),
         f"{path}.from_place": leg["from_place"], f"{path}.to_place": leg["to_place"]},
        {"$set": {f"{path}.route_state": state}})
    if not result.matched_count:
        return {"recalculated": False, "reason": "concurrent_check_retry"}
    explanation = await explain_recalculation(changes) if changes else None
    return {"recalculated": bool(changes), "reason": "threshold_crossing" if changes else "initial_route",
            "route_geojson": route, "changes": changes, "briefing": explanation}
