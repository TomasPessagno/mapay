"""Deterministic routing on an already-loaded OSMnx MultiDiGraph."""
from itertools import pairwise

import networkx as nx
from shapely.geometry import LineString, mapping, shape

from app.routing.belief_config import BELIEF_CONFIG as C


def route_on_graph(graph, origin, destination, hazards=(), avoid_tolls=False):
    graph = graph.copy()
    active = [shape(h["geometry"]).buffer(C["route_buffer_degrees"])
              for h in hazards if h["log_odds"] >= C["threshold"]]
    for u, v, key, edge in list(graph.edges(keys=True, data=True)):
        if avoid_tolls and str(edge.get("toll", "no")).lower() in ("yes", "true", "1"):
            graph.remove_edge(u, v, key)
            continue
        geometry = edge.get("geometry")
        if geometry is None:
            geometry = LineString([(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in (u, v)])
        edge["route_geometry"] = geometry
        cost = float(edge["travel_time"])
        edge["hazard_weight"] = cost * (C["hazard_weight_multiplier"] if any(geometry.intersects(h) for h in active) else 1)
    def nearest(point):
        return min(graph.nodes, key=lambda n: (graph.nodes[n]["y"] - point[0]) ** 2 +
                   (graph.nodes[n]["x"] - point[1]) ** 2)
    path = nx.shortest_path(graph, nearest(origin), nearest(destination), weight="hazard_weight")
    features = []
    for u, v in pairwise(path):
        edge = min(graph[u][v].values(), key=lambda e: e["hazard_weight"])
        features.append({"type": "Feature", "geometry": mapping(edge["route_geometry"]), "properties": {}})
    return {"type": "FeatureCollection", "features": features}


def baseline_route(graph, origin, destination):
    return route_on_graph(graph, origin, destination)


def weighted_route(graph, origin, destination, hazards=(), avoid_tolls=False):
    return route_on_graph(graph, origin, destination, hazards, avoid_tolls)
