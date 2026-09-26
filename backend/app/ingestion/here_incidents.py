"""Ingestion: live traffic incidents/closures from HERE Traffic API v7 (replaces FL511, which has no public API)."""
import httpx

from app.config import get_settings

INCIDENTS_URL = "https://data.traffic.hereapi.com/v7/incidents"
MIAMI_BBOX = "bbox:-80.45,25.55,-80.10,25.98"  # west,south,east,north


async def fetch() -> dict:
    """Raw HERE response; results[].location.shape.links[].points hold the road geometry."""
    params = {"in": MIAMI_BBOX, "locationReferencing": "shape", "apiKey": get_settings().here_api_key}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(INCIDENTS_URL, params=params)
        r.raise_for_status()
        return r.json()


def to_geojson(raw: dict) -> dict:
    # TODO: one LineString per incident (points are {lat, lng}); keep type, criticality, description, start/end time
    raise NotImplementedError
