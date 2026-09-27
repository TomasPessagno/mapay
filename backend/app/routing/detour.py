"""Steer around hazards Google can't avoid on its own (AGENTS.md › Routing, steps 3 and 5).

If the best route still crosses an `avoid` hazard with severity ≥ 4 (or an avoided neighbourhood,
which scores as severity 5), one `via` waypoint goes ~300 m past the hazard's edge, perpendicular
to the route, on the side with fewer hazards, and the route is requested again with it (Google
returns a single route when intermediates are set). At most 2 rounds and 3 waypoints. A detour is
kept only when it scores better. Deterministic; no LLM.
"""
import math
from collections.abc import Awaitable, Callable

from shapely.geometry import Point, shape

from app.routers.neighborhoods import search
from app.routing.belief_config import BELIEF_CONFIG as C
from app.routing.google_routes import NoRouteFound, RoutesApiError
from app.routing.scoring import TITLES, HazardIndex, LocalPlane, corridor_for, rank

MAX_ROUNDS = 2
MAX_WAYPOINTS = 3
PAST_EDGE_M = 300
BLOCKING_SEVERITY = 4
STEP_M = 50
MAX_REACH_M = 6000  # give up on hazards wider than this (e.g. a whole city)
HAZARD_BUFFER_M = 30


def blockers(alternative: dict, index: HazardIndex, preferences: dict) -> list[dict]:
    """What the route still crosses that the user wants avoided, worst first."""
    _, corridor = corridor_for(alternative["route_geojson"])
    found = []
    for hazard in index.on(corridor):
        if (preferences["categories"].get(hazard["hazard_type"]) == "avoid"
                and hazard.get("severity", 1) >= BLOCKING_SEVERITY):
            title = (hazard.get("properties") or {}).get("title") or TITLES.get(hazard["hazard_type"], "hazard")
            found.append({"label": title, "severity": hazard["severity"], "geometry": shape(hazard["geometry"])})
    for area in alternative.get("avoid_hits", []):
        label = neighborhood_name(area["id"]) if area["kind"] == "neighborhood" else area["label"]
        found.append({"label": label, "severity": 5, "geometry": area["geometry"]})
    found.sort(key=lambda b: b["severity"], reverse=True)
    return found


def neighborhood_name(neighborhood_id: str) -> str:
    return next((n["name"] for n in search(neighborhood_id) if n["id"] == neighborhood_id), neighborhood_id)


def via_point(route_geojson: dict, hazard_geometry, index: HazardIndex) -> tuple[float, float] | None:
    """(lat, lng) ~300 m past the hazard's edge, perpendicular to the route, on the quieter side."""
    line_deg, _ = corridor_for(route_geojson)
    plane = LocalPlane(line_deg.centroid.y)
    line = plane.to_m(line_deg)
    blocker = plane.to_m(hazard_geometry).buffer(HAZARD_BUFFER_M)
    crossing = line.intersection(blocker)
    if crossing.is_empty:
        return None
    s = line.project(crossing.centroid)
    a, b = line.interpolate(max(0.0, s - STEP_M)), line.interpolate(min(line.length, s + STEP_M))
    dx, dy = b.x - a.x, b.y - a.y
    norm = math.hypot(dx, dy)
    if norm == 0:
        return None
    nx, ny = -dy / norm, dx / norm
    anchor = line.interpolate(s)
    candidates = []
    for side in (1, -1):
        reach = next((d for d in range(0, MAX_REACH_M + 1, STEP_M)
                      if not blocker.contains(Point(anchor.x + side * nx * d, anchor.y + side * ny * d))), None)
        if reach is None:
            continue
        d = reach + PAST_EDGE_M
        spot = plane.to_deg(Point(anchor.x + side * nx * d, anchor.y + side * ny * d))
        nearby = plane.to_deg(plane.to_m(spot).buffer(PAST_EDGE_M))
        weighted = [h for h in index.on(nearby) if h["log_odds"] >= C["threshold"]]
        candidates.append((len(weighted), reach, spot))
    if not candidates:
        return None
    _, _, spot = min(candidates, key=lambda c: (c[0], c[1]))
    return (round(spot.y, 6), round(spot.x, 6))


Compute = Callable[[list[tuple[float, float]]], Awaitable[list[dict]]]


async def plan_detour(best: dict, hazards, preferences: dict, compute: Compute,
                      avoid_areas: list[dict] | None = None) -> dict:
    """Returns {route, waypoints, unavoidable}: the best route found (the input if no detour
    helps), its via waypoints, and labels of avoid-hazards it still crosses."""
    index = HazardIndex(hazards)
    waypoints: list[tuple[float, float]] = []
    for _ in range(MAX_ROUNDS):
        remaining = blockers(best, index, preferences)
        if not remaining or len(waypoints) >= MAX_WAYPOINTS:
            break
        via = via_point(best["route_geojson"], remaining[0]["geometry"], index)
        if via is None:
            break
        try:
            candidate = rank(await compute([*waypoints, via]), hazards, preferences, avoid_areas)[0]
        except (NoRouteFound, RoutesApiError):  # keep the route we have
            break
        if candidate["score"] >= best["score"]:
            break
        best, waypoints = candidate, [*waypoints, via]
    unavoidable = list(dict.fromkeys(b["label"] for b in blockers(best, index, preferences)))
    return {"route": best, "waypoints": waypoints, "unavoidable": unavoidable}


def briefing(route: dict, detoured: bool, unavoidable: list[str]) -> str:
    minutes = round(route["duration_s"] / 60)
    summary = route.get("summary") or "the fastest route"
    text = f"Taking {summary}: about {minutes} min."
    if detoured:
        text += " Mapay added a waypoint to steer around hazards on the faster roads."
    if unavoidable:
        text += f" Couldn't avoid: {', '.join(u[0].lower() + u[1:] for u in unavoidable[:3])}; this is the best available."
    elif route.get("hazards_on_route"):
        titles = list(dict.fromkeys(h["title"].lower() for h in route["hazards_on_route"]))[:2]
        text += " Watch for " + ", ".join(titles) + "."
    return text
