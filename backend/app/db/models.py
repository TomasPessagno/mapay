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
    routine_id: str | None = None
    mode: Literal["drive", "walk"] = "drive"


class RouteResponse(BaseModel):
    route_geojson: dict
    baseline_geojson: dict | None = None
    hazards_avoided: list[dict] = []
    briefing: str | None = None
    deep_links: dict[str, str] = {}


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
