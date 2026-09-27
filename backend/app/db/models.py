import re
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

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
    leg: int | None = None  # with routine_id: which leg's route_state to save
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


# ---- routines (AGENTS.md › Routines / MongoDB schema) ----
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _clock(value: str | None) -> str | None:
    if value is not None and not _CLOCK.match(value):
        raise ValueError(f"{value!r} is not a HH:MM time")
    return value


class RoutineRepeat(BaseModel):
    kind: Literal["daily", "weekly", "custom"] = "daily"
    weekday: Weekday | None = None  # weekly
    weekdays: list[Weekday] | None = None  # custom

    @model_validator(mode="after")
    def _check(self):
        if self.kind == "weekly" and self.weekday is None:
            raise ValueError("weekly repeat needs a weekday")
        if self.kind == "custom" and not self.weekdays:
            raise ValueError("custom repeat needs at least one weekday")
        return self


class RoutineWhen(BaseModel):
    kind: Literal["at", "window"]
    time: str | None = None  # at
    start: str | None = None  # window
    end: str | None = None

    @model_validator(mode="after")
    def _check(self):
        for value in (self.time, self.start, self.end):
            _clock(value)
        if self.kind == "at" and self.time is None:
            raise ValueError("an 'at' leg needs a time")
        if self.kind == "window" and not (self.start and self.end and self.start < self.end):
            raise ValueError("a 'window' leg needs start < end")
        return self


class RoutineLeg(BaseModel):
    from_place: str
    to_place: str
    when: RoutineWhen
    anchor: Literal["depart", "arrive"] = "depart"  # "arrive" is aspirational (AGENTS.md)
    days: list[Weekday] | None = None  # per-leg override of the routine's repeat


class Routine(BaseModel):
    """Client-editable routine. The server owns `user_id` and each leg's `route_state`."""
    id: str | None = Field(default=None, alias="_id")
    name: str = "Routine"
    active: bool = True
    repeat: RoutineRepeat = RoutineRepeat()
    legs: list[RoutineLeg] = []
    tz: str = "America/New_York"
    heads_up_minutes: int = Field(default=30, ge=0, le=240)
    preferences: dict = {}

    @field_validator("tz")
    @classmethod
    def _tz(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value


def leg_days(routine: dict, leg: dict) -> list[str]:
    """Weekdays a leg runs on: its own `days`, else the routine's repeat rule."""
    if leg.get("days"):
        return list(leg["days"])
    repeat = routine.get("repeat") or {"kind": "daily"}
    if repeat["kind"] == "weekly":
        return [repeat["weekday"]]
    if repeat["kind"] == "custom":
        return list(repeat["weekdays"])
    return list(WEEKDAYS)


# ---- places ----
class LatLngIn(BaseModel):
    lat: float
    lng: float


class PlaceIn(BaseModel):
    """`location` is a GeoJSON Point (the mock) or {lat, lng} (what the app's place picker sends)."""
    id: str | None = Field(default=None, alias="_id")
    name: str
    google_place_id: str | None = None
    address: str | None = None
    location: GeoPoint | LatLngIn

    def point(self) -> dict:
        if isinstance(self.location, LatLngIn):
            return {"type": "Point", "coordinates": [self.location.lng, self.location.lat]}
        return self.location.model_dump()


# ---- users.preferences ----
Preference = Literal["avoid", "prefer_avoid", "ignore"]
Category = Literal["flood", "weather", "construction", "closure", "congestion", "no_sidewalk", "pothole",
                   "incident", "event"]


class Preferences(BaseModel):
    categories: dict[Category, Preference] = {}
    avoid_neighborhoods: list[str] = []
    avoid_tolls: bool = False
    avoid_highways: bool = False
    nav_app: Literal["google_maps", "apple_maps", "waze"] = "google_maps"
