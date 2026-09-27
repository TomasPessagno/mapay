"""Deterministic route choice over Google Routes API alternatives.

Google computes the candidate paths; routing/scoring.py ranks them against the hazard beliefs
and the user's preferences. The choice never involves an LLM.
"""
from app.routing.google_routes import compute_routes
from app.routing.scoring import merge_preferences, rank


def pick_route(alternatives: list[dict], hazards=(), preferences: dict | None = None) -> dict:
    """The cheapest alternative under `preferences` (AGENTS.md defaults when None)."""
    return rank(alternatives, hazards, preferences or merge_preferences())[0]


async def route_alternatives(origin, destination, depart_at=None, avoid_tolls=False, avoid_highways=False,
                             mode="drive"):
    return await compute_routes(origin, destination, depart_at=depart_at, avoid_tolls=avoid_tolls,
                                avoid_highways=avoid_highways, mode=mode)


async def weighted_route(origin, destination, hazards=(), avoid_tolls=False, depart_at=None,
                         avoid_highways=False, mode="drive", preferences: dict | None = None) -> dict:
    """GeoJSON FeatureCollection of the chosen route."""
    alternatives = await route_alternatives(origin, destination, depart_at, avoid_tolls, avoid_highways, mode)
    return pick_route(alternatives, hazards, preferences)["route_geojson"]
