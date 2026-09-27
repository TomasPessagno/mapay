import asyncio
import json
import math
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Point, box

from app.routers import routes
from app.routers.neighborhoods import get_polygon
from app.routing import deeplinks
from app.routing.beliefs import log_odds
from app.routing.detour import briefing, plan_detour, via_point
from app.routing.google_routes import NoRouteFound
from app.routing.scoring import HazardIndex, merge_preferences, rank

DEFAULTS = merge_preferences()
MOCK = Path(__file__).resolve().parents[2] / "frontend" / "public" / "mocks" / "route.json"
M_PER_DEG = 111_320


def encode(points):
    """Google's polyline encoding for (lat, lng) points (the inverse of decode_polyline)."""
    out, prev = [], (0, 0)
    for lat, lng in points:
        cur = (round(lat * 1e5), round(lng * 1e5))
        for value, before in zip(cur, prev, strict=True):
            d = value - before
            d = ~(d << 1) if d < 0 else d << 1
            while d >= 0x20:
                out.append(chr((0x20 | (d & 0x1F)) + 63))
                d >>= 5
            out.append(chr(d + 63))
        prev = cur
    return "".join(out)


def alt(coords, minutes, summary=""):
    return {"summary": summary, "duration_s": minutes * 60, "static_duration_s": minutes * 60, "distance_m": 1,
            "route_geojson": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": coords}}]}}


def hazard(hazard_id, kind, lng, lat, p=0.9, severity=5):
    return {"hazard_id": hazard_id, "hazard_type": kind, "severity": severity, "log_odds": log_odds(p),
            "geometry": {"type": "Point", "coordinates": [lng, lat]}, "type": "hazard_belief", "evidence": {}}


STRAIGHT = alt([[-80.30, 25.80], [-80.20, 25.80]], 20, "straight")  # east-west through the hazard
DETOUR = alt([[-80.30, 25.80], [-80.25, 25.81], [-80.20, 25.80]], 24, "detour")  # ~1.1 km north of it
CLOSURE = hazard("here:1", "closure", -80.25, 25.80)


class DeepLinkTests(unittest.TestCase):
    def test_google_matches_the_mock(self):
        mock = json.loads(MOCK.read_text())
        url = deeplinks.google_maps((25.7574, -80.3733), (25.9104, -80.1392), [(25.835, -80.331)])
        self.assertEqual(url, mock["deep_links"]["google_maps"])

    def test_at_most_three_waypoints_joined_by_pipe(self):
        url = deeplinks.google_maps((25.7, -80.3), (25.9, -80.1), [(25.71, -80.3), (25.72, -80.3), (25.73, -80.3),
                                                                     (25.74, -80.3)])
        self.assertTrue(url.endswith("waypoints=25.7100,-80.3000%7C25.7200,-80.3000%7C25.7300,-80.3000"))
        self.assertNotIn("waypoints", deeplinks.google_maps((25.7, -80.3), (25.9, -80.1)))

    def test_apple_waze_and_walking(self):
        links = deeplinks.deep_links((25.7574, -80.3733), (25.9104, -80.1392), [(25.8, -80.3)], mode="walk")
        self.assertIn("travelmode=walking", links["google_maps"])
        self.assertEqual(links["apple_maps"], "https://maps.apple.com/?saddr=25.7574,-80.3733&daddr=25.9104,-80.1392&dirflg=w")
        self.assertEqual(links["waze"], "https://waze.com/ul?ll=25.9104,-80.1392&navigate=yes")
        self.assertNotIn("25.8", links["apple_maps"] + links["waze"])  # origin → destination only


class ViaPointTests(unittest.TestCase):
    def distance_m(self, a, b):
        dy = (a[0] - b[0]) * M_PER_DEG
        dx = (a[1] - b[1]) * M_PER_DEG * math.cos(math.radians(a[0]))
        return math.hypot(dx, dy)

    def test_about_300_m_past_a_point_hazard_perpendicular_to_the_route(self):
        lat, lng = via_point(STRAIGHT["route_geojson"], Point(-80.25, 25.80), HazardIndex([]))
        self.assertAlmostEqual(lng, -80.25, places=3)  # perpendicular to an east-west road
        self.assertTrue(300 <= self.distance_m((lat, lng), (25.80, -80.25)) <= 400)

    def test_quieter_side(self):
        north_jam = hazard("x", "congestion", -80.25, 25.803, severity=3)
        lat, _ = via_point(STRAIGHT["route_geojson"], Point(-80.25, 25.80), HazardIndex([north_jam]))
        self.assertLess(lat, 25.80)
        south_jam = hazard("y", "congestion", -80.25, 25.797, severity=3)
        lat, _ = via_point(STRAIGHT["route_geojson"], Point(-80.25, 25.80), HazardIndex([south_jam]))
        self.assertGreater(lat, 25.80)

    def test_clears_the_edge_of_an_area(self):
        area = box(-80.26, 25.795, -80.24, 25.805)  # ~550 m either side of the road
        lat, lng = via_point(STRAIGHT["route_geojson"], area, HazardIndex([]))
        self.assertFalse(area.contains(Point(lng, lat)))
        edge_gap = min(abs(lat - 25.805), abs(lat - 25.795)) * M_PER_DEG
        self.assertTrue(300 <= edge_gap <= 420, edge_gap)

    def test_no_crossing_no_waypoint(self):
        self.assertIsNone(via_point(STRAIGHT["route_geojson"], Point(-80.25, 25.90), HazardIndex([])))


class PlanTests(unittest.TestCase):
    def plan(self, hazards, responses, preferences=DEFAULTS, start=STRAIGHT):
        calls = []

        async def compute(waypoints):
            calls.append(list(waypoints))
            response = responses[min(len(calls), len(responses)) - 1]
            if isinstance(response, Exception):
                raise response
            return [response]

        best = rank([start], hazards, preferences)[0]
        return asyncio.run(plan_detour(best, hazards, preferences, compute)), calls

    def test_detours_around_a_severe_avoid_hazard(self):
        result, calls = self.plan([CLOSURE], [DETOUR])
        self.assertEqual(result["route"]["summary"], "detour")
        self.assertEqual(len(result["waypoints"]), 1)
        self.assertEqual(calls, [result["waypoints"]])
        self.assertEqual(result["unavoidable"], [])

    def test_mild_or_prefer_avoid_hazards_do_not_trigger(self):
        for h in (hazard("c", "closure", -80.25, 25.80, severity=3), hazard("j", "construction", -80.25, 25.80)):
            result, calls = self.plan([h], [DETOUR])
            self.assertEqual((result["waypoints"], calls), ([], []))

    def test_worse_or_failed_detour_keeps_the_route_and_says_so(self):
        for response in (alt([[-80.30, 25.80], [-80.20, 25.80]], 90), NoRouteFound("x")):
            result, _ = self.plan([CLOSURE], [response])
            self.assertEqual(result["route"]["summary"], "straight")
            self.assertEqual(result["waypoints"], [])
            self.assertEqual(result["unavoidable"], ["Road closed"])

    def test_at_most_two_rounds(self):
        # A milder closure on the first detour: that detour still wins (24 + 96 < 20 + 135), but it's
        # still blocked, so a second round is tried; it scores worse, and there is no third round.
        second = hazard("here:2", "closure", -80.25, 25.81, p=0.8, severity=4)
        detour2 = alt([[-80.30, 25.80], [-80.25, 25.79], [-80.20, 25.80]], 26, "detour2")
        detour3 = alt([[-80.30, 25.80], [-80.25, 25.77], [-80.20, 25.80]], 27, "detour3")
        still_blocked = hazard("here:3", "closure", -80.25, 25.79)
        result, calls = self.plan([CLOSURE, second, still_blocked], [DETOUR, detour2, detour3])
        self.assertEqual(len(calls), 2)
        self.assertEqual([len(c) for c in calls], [1, 2])
        self.assertEqual(result["route"]["summary"], "detour")
        self.assertEqual(result["unavoidable"], ["Road closed"])

    def test_destination_inside_an_avoided_neighborhood(self):
        inside = get_polygon("brickell").representative_point()
        into = alt([[-80.30, 25.80], [inside.x, inside.y]], 20, "into")
        prefs = merge_preferences({"avoid_neighborhoods": ["brickell"]})
        result, _ = self.plan([], [into], prefs, start=into)
        self.assertEqual(result["unavoidable"], ["Brickell"])
        self.assertIn("Couldn't avoid: brickell", briefing(result["route"], False, result["unavoidable"]))


class BriefingTests(unittest.TestCase):
    def test_plain_detour_and_watch_for(self):
        route = {"summary": "via FL-836", "duration_s": 2640,
                 "hazards_on_route": [{"title": "Heavy traffic"}, {"title": "Construction"}]}
        self.assertEqual(briefing(route, False, []),
                         "Taking via FL-836: about 44 min. Watch for heavy traffic, construction.")
        self.assertIn("added a waypoint", briefing(route, True, []))


class EndpointTests(unittest.TestCase):
    def test_route_gets_detour_waypoints_links_and_briefing(self):
        docs = [CLOSURE]
        db = SimpleNamespace(
            intel_cache=SimpleNamespace(find=lambda q, projection=None: SimpleNamespace(to_list=_async(docs))),
            users=SimpleNamespace(find_one=_async(None)), routines=SimpleNamespace(find_one=_async(None)))
        bodies = []

        def handler(request):
            body = json.loads(request.content)
            bodies.append(body)
            line = [(25.80, -80.30), (25.81, -80.25), (25.80, -80.20)] if body.get("intermediates") \
                else [(25.80, -80.30), (25.80, -80.20)]
            return httpx.Response(200, json={"routes": [{
                "description": "detour" if body.get("intermediates") else "straight",
                "duration": "1440s" if body.get("intermediates") else "1200s", "distanceMeters": 1,
                "polyline": {"encodedPolyline": encode(line)}}]})

        app = FastAPI()
        app.include_router(routes.router)
        real = httpx.AsyncClient
        with patch("app.routers.routes.get_db", return_value=db), \
             patch("app.routing.google_routes.get_settings", return_value=SimpleNamespace(google_maps_api_key="k")), \
             patch("app.routing.google_routes.httpx.AsyncClient",
                   lambda **kw: real(transport=httpx.MockTransport(handler))):
            response = TestClient(app).post("/route", json={"origin": [25.80, -80.30], "destination": [25.80, -80.20]})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(bodies), 2)
        self.assertTrue(bodies[0]["computeAlternativeRoutes"])
        self.assertFalse(bodies[1]["computeAlternativeRoutes"])
        self.assertTrue(bodies[1]["intermediates"][0]["via"])
        self.assertEqual(len(body["waypoints"]), 1)
        self.assertEqual([a["summary"] for a in body["alternatives"]], ["via detour", "via straight"])
        self.assertEqual([a["recommended"] for a in body["alternatives"]], [True, False])
        self.assertEqual(body["route_geojson"], body["alternatives"][0]["route_geojson"])
        lat, lng = body["waypoints"][0]
        self.assertIn(f"waypoints={lat:.4f},{lng:.4f}", body["deep_links"]["google_maps"])
        self.assertIn("added a waypoint", body["briefing"])
        self.assertEqual(set(body["deep_links"]), {"google_maps", "apple_maps", "waze"})


def _async(value):
    async def call(*args, **kwargs):
        return value
    return call
