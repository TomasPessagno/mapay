"""Ingestion: NOAA CO-OPS tides at Virginia Key (8723214) → predicted flood beliefs on hotspots.

Every curated hotspot in data/flood_hotspots.geojson is registered as a `flood:<id>` belief whose
prior combines its cached FEMA zone with the predicted tide vs the minor-flood threshold
(beliefs.prior_probability). See AGENTS.md › Floods: predicted + observed.
"""
import json
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path

import httpx

from app.routing.beliefs import register_hazard

STATION = "8723214"  # Virginia Key
PREDICTIONS_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
METADATA_URL = f"https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{STATION}"
HOTSPOTS_PATH = Path(__file__).resolve().parents[1] / "data" / "flood_hotspots.geojson"
# NWS minor coastal flood stage for the Virginia Key gauge (VAKF1), in ft above MHHW. CO-OPS
# publishes the same level as nws_minor on the station datum (13.66 - MHHW 12.38 = 1.28 ft);
# used only when the metadata API is unreachable.
FALLBACK_THRESHOLD_FT_MHHW = 1.3
# A run registers the highest tide in the next few hours, so a flood that peaks between
# hourly runs (or during a commute that starts soon) is already in the prior.
LOOKAHEAD = timedelta(hours=3)


def _noaa_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%d %H:%M")


def predictions_query(start: datetime, end: datetime) -> dict:
    return {"station": STATION, "product": "predictions", "datum": "MHHW", "interval": "h",
            "units": "english", "time_zone": "gmt", "format": "json",
            "begin_date": _noaa_time(start), "end_date": _noaa_time(end)}


def parse_predictions(payload: dict) -> list[tuple[datetime, float]]:
    if "error" in payload:
        raise RuntimeError(f"NOAA CO-OPS error: {payload['error']}")
    return [(datetime.strptime(p["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc), float(p["v"]))
            for p in payload.get("predictions", [])]


def tide_at(predictions: list[tuple[datetime, float]], at: datetime) -> float:
    """Linear interpolation between hourly predictions (ft above MHHW)."""
    if not predictions:
        raise ValueError("No tide predictions")
    at = at.astimezone(timezone.utc)
    for (t0, v0), (t1, v1) in pairwise(predictions):
        if t0 <= at <= t1:
            return v0 + (v1 - v0) * (at - t0) / (t1 - t0)
    return min(predictions, key=lambda p: abs(p[0] - at))[1]


def max_tide(predictions: list[tuple[datetime, float]], start: datetime, end: datetime) -> float:
    inside = [v for t, v in predictions if start <= t <= end]
    return max([tide_at(predictions, start), tide_at(predictions, end), *inside])


def parse_threshold(floodlevels: dict, datums: dict) -> float:
    """NWS minor flood level converted from the station datum to ft above MHHW."""
    mhhw = next(d["value"] for d in datums["datums"] if d["name"] == "MHHW")
    minor = floodlevels.get("nws_minor") or floodlevels["nos_minor"]
    return round(minor - mhhw, 2)


async def fetch_predictions(start: datetime, end: datetime, client: httpx.AsyncClient):
    response = await client.get(PREDICTIONS_URL, params=predictions_query(start, end))
    response.raise_for_status()
    return parse_predictions(response.json())


async def fetch_threshold(client: httpx.AsyncClient) -> float:
    try:
        levels = await client.get(f"{METADATA_URL}/floodlevels.json")
        datums = await client.get(f"{METADATA_URL}/datums.json", params={"units": "english"})
        levels.raise_for_status()
        datums.raise_for_status()
        return parse_threshold(levels.json(), datums.json())
    except (httpx.HTTPError, KeyError, StopIteration, TypeError, ValueError):
        return FALLBACK_THRESHOLD_FT_MHHW


async def fetch(at: datetime, client: httpx.AsyncClient | None = None) -> dict:
    """Predicted tide (ft above MHHW) at `at`, the peak over the lookahead, and the threshold."""
    owned = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        predictions = await fetch_predictions(at - timedelta(hours=1), at + LOOKAHEAD + timedelta(hours=1), client)
        threshold = await fetch_threshold(client)
    finally:
        if owned:
            await client.aclose()
    return {"tide_ft_mhhw": round(tide_at(predictions, at), 3),
            "peak_tide_ft_mhhw": round(max_tide(predictions, at, at + LOOKAHEAD), 3),
            "flood_threshold_ft_mhhw": threshold}


def load_hotspots(path: Path = HOTSPOTS_PATH) -> list[dict]:
    return json.loads(path.read_text())["features"]


async def run(db, now: datetime, client: httpx.AsyncClient | None = None,
              hotspots: list[dict] | None = None) -> dict:
    """Register (or refresh the prior of) a flood belief on every curated hotspot."""
    tide = await fetch(now, client)
    hotspots = load_hotspots() if hotspots is None else hotspots
    for feature in hotspots:
        props = feature["properties"]
        await register_hazard(db, f"flood:{props['id']}", "flood", feature["geometry"], {
            "fema_zone": props.get("fema_zone") or "X",
            "tide_ft_mhhw": tide["peak_tide_ft_mhhw"],
            "flood_threshold_ft_mhhw": tide["flood_threshold_ft_mhhw"],
            "severity": props.get("severity", 3),
        }, now)
    return {"registered": len(hotspots), **tide}
