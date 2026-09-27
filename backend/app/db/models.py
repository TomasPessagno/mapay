from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

LatLng = tuple[float, float]


class GeoPoint(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]  # [lng, lat]


# ---- routes_cache ----
class RouteRequest(BaseModel):
    origin: LatLng
    destination: LatLng
    depart_at: datetime | None = None
    avoid_tolls: bool = False
    avoid_highways: bool = False
    # Same shape as users.preferences; overrides the user's and the routine's (A6 scoring).
    preferences: dict | None = None
    routine_id: str | None = None
    mode: Literal["drive", "walk"] = "drive"


class RouteAlternative(BaseModel):
    summary: str = ""
    route_geojson: dict
    duration_s: int
    static_duration_s: int
    distance_m: int
    score: float | None = None  # predicted minutes + hazard penalty minutes (routing/scoring.py)
    recommended: bool = False
    hazards_on_route: list[dict] = []
    neighborhoods_crossed: list[str] = []  # avoided neighbourhood ids this route still enters


class RouteResponse(BaseModel):
    """Shape of frontend/public/mocks/route.json."""
    depart_at: datetime | None = None
    route_geojson: dict
    baseline_geojson: dict | None = None
    alternatives: list[RouteAlternative] = []
    waypoints: list[LatLng] = []
    hazards_on_route: list[dict] = []
    deep_links: dict[str, str] = {}
    briefing: str | None = None


# ---- intel_cache ----
class IntelItem(BaseModel):
    id: str = Field(alias="_id")
    type: Literal["news", "police", "satellite_check"]
    location: GeoPoint
    severity: int
    summary: str
    source_url: str
    created_at: datetime
    expires_at: datetime
    log_odds: float = 0.0
    last_updated: datetime | None = None


# ---- hazard_reports ----
class HazardReportIn(BaseModel):
    type: Literal["pothole", "flood", "closure", "other"]
    lat: float
    lng: float
    hazard_id: str | None = None
    cleared: bool = False


class HazardReport(BaseModel):
    id: str = Field(alias="_id")
    type: str
    location: GeoPoint
    reported_at: datetime
    confirmed_count: int = 1


# ---- routines ----
class Routine(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    user_id: str
    origin: LatLng
    destination: LatLng
    days: list[str]
    time_window: tuple[str, str]
    preferences: dict = {}
