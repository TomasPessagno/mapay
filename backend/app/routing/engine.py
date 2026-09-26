"""Deterministic weighted routing. The LLM never touches this path."""
import networkx as nx

from app.db.models import LatLng


def baseline_route(graph: nx.MultiDiGraph, origin: LatLng, destination: LatLng) -> dict:
    # TODO: shortest path by travel_time -> GeoJSON
    raise NotImplementedError


def weighted_route(graph: nx.MultiDiGraph, origin: LatLng, destination: LatLng) -> dict:
    # TODO: shortest path by hazard_weight -> GeoJSON + hazards_avoided
    raise NotImplementedError
