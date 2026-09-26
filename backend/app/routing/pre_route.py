"""Client-timer pre-route checks; no push infrastructure or LLM decisions."""
from datetime import datetime
from zoneinfo import ZoneInfo

from shapely.geometry import shape
from shapely.ops import unary_union

from app.agents.briefing import explain_recalculation
from app.routing.belief_config import BELIEF_CONFIG as C
from app.routing.beliefs import refresh_belief, snapshot, threshold_changes, utc
from app.routing.engine import weighted_route


def on_route(route: dict, hazards: list[dict]) -> dict:
    corridor = unary_union([shape(f["geometry"]) for f in route["features"]]).buffer(C["route_buffer_degrees"])
    return {h["hazard_id"]: snapshot(h) for h in hazards if corridor.intersects(shape(h["geometry"]))}


async def current_hazards(db, now):
    docs = await db.intel_cache.find({"type": "hazard_belief"}).to_list(length=None)
    return [await refresh_belief(db, h["hazard_id"], now) for h in docs]


async def check_routine(db, routine: dict, departure: datetime, now: datetime, graph) -> dict:
    if departure.tzinfo is None:
        raise ValueError("departure must include a timezone")
    local = departure.astimezone(ZoneInfo("America/New_York"))
    if local.strftime("%a").lower() not in routine["days"]:
        raise ValueError("Departure is not on a scheduled day")
    start, end = routine["time_window"]
    clock = local.strftime("%H:%M")
    if not start <= clock <= end:
        raise ValueError("Departure is outside the routine time window")
    minutes = (utc(departure) - utc(now)).total_seconds() / 60
    low, high = C["check_window_minutes"]
    if not low <= minutes <= high:
        return {"recalculated": False, "reason": "outside_pre_route_window"}
    hazards = await current_hazards(db, now)
    previous = routine.get("route_state")
    if previous and utc(previous["departure"]) != utc(departure):
        previous = None
    changes = threshold_changes(previous["beliefs"], on_route(previous["route_geojson"], hazards)) if previous else []
    if previous and not changes:
        return {"recalculated": False, "reason": "no_threshold_crossing", "route_geojson": previous["route_geojson"]}
    if graph is None:
        raise RuntimeError("Routing graph is not loaded")
    preferences = routine.get("preferences", {})
    if preferences.get("mode", "drive") != "drive":
        raise ValueError("A walking graph is not available")
    route = weighted_route(graph, routine["origin"], routine["destination"], hazards,
                           avoid_tolls=preferences.get("avoid_tolls", False))
    state = {"departure": utc(departure), "computed_at": utc(now), "route_geojson": route,
             "beliefs": on_route(route, hazards)}
    # Prevent concurrent checks from overwriting a newer route state.
    result = await db.routines.update_one(
        {"_id": routine["_id"], "route_state": routine.get("route_state")}, {"$set": {"route_state": state}})
    if not result.matched_count:
        return {"recalculated": False, "reason": "concurrent_check_retry"}
    explanation = await explain_recalculation(changes) if changes else None
    return {"recalculated": bool(changes), "reason": "threshold_crossing" if changes else "initial_route",
            "route_geojson": route, "changes": changes, "briefing": explanation}
