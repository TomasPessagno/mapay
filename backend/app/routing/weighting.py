"""Hazard -> edge spatial join and edge-weight multipliers."""
from datetime import datetime

import networkx as nx


def apply_hazard_weights(graph: nx.MultiDiGraph, hazards: dict, depart_at: datetime) -> None:
    # TODO: spatial join hazard geometries to edges; set edge["hazard_weight"]
    raise NotImplementedError
