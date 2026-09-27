"""POST /customize: prompt → Gemini constraints → Mapay's router → old vs new route + explanation.

Request (frontend/public/mocks/README.md): {prompt, routine_id, leg} for a routine leg, or
{prompt, origin: {lat, lng}, destination: {lat, lng}}. Response: customize.json. Gemini only
turns the prompt into constraints and explains the result; stops come from Places Text Search
biased to the current route, roads from OpenStreetMap (Overpass), and the route choice from
routing/scoring.py + detour.py.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, model_validator
from shapely.geometry import LineString, MultiLineString, Point

from app.agents.customize import explain, extract_constraints
from app.config import get_settings
from app.db.mongo import get_db
from app.routers.neighborhoods import search
from app.routing.deeplinks import deep_links
from app.routing.detour import neighborhood_name, plan_detour
from app.routing.engine import route_alternatives
from app.routing.google_routes import NoRouteFound, RoutesApiError, compute_routes
from app.routing.pre_route import current_hazards, leg_endpoints
from app.routing.scoring import avoid_areas_for, corridor_for, merge_preferences, rank

log = logging.getLogger(__name__)
router = APIRouter(prefix="/customize", tags=["customize"])

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
# The public Overpass servers are often busy (504/429): try a mirror before giving up.
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter")
USER_AGENT = "MAPAY/0.1 (https://github.com/TomasPessagno/mapay)"
MIAMI_DADE_BBOX = (25.13, -80.87, 25.98, -80.10)  # south, west, north, east (Overpass order)
MAX_STOPS = 3
STOP_MAX_OFF_ROUTE_DEG = 0.03  # ~3 km: further than this isn't "on the way"
_road_cache: dict[str, object] = {}


class LatLngBody(BaseModel):
    lat: float
    lng: float


class CustomizeRequest(BaseModel):
    prompt: str
    routine_id: str | None = None
    leg: int | None = None
    origin: LatLngBody | None = None
    destination: LatLngBody | None = None
    depart_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self):
        if not self.prompt.strip():
            raise ValueError("prompt is empty")
        if self.routine_id is None and (self.origin is None or self.destination is None):
            raise ValueError("send routine_id + leg, or origin and destination")
        return self


# ---- resolvers ----
def match_neighborhoods(names: list[str]) -> tuple[list[str], list[str]]:
    """Names → neighbourhood ids (exact name/id first, then a unique substring). Returns (ids, unmatched)."""
    ids, unmatched = [], []
    for name in names:
        needle = name.strip().lower()
        candidates = search(needle)
        exact = [n for n in candidates if n["name"].lower() == needle or n["id"] == needle]
        chosen = exact or (candidates if len(candidates) == 1 else [])
        if chosen:
            ids.append(chosen[0]["id"])
        else:
            unmatched.append(name)
    return list(dict.fromkeys(ids)), unmatched


def overpass_road_query(road: str) -> str:
    south, west, north, east = MIAMI_DADE_BBOX
    number = re.search(r"\d+", road)
    if number:  # "SR 826", "I-95", "US 1": match the ref number on major roads
        selector = f'way[highway~"^(motorway|trunk|primary)(_link)?$"][ref~"(^|[ ;])({number.group()})($|[ ;])"]'
    else:  # "Palmetto Expressway", "Biscayne Boulevard"
        words = re.sub(r"^the\s+", "", road.strip(), flags=re.IGNORECASE)
        words = re.sub(r"[^A-Za-z0-9' .-]", "", words)  # plain name characters only: no regex syntax
        selector = f'way[highway][name~"{words}",i]'
    return f"[out:json][timeout:25];{selector}({south},{west},{north},{east});out geom;"


def parse_road(payload: dict):
    lines = [LineString([(p["lon"], p["lat"]) for p in way["geometry"]])
             for way in payload.get("elements", []) if len(way.get("geometry") or []) >= 2]
    return MultiLineString(lines) if lines else None


async def resolve_road(road: str, client: httpx.AsyncClient):
    key = road.lower().strip()
    if key not in _road_cache:
        error = None
        for url in OVERPASS_URLS:
            try:
                response = await client.post(url, data={"data": overpass_road_query(road)},
                                             headers={"User-Agent": USER_AGENT}, timeout=12)
                response.raise_for_status()
                _road_cache[key] = parse_road(response.json())
                break
            except httpx.HTTPError as exc:
                error = exc
        else:
            raise error
    return _road_cache[key]


async def resolve_stop(query: str, route_geojson: dict, client: httpx.AsyncClient) -> dict | None:
    """The Places Text Search result closest to the current route, within ~3 km of it."""
    line, _ = corridor_for(route_geojson)
    west, south, east, north = line.bounds
    pad = 0.02
    response = await client.post(PLACES_SEARCH_URL, json={
        "textQuery": query, "maxResultCount": 10,
        "locationBias": {"rectangle": {"low": {"latitude": south - pad, "longitude": west - pad},
                                       "high": {"latitude": north + pad, "longitude": east + pad}}}},
        headers={"X-Goog-Api-Key": get_settings().google_maps_api_key,
                 "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.formattedAddress"})
    response.raise_for_status()
    best = None
    for place in response.json().get("places", []):
        lat, lng = place["location"]["latitude"], place["location"]["longitude"]
        off = line.distance(Point(lng, lat))
        if off <= STOP_MAX_OFF_ROUTE_DEG and (best is None or off < best[0]):
            best = (off, {"name": place.get("displayName", {}).get("text") or query, "place_id": place["id"],
                          "address": place.get("formattedAddress"),
                          "location": {"type": "Point", "coordinates": [lng, lat]}})
    return best[1] if best else None


def local_departure(clock: str, base: datetime | None, tz: str, now: datetime) -> datetime:
    """HH:MM today in the routine's timezone (tomorrow if that already passed)."""
    zone = ZoneInfo(tz)
    day = (base or now).astimezone(zone)
    hour, minute = map(int, clock.split(":"))
    candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if base is None and candidate < now.astimezone(zone):
        candidate += timedelta(days=1)
    return candidate


def summarize(route: dict, stops: list[dict] | None = None) -> dict:
    out = {"summary": route.get("summary") or "", "duration_s": route["duration_s"],
           "distance_m": route["distance_m"], "route_geojson": route["route_geojson"]}
    if stops is not None:
        out["stops"] = [{k: s[k] for k in ("name", "place_id", "location")} for s in stops]
        out["hazards_on_route"] = route.get("hazards_on_route", [])
        if stops and out["summary"]:
            out["summary"] += ", stopping at " + ", ".join(s["name"] for s in stops)
    return out


def order_along(line, points: list[tuple]) -> list[tuple]:
    """Intermediates in the order the route reaches them."""
    return sorted(points, key=lambda p: line.project(Point(p[1], p[0])))


# ---- endpoint ----
@router.post("")
async def customize(req: CustomizeRequest, x_device_id: str | None = Header(default=None)):
    db = get_db()
    device_id = (x_device_id or "").strip()
    now = datetime.now(timezone.utc)
    user = await db.users.find_one({"_id": device_id}) if device_id else None
    routine, tz, names = None, "America/New_York", {}
    if req.routine_id:
        if not device_id:
            raise HTTPException(401, "X-Device-Id is required with routine_id")
        routine = await db.routines.find_one({"_id": req.routine_id, "user_id": device_id})
        if routine is None:
            raise HTTPException(404, "Routine not found")
        legs = routine.get("legs", [])
        leg_index = req.leg or 0
        if not 0 <= leg_index < len(legs):
            raise HTTPException(422, f"Routine has no leg {leg_index}")
        try:
            origin, destination = await leg_endpoints(db, routine, legs[leg_index])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        tz = routine.get("tz") or tz
        for key in ("from_place", "to_place"):
            place = await db.places.find_one({"_id": legs[leg_index][key]}) or {}
            names[key] = place.get("name")
    else:
        origin, destination = (req.origin.lat, req.origin.lng), (req.destination.lat, req.destination.lng)

    base = merge_preferences((user or {}).get("preferences"), (routine or {}).get("preferences"))
    constraints, source = await extract_constraints(req.prompt, {
        "from": names.get("from_place"), "to": names.get("to_place"), "timezone": tz,
        "now_local": now.astimezone(ZoneInfo(tz)).strftime("%a %H:%M")})

    unmet: list[str] = []
    prefs = merge_preferences(base, {"avoid_tolls": constraints["avoid_tolls"],
                                     "avoid_highways": constraints["avoid_highways"]})
    prefs["categories"] = {**prefs["categories"], **{c: "avoid" for c in constraints["avoid_categories"]}}
    neighborhood_ids, unmatched = match_neighborhoods(constraints["avoid_neighborhoods"])
    prefs["avoid_neighborhoods"] = list(dict.fromkeys([*prefs["avoid_neighborhoods"], *neighborhood_ids]))
    unmet += [f"no neighbourhood called {n}" for n in unmatched]
    if constraints["arrive_by"]:
        unmet.append(f"arrive by {constraints['arrive_by']} (not supported yet)")
    mode = constraints["travel_mode"] or "drive"
    depart_at = req.depart_at
    if constraints["depart_at"]:
        depart_at = local_departure(constraints["depart_at"], req.depart_at, tz, now)

    async with httpx.AsyncClient(timeout=25) as client:
        roads = []
        for road in constraints["avoid_roads"]:
            try:
                geometry = await resolve_road(road, client)
            except httpx.HTTPError:
                log.warning("Overpass lookup failed for %s", road, exc_info=True)
                geometry = None
            if geometry is None:
                unmet.append(f"couldn't find {road}")
            else:
                roads.append({"id": f"road:{road}", "label": road, "kind": "road", "geometry": geometry})
        hazards = await current_hazards(db, now)
        try:
            # Old route: what Mapay would pick without the prompt.
            old_alternatives = await route_alternatives(origin, destination, req.depart_at, base["avoid_tolls"],
                                                        base["avoid_highways"], "drive")
            old = rank(old_alternatives, hazards, base)[0]
            stops = []
            for stop in constraints["add_stops"][:MAX_STOPS]:
                try:
                    found = await resolve_stop(stop["query"], old["route_geojson"], client)
                except httpx.HTTPError:
                    log.warning("Places lookup failed for %s", stop["query"], exc_info=True)
                    found = None
                if found:
                    stops.append(found)
                else:
                    unmet.append(f"no {stop['query']} near the route")
            areas = avoid_areas_for(prefs, roads)
            old_line, _ = corridor_for(old["route_geojson"])
            stop_points = [(s["location"]["coordinates"][1], s["location"]["coordinates"][0], False) for s in stops]

            async def with_intermediates(vias):
                points = order_along(old_line, [*stop_points, *[(lat, lng, True) for lat, lng in vias]])
                return await compute_routes(origin, destination, depart_at=depart_at,
                                            avoid_tolls=prefs["avoid_tolls"], avoid_highways=prefs["avoid_highways"],
                                            mode=mode, intermediates=points)

            if stops:  # stops mean a single route (Routes API gives no alternatives with intermediates)
                candidates = await with_intermediates([])
            else:
                candidates = await route_alternatives(origin, destination, depart_at, prefs["avoid_tolls"],
                                                      prefs["avoid_highways"], mode)
            best = rank(candidates, hazards, prefs, areas)[0]
            plan = await plan_detour(best, hazards, prefs, with_intermediates, areas)
        except NoRouteFound as exc:
            raise HTTPException(422, "No route found") from exc
        except RoutesApiError as exc:
            raise HTTPException(502, str(exc)) from exc

    new = plan["route"]
    waypoints = [(lat, lng) for lat, lng, _ in order_along(
        old_line, [*stop_points, *[(lat, lng, True) for lat, lng in plan["waypoints"]]])]
    avoided = [neighborhood_name(i) for i in neighborhood_ids] + [r["label"] for r in roads] + \
              [f"{c} hazards" for c in constraints["avoid_categories"]]
    unmet += [f"{label} could not be avoided" for label in plan["unavoidable"]]
    facts = {"request": req.prompt, "old_route": old.get("summary"), "new_route": new.get("summary"),
             "minutes_delta": round((new["duration_s"] - old["duration_s"]) / 60),
             "stops": [s["name"] + (f" ({s['address']})" if s.get("address") else "") for s in stops],
             "avoided": avoided, "hazards_on_new_route": [h["title"] for h in new.get("hazards_on_route", [])[:3]],
             "unmet": unmet}
    return {
        "prompt": req.prompt,
        "constraints": constraints,
        "old_route": summarize(old),
        "new_route": summarize(new, stops),
        "explanation": await explain(facts),
        "deep_links": deep_links(origin, destination, waypoints, mode),
        "waypoints": waypoints,
        "depart_at": depart_at.isoformat() if depart_at else None,
        "unmet": unmet,
        "constraints_source": source,
    }
