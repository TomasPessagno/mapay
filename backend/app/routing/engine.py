"""Deterministic route choice over Google Routes API alternatives.

Google computes the candidate paths; the choice between them never involves an LLM. Until the
full scoring in A6 lands, an alternative that crosses an active hazard costs its duration times
`hazard_weight_multiplier`, the same rule the old OSMnx graph search applied per edge.
"""
from shapely.geometry import shape
from shapely.ops import unary_union

from app.routing.belief_config import BELIEF_CONFIG as C
from app.routing.google_routes import compute_routes


def crosses_active_hazard(route: dict, hazards) -> bool:
    active = [shape(h["geometry"]) for h in hazards if h["log_odds"] >= C["threshold"]]
    if not active:
        return False
    corridor = unary_union([shape(f["geometry"]) for f in route["features"]]).buffer(C["route_buffer_degrees"])
    return any(corridor.intersects(h) for h in active)


def pick_route(alternatives: list[dict], hazards=()) -> dict:
    """The cheapest alternative; ties keep Google's order, so no hazards → Google's first route."""
    def cost(alt):
        penalty = C["hazard_weight_multiplier"] if crosses_active_hazard(alt["route_geojson"], hazards) else 1
        return alt["duration_s"] * penalty
    return min(alternatives, key=cost)


async def route_alternatives(origin, destination, depart_at=None, avoid_tolls=False, avoid_highways=False,
                             mode="drive"):
    return await compute_routes(origin, destination, depart_at=depart_at, avoid_tolls=avoid_tolls,
                                avoid_highways=avoid_highways, mode=mode)


async def weighted_route(origin, destination, hazards=(), avoid_tolls=False, depart_at=None,
                         avoid_highways=False, mode="drive") -> dict:
    """GeoJSON FeatureCollection of the chosen route."""
    alternatives = await route_alternatives(origin, destination, depart_at, avoid_tolls, avoid_highways, mode)
    return pick_route(alternatives, hazards)["route_geojson"]
