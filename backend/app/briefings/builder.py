"""Heads-up briefings: one `/routines/upcoming` item per leg occurrence (routines-upcoming.json).

Each leg is routed once per request (Routes API + A6 scoring + A7 detour, cached 15 min) and the
result is shared by that leg's occurrences. A leg whose route can't be computed still gets its
item (times + links), so the phone can schedule its notifications anyway.
"""
import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import quote

from shapely.geometry import shape

from app.config import get_settings
from app.routers.layers import PREDICTIVE_SOURCES, source_kind
from app.routing.deeplinks import google_maps
from app.routing.detour import plan_detour
from app.routing.engine import route_alternatives
from app.routing.google_routes import (
    NoRouteFound,
    RoutesApiError,
    compute_routes,
    encode_polyline,
)
from app.routing.scoring import merge_preferences, rank
from app.scheduling.best_time import best_departure
from app.scheduling.occurrences import Occurrence

log = logging.getLogger(__name__)

ROUTE_TTL_S = 15 * 60  # AGENTS.md: routes are cached for 15 min
TOP_HAZARDS, TOP_HAZARDS_COMPACT = 3, 2
STATIC_MAPS_HOST = "https://maps.googleapis.com"
# Marker colours: frontend/src/map/legend.ts (light palette).
MARKER_COLORS = {"flood": "0x32ADE6", "weather": "0x5856D6", "construction": "0xFF9500", "closure": "0x1C1C1E",
                 "congestion": "0xFF3B30", "no_sidewalk": "0xAF52DE", "pothole": "0xA2845E", "incident": "0xFF2D55",
                 "event": "0x34C759"}
_route_cache: dict[str, tuple[float, dict]] = {}


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def sign_static_map(path_and_query: str, secret: str) -> str:
    """Google URL signing: HMAC-SHA1 over path + query with the URL-safe base64 secret."""
    key = base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))
    digest = hmac.new(key, path_and_query.encode(), hashlib.sha1).digest()
    return base64.urlsafe_b64encode(digest).decode()


def static_map_url(route_geojson: dict, hazards: list[dict]) -> str | None:
    """Signed Static Maps image: the route in Mapay blue + a marker per top hazard. None without a
    signing secret (an unsigned URL would hand out the server key)."""
    settings = get_settings()
    if not settings.google_maps_api_key or not settings.google_maps_signing_secret:
        return None
    line = shape(route_geojson["features"][0]["geometry"]).simplify(0.0003)
    parts = ["size=600x300", "scale=2",
             "path=" + quote(f"color:0x007AFFff|weight:5|enc:{encode_polyline(list(line.coords))}", safe=":,")]
    for hazard in hazards:
        point = shape(hazard["geometry"]).representative_point()
        color = MARKER_COLORS.get(hazard["hazard_type"], "0xFF2D55")
        parts.append("markers=" + quote(f"size:mid|color:{color}|{point.y:.5f},{point.x:.5f}", safe=":,"))
    path_and_query = "/maps/api/staticmap?" + "&".join(parts) + f"&key={settings.google_maps_api_key}"
    if len(path_and_query) > 8000:  # Static Maps URL limit
        return None
    return f"{STATIC_MAPS_HOST}{path_and_query}&signature={sign_static_map(path_and_query, settings.google_maps_signing_secret)}"


def hazard_status(doc: dict) -> str:
    return "predicted" if source_kind(doc["hazard_id"]) in PREDICTIVE_SOURCES and not doc.get("evidence") else "observed"


async def route_leg(origin, destination, departure, preferences: dict, hazards) -> dict:
    """{route, waypoints} for one leg, cached for 15 min per endpoints + preferences."""
    key = json.dumps([origin, destination, preferences], sort_keys=True, default=str)
    cached = _route_cache.get(key)
    if cached and time.monotonic() - cached[0] < ROUTE_TTL_S:
        return cached[1]
    alternatives = await route_alternatives(origin, destination, departure, preferences["avoid_tolls"],
                                            preferences["avoid_highways"], "drive")
    best = rank(alternatives, hazards, preferences)[0]

    async def with_vias(vias):
        return await compute_routes(origin, destination, depart_at=departure, avoid_tolls=preferences["avoid_tolls"],
                                    avoid_highways=preferences["avoid_highways"], intermediates=vias)

    plan = await plan_detour(best, hazards, preferences, with_vias)
    result = {"route": plan["route"], "waypoints": plan["waypoints"]}
    _route_cache[key] = (time.monotonic(), result)
    return result


async def build_items(db, occurrences: list[Occurrence], routines: dict[str, dict], user: dict | None,
                      hazards: list[dict], compact: bool = False, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    place_ids = {leg[k] for r in routines.values() for leg in r.get("legs", []) for k in ("from_place", "to_place")}
    places = {p["_id"]: p for p in await db.places.find({"_id": {"$in": sorted(place_ids)}}).to_list(length=None)}
    by_id = {h["hazard_id"]: h for h in hazards}
    legs_routed: dict[tuple[str, int], dict | None] = {}
    leg_preferences: dict[tuple[str, int], dict] = {}
    items = []
    for occ in occurrences:
        routine = routines[occ.routine_id]
        leg = routine["legs"][occ.leg]
        start, end = places.get(leg["from_place"]), places.get(leg["to_place"])
        if not start or not end:
            log.warning("Routine %s leg %s points at a missing place", occ.routine_id, occ.leg)
            continue
        origin = tuple(reversed(start["location"]["coordinates"]))
        destination = tuple(reversed(end["location"]["coordinates"]))
        key = (occ.routine_id, occ.leg)
        if key not in legs_routed:
            preferences = merge_preferences((user or {}).get("preferences"), routine.get("preferences"))
            leg_preferences[key] = preferences
            try:
                legs_routed[key] = await route_leg(origin, destination, occ.departure_at, preferences, hazards)
            except (NoRouteFound, RoutesApiError) as exc:
                log.warning("Couldn't route %s leg %s: %s", occ.routine_id, occ.leg, exc)
                legs_routed[key] = None
        routed = legs_routed[key]
        route = (routed or {}).get("route") or {}
        waypoints = (routed or {}).get("waypoints") or []
        top = route.get("hazards_on_route", [])[:TOP_HAZARDS_COMPACT if compact else TOP_HAZARDS]
        top = [{**h, "status": hazard_status(by_id[h["hazard_id"]]) if h["hazard_id"] in by_id else "observed"}
               for h in top]
        query = f"routine={quote(occ.routine_id)}&leg={occ.leg}"
        item = {
            "routine_id": occ.routine_id,
            "routine_name": routine.get("name") or "Routine",
            "leg": occ.leg,
            "from": {"place_id": start["_id"], "name": start.get("name")},
            "to": {"place_id": end["_id"], "name": end.get("name")},
            "local_date": occ.local_date.isoformat(),
            "departure_at": _iso(occ.departure_at),
            "heads_up_at": _iso(occ.heads_up_at),
            "window": {"start": _iso(occ.window[0]), "end": _iso(occ.window[1])} if occ.window else None,
            "best_departure_at": None,
            "best_saving_s": None,
            "duration_s": route.get("duration_s", 0),
            "static_duration_s": route.get("static_duration_s", 0),
            "summary": route.get("summary", ""),
            "top_hazards": top,
            "image_url": None if compact or not route else static_map_url(
                route["route_geojson"], [by_id[h["hazard_id"]] for h in top if h["hazard_id"] in by_id]),
            "deep_links": {"start": f"mapay://start?{query}", "customize": f"mapay://customize?{query}",
                           "google_maps": google_maps(origin, destination, waypoints)},
        }
        if occ.window and routed is not None and not occ.demo:
            best = await best_departure(origin, destination, occ.window, leg_preferences[key], hazards, now)
            if best:
                item["best_departure_at"] = _iso(best["best_departure_at"].astimezone(occ.departure_at.tzinfo))
                item["best_saving_s"] = best["saving_s"]
        if occ.demo:
            item["demo"] = True
        if routed is None:
            item["route_error"] = "Route unavailable right now"
        items.append(item)
    return items
