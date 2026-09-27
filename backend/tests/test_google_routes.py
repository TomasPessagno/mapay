import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import routes
from app.routing.google_routes import (
    COMPUTE_ROUTES_URL,
    FIELD_MASK,
    NoRouteFound,
    RoutesApiError,
    build_request,
    compute_routes,
    decode_polyline,
    parse_routes,
)

# Google's documented example: (38.5, -120.2), (40.7, -120.95), (43.252, -126.453)
EXAMPLE_POLYLINE = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
MMC, BBC = (25.7574, -80.3733), (25.9104, -80.1392)


def payload(*routes_):
    return {"routes": [{
        "description": d, "duration": f"{dur}s", "staticDuration": f"{static}s", "distanceMeters": dist,
        "polyline": {"encodedPolyline": EXAMPLE_POLYLINE},
        "legs": [{"steps": [{
            "navigationInstruction": {"instructions": "Turn right onto SW 8th St", "maneuver": "TURN_RIGHT"},
            "distanceMeters": dist, "staticDuration": f"{static}s",
            "polyline": {"encodedPolyline": EXAMPLE_POLYLINE},
        }]}],
    } for d, dur, static, dist in routes_]}


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def settings(key="server-key"):
    return patch("app.routing.google_routes.get_settings", return_value=SimpleNamespace(google_maps_api_key=key))


class PolylineTests(unittest.TestCase):
    def test_decodes_google_example_to_lng_lat(self):
        self.assertEqual(decode_polyline(EXAMPLE_POLYLINE),
                         [[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]])

    def test_empty(self):
        self.assertEqual(decode_polyline(""), [])

    def test_parse_navigation_steps_without_network(self):
        parsed = parse_routes({"routes": [{
            "duration": "120s",
            "distanceMeters": 900,
            "polyline": {"encodedPolyline": EXAMPLE_POLYLINE},
            "legs": [{"steps": [{
                "navigationInstruction": {"instructions": "Turn right onto SW 8th St", "maneuver": "TURN_RIGHT"},
                "distanceMeters": 300,
                "staticDuration": "45s",
                "polyline": {"encodedPolyline": EXAMPLE_POLYLINE},
            }, {
                "navigationInstruction": {"instructions": "Merge onto SR-826 N", "maneuver": "MERGE"},
                "distanceMeters": 600,
                "staticDuration": "75s",
                "polyline": {"encodedPolyline": ""},
            }]}],
        }]})

        self.assertEqual(parsed[0]["steps"], [
            {"instruction": "Turn right onto SW 8th St", "maneuver": "TURN_RIGHT", "distance_m": 300,
             "duration_s": 45, "polyline": EXAMPLE_POLYLINE},
            {"instruction": "Merge onto SR-826 N", "maneuver": "MERGE", "distance_m": 600,
             "duration_s": 75, "polyline": ""},
        ])


class BuildRequestTests(unittest.TestCase):
    now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)

    def test_drive_request_has_alternatives_traffic_and_modifiers(self):
        depart = datetime(2026, 9, 28, 9, 30, tzinfo=timezone(timedelta(hours=-4)))
        body = build_request(MMC, BBC, depart, avoid_tolls=True, avoid_highways=False, now=self.now)
        self.assertTrue(body["computeAlternativeRoutes"])
        self.assertEqual(body["routingPreference"], "TRAFFIC_AWARE_OPTIMAL")
        self.assertEqual(body["travelMode"], "DRIVE")
        self.assertEqual(body["routeModifiers"], {"avoidTolls": True, "avoidHighways": False})
        self.assertEqual(body["departureTime"], "2026-09-28T13:30:00Z")
        self.assertEqual(body["origin"]["location"]["latLng"], {"latitude": 25.7574, "longitude": -80.3733})

    def test_past_or_naive_departure_is_left_out(self):
        self.assertNotIn("departureTime", build_request(MMC, BBC, self.now - timedelta(minutes=1), now=self.now))
        self.assertNotIn("departureTime", build_request(MMC, BBC, datetime(2026, 9, 29, 9), now=self.now))  # noqa: DTZ001

    def test_intermediates_turn_off_alternatives(self):
        body = build_request(MMC, BBC, intermediates=[(25.8, -80.3)], now=self.now)
        self.assertFalse(body["computeAlternativeRoutes"])
        self.assertEqual(body["intermediates"][0]["via"], True)

    def test_walk_has_no_routing_preference(self):
        body = build_request(MMC, BBC, mode="walk", now=self.now)
        self.assertEqual(body["travelMode"], "WALK")
        self.assertNotIn("routingPreference", body)


class ComputeRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_key_and_field_mask_and_parses_alternatives(self):
        seen = {}

        def handler(request):
            seen["request"] = request
            return httpx.Response(200, json=payload(("SR-826 and I-95", 2460, 1980, 31800),
                                                    ("Biscayne Blvd", 2700, 2100, 29900)))

        with settings():
            alts = await compute_routes(MMC, BBC, client=mock_client(handler))
        request = seen["request"]
        self.assertEqual(str(request.url), COMPUTE_ROUTES_URL)
        self.assertEqual(request.headers["X-Goog-Api-Key"], "server-key")
        self.assertIn("routes.polyline.encodedPolyline", request.headers["X-Goog-FieldMask"])
        for path in ("routes.legs.steps.navigationInstruction", "routes.legs.steps.distanceMeters",
                     "routes.legs.steps.staticDuration", "routes.legs.steps.polyline.encodedPolyline"):
            self.assertIn(path, FIELD_MASK)
        self.assertTrue(json.loads(request.content)["computeAlternativeRoutes"])
        self.assertEqual(len(alts), 2)
        self.assertEqual(alts[0]["summary"], "via SR-826 and I-95")
        self.assertEqual((alts[0]["duration_s"], alts[0]["static_duration_s"], alts[0]["distance_m"]),
                         (2460, 1980, 31800))
        self.assertEqual(alts[0]["route_geojson"]["features"][0]["geometry"]["coordinates"][0], [-120.2, 38.5])

    async def test_missing_key(self):
        with settings(""), self.assertRaises(RoutesApiError):
            await compute_routes(MMC, BBC, client=mock_client(lambda r: httpx.Response(200)))

    async def test_http_error(self):
        with settings(), self.assertRaises(RoutesApiError):
            await compute_routes(MMC, BBC, client=mock_client(lambda r: httpx.Response(403, text="denied")))

    async def test_no_routes(self):
        with settings(), self.assertRaises(NoRouteFound):
            await compute_routes(MMC, BBC, client=mock_client(lambda r: httpx.Response(200, json={})))


class FakeCursor:
    async def to_list(self, length=None):
        return []


class FakeRoutines:
    def __init__(self, docs):
        self.docs = docs

    async def find_one(self, query):
        return next((d for d in self.docs if all(d.get(k) == v for k, v in query.items())), None)

    async def update_one(self, query, update):
        doc = await self.find_one(query)
        for path, value in update["$set"].items():  # supports "legs.<i>.route_state"
            target, *keys, last = [doc, *path.split(".")]
            for key in keys:
                target = target[int(key)] if key.isdigit() else target[key]
            target[last] = value
        return SimpleNamespace(matched_count=1)


class RouteEndpointTests(unittest.TestCase):
    def setUp(self):
        self.routines = FakeRoutines([{"_id": "r1", "user_id": "dev", "legs": [
            {"from_place": "mmc", "to_place": "bbc", "when": {"kind": "at", "time": "09:30"}}]}])
        places = {"mmc": {"location": {"coordinates": [MMC[1], MMC[0]]}},
                  "bbc": {"location": {"coordinates": [BBC[1], BBC[0]]}}}

        async def find_place(query):
            return places.get(query["_id"])

        async def no_user(query):
            return None

        self.db = SimpleNamespace(intel_cache=SimpleNamespace(find=lambda q: FakeCursor()), routines=self.routines,
                                  places=SimpleNamespace(find_one=find_place), users=SimpleNamespace(find_one=no_user))
        app = FastAPI()
        app.include_router(routes.router)
        self.client = TestClient(app)

    def post(self, body, handler, headers=None):
        real_client = httpx.AsyncClient
        with settings(), patch("app.routers.routes.get_db", return_value=self.db), \
             patch("app.routing.google_routes.httpx.AsyncClient",
                   lambda **kw: real_client(transport=httpx.MockTransport(handler))):
            return self.client.post("/route", json=body, headers=headers or {})

    def test_returns_mock_shape_without_a_graph(self):
        ok = lambda r: httpx.Response(200, json=payload(("SR-826", 2460, 1980, 31800), ("US-1", 2700, 2100, 29900)))
        response = self.post({"origin": list(MMC), "destination": list(BBC)}, ok)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        for key in ("route_geojson", "baseline_geojson", "alternatives", "waypoints", "hazards_on_route",
                    "deep_links", "briefing", "depart_at"):
            self.assertIn(key, body)
        self.assertEqual(len(body["alternatives"]), 2)
        self.assertEqual(body["route_geojson"], body["alternatives"][0]["route_geojson"])
        self.assertEqual([a["recommended"] for a in body["alternatives"]], [True, False])
        self.assertEqual(body["alternatives"][1]["static_duration_s"], 2100)
        self.assertEqual(body["alternatives"][0]["steps"][0]["instruction"], "Turn right onto SW 8th St")
        self.assertEqual(body["alternatives"][0]["steps"][0]["maneuver"], "TURN_RIGHT")

    def test_routine_route_saves_route_state(self):
        ok = lambda r: httpx.Response(200, json=payload(("SR-826", 2460, 1980, 31800)))
        body = {"origin": list(MMC), "destination": list(BBC), "routine_id": "r1", "leg": 0,
                "depart_at": "2099-09-28T09:30:00-04:00"}
        self.assertEqual(self.post(body, ok).status_code, 401)  # writing to a routine needs the device id
        self.assertEqual(self.post(body, ok, {"X-Device-Id": "other"}).status_code, 404)
        self.assertEqual(self.post({**body, "leg": 3}, ok, {"X-Device-Id": "dev"}).status_code, 422)
        self.assertEqual(self.post({**body, "destination": [25.0, -80.0]}, ok, {"X-Device-Id": "dev"}).status_code, 422)
        response = self.post(body, ok, {"X-Device-Id": "dev"})
        self.assertEqual(response.status_code, 200, response.text)
        state = self.routines.docs[0]["legs"][0]["route_state"]
        self.assertEqual(state["route_geojson"], response.json()["route_geojson"])
        self.assertEqual(state["beliefs"], {})

    def test_upstream_failure_is_502_and_no_route_is_422(self):
        self.assertEqual(self.post({"origin": list(MMC), "destination": list(BBC)},
                                   lambda r: httpx.Response(500)).status_code, 502)
        self.assertEqual(self.post({"origin": list(MMC), "destination": list(BBC)},
                                   lambda r: httpx.Response(200, json={"routes": []})).status_code, 422)
