"""Google Routes API client (computeRoutes). Google finds the paths; Mapay scores them."""
from datetime import datetime, timezone

import httpx

from app.config import get_settings

COMPUTE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = ("routes.description,routes.duration,routes.staticDuration,routes.distanceMeters,"
              "routes.polyline.encodedPolyline")
TRAVEL_MODES = {"drive": "DRIVE", "walk": "WALK"}


class RoutesApiError(RuntimeError):
    """The Routes API is unconfigured, unreachable or rejected the request."""


class NoRouteFound(ValueError):
    """The Routes API answered but found no route."""


def decode_polyline(encoded: str) -> list[list[float]]:
    """Google's encoded polyline algorithm → GeoJSON [lng, lat] coordinates."""
    coords, index, lat, lng = [], 0, 0, 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            result, shift = 0, 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lng += deltas[1]
        coords.append([lng / 1e5, lat / 1e5])
    return coords


def _seconds(duration: str | None) -> int:
    # Routes API durations are strings like "2460s".
    return round(float(duration.rstrip("s"))) if duration else 0


def _waypoint(point, via: bool = False) -> dict:
    lat, lng = point
    waypoint = {"location": {"latLng": {"latitude": lat, "longitude": lng}}}
    if via:
        waypoint["via"] = True
    return waypoint


def build_request(origin, destination, depart_at: datetime | None = None, avoid_tolls: bool = False,
                  avoid_highways: bool = False, mode: str = "drive", intermediates=(),
                  now: datetime | None = None) -> dict:
    """computeRoutes body. `intermediates` are (lat, lng) pass-through `via` points, or
    (lat, lng, False) for a real stop. Google returns no alternatives when any are set, so
    alternatives are only requested without them."""
    body = {
        "origin": _waypoint(origin),
        "destination": _waypoint(destination),
        "travelMode": TRAVEL_MODES[mode],
        "computeAlternativeRoutes": not intermediates,
        "polylineEncoding": "ENCODED_POLYLINE",
    }
    if intermediates:
        body["intermediates"] = [_waypoint(p[:2], via=p[2] if len(p) > 2 else True) for p in intermediates]
    if mode == "drive":
        # routingPreference is only valid for DRIVE; route modifiers only matter there.
        body["routingPreference"] = "TRAFFIC_AWARE_OPTIMAL"
        body["routeModifiers"] = {"avoidTolls": avoid_tolls, "avoidHighways": avoid_highways}
    now = now or datetime.now(timezone.utc)
    # Google rejects departure times in the past; leaving it out means "now".
    if depart_at is not None and depart_at.tzinfo is not None and depart_at > now:
        body["departureTime"] = depart_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return body


def parse_routes(payload: dict) -> list[dict]:
    alternatives = []
    for route in payload.get("routes", []):
        encoded = route.get("polyline", {}).get("encodedPolyline")
        if not encoded:
            continue
        duration = _seconds(route.get("duration"))
        description = route.get("description")
        alternatives.append({
            "summary": f"via {description}" if description else "",
            "route_geojson": {"type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "LineString", "coordinates": decode_polyline(encoded)}}]},
            "duration_s": duration,
            "static_duration_s": _seconds(route.get("staticDuration")) or duration,
            "distance_m": int(route.get("distanceMeters", 0)),
        })
    return alternatives


async def compute_routes(origin, destination, depart_at: datetime | None = None, avoid_tolls: bool = False,
                         avoid_highways: bool = False, mode: str = "drive", intermediates=(),
                         client: httpx.AsyncClient | None = None) -> list[dict]:
    """Up to 3 alternatives (1 when `intermediates` are set), Google's recommended route first."""
    key = get_settings().google_maps_api_key
    if not key:
        raise RoutesApiError("GOOGLE_MAPS_API_KEY is not set")
    body = build_request(origin, destination, depart_at, avoid_tolls, avoid_highways, mode, intermediates)
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK}
    owned = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        response = await client.post(COMPUTE_ROUTES_URL, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise RoutesApiError(f"Routes API request failed: {exc}") from exc
    finally:
        if owned:
            await client.aclose()
    if response.status_code != 200:
        raise RoutesApiError(f"Routes API returned HTTP {response.status_code}: {response.text[:300]}")
    alternatives = parse_routes(response.json())
    if not alternatives:
        raise NoRouteFound("No route found")
    return alternatives
