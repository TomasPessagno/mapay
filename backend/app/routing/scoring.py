"""Deterministic route scoring: Google supplies the alternatives, Mapay picks the safest one.

cost = predicted_minutes + Σ penalty over active hazard beliefs (log-odds ≥ threshold) inside an
alternative's ~30 m corridor, where penalty = weight(preference) × severity × p × 3 min.
An avoided neighbourhood the route enters counts as a severity-5 hazard with p = 1 and the
`avoid` weight. See AGENTS.md › Routing (step 2) and › Preferences. No LLM on this path.
"""
from shapely import STRtree
from shapely.geometry import shape
from shapely.ops import unary_union

from app.deps import default_preferences
from app.routers.neighborhoods import get_polygon
from app.routing.belief_config import BELIEF_CONFIG as C
from app.routing.beliefs import probability

WEIGHTS = {"avoid": 10, "prefer_avoid": 2, "ignore": 0}
PENALTY_MINUTES = 3
NEIGHBORHOOD_SEVERITY = 5
TITLES = {"flood": "Flooded street", "weather": "Weather alert", "construction": "Construction",
          "closure": "Road closed", "congestion": "Heavy traffic", "no_sidewalk": "No sidewalk",
          "pothole": "Potholes", "incident": "Incident", "event": "Event"}


def merge_preferences(*layers: dict | None) -> dict:
    """Later layers win: AGENTS.md defaults ← user defaults ← routine / request overrides.
    `categories` merges per key; everything else is replaced when present."""
    merged = default_preferences()
    for layer in layers:
        if not layer:
            continue
        for key, value in layer.items():
            if value is None:
                continue
            if key == "categories":
                merged["categories"] = {**merged["categories"], **value}
            else:
                merged[key] = value
    return merged


class HazardIndex:
    """Active beliefs in an STRtree, so each alternative is one spatial query."""

    def __init__(self, hazards):
        self.hazards, geometries = [], []
        for hazard in hazards:
            if hazard["log_odds"] < C["threshold"]:
                continue
            try:
                geometries.append(shape(hazard["geometry"]))
            except Exception:  # noqa: BLE001, S112 - a malformed belief is never routable
                continue
            self.hazards.append(hazard)
        self.geometries = geometries
        self.tree = STRtree(geometries) if geometries else None

    def on(self, corridor) -> list[dict]:
        if self.tree is None:
            return []
        return [self.hazards[i] for i in self.tree.query(corridor, predicate="intersects")]


def corridor_for(route_geojson: dict):
    lines = unary_union([shape(f["geometry"]) for f in route_geojson["features"]])
    return lines, lines.buffer(C["route_buffer_degrees"])


def hazard_entry(hazard: dict, p: float) -> dict:
    title = (hazard.get("properties") or {}).get("title") or TITLES.get(hazard["hazard_type"], hazard["hazard_type"])
    return {"hazard_id": hazard["hazard_id"], "hazard_type": hazard["hazard_type"], "title": title,
            "probability": round(p, 2)}


def score_alternative(alternative: dict, index: HazardIndex, preferences: dict) -> dict:
    """Cost, the hazards on the route (worst first) and the avoided neighbourhoods it enters."""
    line, corridor = corridor_for(alternative["route_geojson"])
    categories = preferences["categories"]
    penalties = []
    for hazard in index.on(corridor):
        p = probability(hazard["log_odds"])
        weight = WEIGHTS.get(categories.get(hazard["hazard_type"], "ignore"), 0)
        penalties.append((weight * hazard.get("severity", 1) * p * PENALTY_MINUTES, p, hazard))
    crossed = []
    for neighborhood_id in preferences.get("avoid_neighborhoods") or []:
        polygon = get_polygon(neighborhood_id)
        if polygon is not None and line.intersects(polygon):
            crossed.append(neighborhood_id)
    penalty = sum(p for p, _, _ in penalties)
    penalty += len(crossed) * WEIGHTS["avoid"] * NEIGHBORHOOD_SEVERITY * 1.0 * PENALTY_MINUTES
    penalties.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return {"score": round(alternative["duration_s"] / 60 + penalty, 1),
            "hazards_on_route": [hazard_entry(h, p) for _, p, h in penalties],
            "neighborhoods_crossed": crossed}


def rank(alternatives: list[dict], hazards, preferences: dict) -> list[dict]:
    """Alternatives with score / recommended / hazards_on_route filled, cheapest first.
    Ties keep Google's order, so with nothing on any route Google's first route wins."""
    index = HazardIndex(hazards)
    scored = [{**alt, **score_alternative(alt, index, preferences)} for alt in alternatives]
    scored.sort(key=lambda alt: alt["score"])
    for position, alt in enumerate(scored):
        alt["recommended"] = position == 0
    return scored
