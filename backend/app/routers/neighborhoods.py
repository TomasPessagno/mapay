"""Neighbourhood search and polygon lookup.

`app/data/neighborhoods.geojson` is built by `scripts/build_neighborhoods.py`.
Routing (A6) and Customize (A10) import `get_polygon` to turn an avoided name
into a Shapely geometry.
"""
import json
from functools import cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query
from shapely.geometry import shape

router = APIRouter(prefix="/neighborhoods", tags=["neighborhoods"])

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "neighborhoods.geojson"


@cache
def _features(path: str) -> tuple[dict, ...]:
    with open(path, encoding="utf-8") as handle:
        return tuple(json.load(handle).get("features", []))


def search(q: str | None = None, path: Path | str | None = None) -> list[dict]:
    """Return {id, name, source} for every neighborhood whose name or id matches q."""
    needle = (q or "").strip().lower()
    matches = []
    for feature in _features(str(path or DATA_PATH)):
        properties = feature["properties"]
        if needle and needle not in properties["name"].lower() and needle not in properties["id"]:
            continue
        matches.append({"id": properties["id"], "name": properties["name"], "source": properties["source"]})
    return matches


def get_polygon(neighborhood_id: str, path: Path | str | None = None):
    """Shapely geometry for a neighborhood id, or None when it is unknown."""
    for feature in _features(str(path or DATA_PATH)):
        if feature["properties"]["id"] == neighborhood_id:
            return shape(feature["geometry"])
    return None


@router.get("")
async def list_neighborhoods(q: Annotated[str | None, Query(description="Case-insensitive substring search")] = None):
    return search(q)
