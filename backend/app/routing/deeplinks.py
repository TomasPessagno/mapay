"""Hand a Mapay route to a navigation app (AGENTS.md › Routing, step 4).

Only Google Maps keeps Mapay's shaping, through up to 3 waypoints (the mobile app's limit);
Apple Maps and Waze get origin → destination only. Points are (lat, lng).
"""
from urllib.parse import quote

MAX_WAYPOINTS = 3
TRAVEL_MODES = {"drive": "driving", "walk": "walking"}


def _point(point) -> str:
    lat, lng = point
    return f"{lat:.4f},{lng:.4f}"


def google_maps(origin, destination, waypoints=(), mode: str = "drive") -> str:
    url = (f"https://www.google.com/maps/dir/?api=1&origin={_point(origin)}&destination={_point(destination)}"
           f"&travelmode={TRAVEL_MODES.get(mode, 'driving')}")
    if waypoints:
        url += "&waypoints=" + quote("|".join(_point(p) for p in list(waypoints)[:MAX_WAYPOINTS]), safe=",")
    return url


def apple_maps(origin, destination, mode: str = "drive") -> str:
    return (f"https://maps.apple.com/?saddr={_point(origin)}&daddr={_point(destination)}"
            f"&dirflg={'w' if mode == 'walk' else 'd'}")


def waze(destination) -> str:
    return f"https://waze.com/ul?ll={_point(destination)}&navigate=yes"


def deep_links(origin, destination, waypoints=(), mode: str = "drive") -> dict[str, str]:
    return {"google_maps": google_maps(origin, destination, waypoints, mode),
            "apple_maps": apple_maps(origin, destination, mode),
            "waze": waze(destination)}
