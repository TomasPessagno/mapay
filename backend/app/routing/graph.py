"""OSMnx graph build/load. Build once offline, pickle into app/data/ (gitignored)."""
from pathlib import Path

import networkx as nx

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
GRAPH_PATH = DATA_DIR / "miami_drive.pickle"


def build_graph() -> nx.MultiDiGraph:
    # TODO: osmnx.graph_from_bbox(...) for Miami, add speeds/travel times, pickle to GRAPH_PATH
    raise NotImplementedError


def load_graph() -> nx.MultiDiGraph:
    # TODO: unpickle GRAPH_PATH
    raise NotImplementedError
