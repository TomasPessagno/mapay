"""Ingestion: FEMA National Flood Hazard Layer (NFHL) flood zones. See AGENTS.md data sources table.

Zones are looked up once per hotspot and cached in data/flood_hotspots.geojson
(`python -m app.ingestion.fema` refreshes them), so the hourly flood job never calls FEMA.
"""
import asyncio
import json
from pathlib import Path

import httpx

# Layer 28 = "Flood Hazard Zones" (S_FLD_HAZ_AR).
NFHL_ZONES_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
HOTSPOTS_PATH = Path(__file__).resolve().parents[1] / "data" / "flood_hotspots.geojson"
# Worst first: coastal high hazard, then 1% annual chance, then the rest.
ZONE_RANK = ["VE", "V", "AE", "AH", "AO", "A", "X"]


def zone_query(lng: float, lat: float) -> dict:
    return {"geometry": f"{lng},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects", "outFields": "FLD_ZONE,ZONE_SUBTY",
            "returnGeometry": "false", "f": "json"}


def parse_zone(payload: dict) -> str | None:
    """Most hazardous zone among the polygons at the point; None outside mapped areas."""
    if "error" in payload:
        raise RuntimeError(f"FEMA NFHL error: {payload['error']}")
    zones = {f["attributes"]["FLD_ZONE"].upper() for f in payload.get("features", [])
             if f.get("attributes", {}).get("FLD_ZONE")}
    if not zones:
        return None
    return min(zones, key=lambda z: ZONE_RANK.index(z) if z in ZONE_RANK else len(ZONE_RANK))


async def zone_at(lng: float, lat: float, client: httpx.AsyncClient) -> str | None:
    response = await client.get(NFHL_ZONES_URL, params=zone_query(lng, lat))
    response.raise_for_status()
    return parse_zone(response.json())


async def fetch(points: list[tuple[float, float]], client: httpx.AsyncClient | None = None) -> list[str | None]:
    """FEMA zone for each (lng, lat)."""
    owned = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        return [await zone_at(lng, lat, client) for lng, lat in points]
    finally:
        if owned:
            await client.aclose()


async def refresh_hotspot_zones(path: Path = HOTSPOTS_PATH, client: httpx.AsyncClient | None = None) -> dict:
    """Look up every hotspot's zone and write it back as `fema_zone` (a dev task, not a job)."""
    collection = json.loads(path.read_text())
    points = [tuple(f["geometry"]["coordinates"]) for f in collection["features"]]
    for feature, zone in zip(collection["features"], await fetch(points, client), strict=True):
        feature["properties"]["fema_zone"] = zone or "X"
    path.write_text(json.dumps(collection, indent=2) + "\n")
    return collection


if __name__ == "__main__":
    for f in asyncio.run(refresh_hotspot_zones())["features"]:
        print(f["properties"]["id"], f["properties"]["fema_zone"])
