import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import routes
from app.routers.neighborhoods import get_polygon
from app.routing.beliefs import log_odds
from app.routing.scoring import merge_preferences, rank

DEFAULTS = merge_preferences()


def alt(coords, minutes, summary=""):
    return {"summary": summary, "duration_s": minutes * 60, "static_duration_s": minutes * 60, "distance_m": 1000,
            "route_geojson": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": coords}}]}}


def hazard(hazard_id, kind, lng, lat, p, severity=3, properties=None):
    doc = {"hazard_id": hazard_id, "hazard_type": kind, "severity": severity, "log_odds": log_odds(p),
           "geometry": {"type": "Point", "coordinates": [lng, lat]}}
    if properties:
        doc["properties"] = properties
    return doc


# Two east-west routes ~1 km apart in Miami's latitude band.
NORTH = alt([[-80.30, 25.80], [-80.20, 25.80]], 20, "north")
SOUTH = alt([[-80.30, 25.79], [-80.20, 25.79]], 25, "south")


class PenaltyTests(unittest.TestCase):
    def score(self, hazards, preferences=DEFAULTS, alternatives=(NORTH,)):
        return rank(list(alternatives), hazards, preferences)

    def test_formula_weight_times_severity_times_p_times_three(self):
        [scored] = self.score([hazard("f", "flood", -80.25, 25.80, 0.8, severity=3)])
        self.assertAlmostEqual(scored["score"], 20 + 10 * 3 * 0.8 * 3)  # flood defaults to avoid

    def test_prefer_avoid_and_ignore_weights(self):
        [scored] = self.score([hazard("c", "construction", -80.25, 25.80, 0.8, severity=2)])
        self.assertAlmostEqual(scored["score"], 20 + 2 * 2 * 0.8 * 3)
        [scored] = self.score([hazard("p", "pothole", -80.25, 25.80, 0.9, severity=4)])
        self.assertEqual(scored["score"], 20)
        self.assertEqual([h["hazard_id"] for h in scored["hazards_on_route"]], ["p"])  # listed, not penalised

    def test_only_active_beliefs_count(self):
        [scored] = self.score([hazard("f", "flood", -80.25, 25.80, 0.72)])  # log-odds 0.94 < 1.0
        self.assertEqual((scored["score"], scored["hazards_on_route"]), (20, []))

    def test_corridor_is_about_30_m(self):
        near = hazard("near", "flood", -80.25, 25.80 + 0.0002, 0.9)  # ~22 m off the line
        far = hazard("far", "flood", -80.25, 25.80 + 0.0005, 0.9)  # ~55 m off
        [scored] = self.score([near, far])
        self.assertEqual([h["hazard_id"] for h in scored["hazards_on_route"]], ["near"])

    def test_user_preference_changes_the_weight(self):
        prefs = merge_preferences({"categories": {"flood": "ignore"}})
        [scored] = self.score([hazard("f", "flood", -80.25, 25.80, 0.9)], prefs)
        self.assertEqual(scored["score"], 20)

    def test_hazards_on_route_worst_first_with_titles(self):
        [scored] = self.score([
            hazard("c", "construction", -80.28, 25.80, 0.8, severity=1),
            hazard("f", "flood", -80.25, 25.80, 0.876, properties={"title": "Brickell Bay Dr flooding"})])
        self.assertEqual(scored["hazards_on_route"], [
            {"hazard_id": "f", "hazard_type": "flood", "title": "Brickell Bay Dr flooding", "probability": 0.88},
            {"hazard_id": "c", "hazard_type": "construction", "title": "Construction", "probability": 0.8}])


class NeighborhoodTests(unittest.TestCase):
    def setUp(self):
        polygon = get_polygon("brickell")
        inside = polygon.representative_point()
        self.through = alt([[inside.x - 0.05, inside.y], [inside.x, inside.y], [inside.x + 0.05, inside.y]], 20)
        self.around = alt([[-80.45, 25.95], [-80.40, 25.95]], 30)

    def test_avoided_neighborhood_is_severity_five_p_one(self):
        prefs = merge_preferences({"avoid_neighborhoods": ["brickell"]})
        ranked = rank([self.through, self.around], [], prefs)
        self.assertEqual(ranked[0]["duration_s"], 30 * 60)  # the detour wins
        through = ranked[1]
        self.assertAlmostEqual(through["score"], 20 + 10 * 5 * 1 * 3)
        self.assertEqual(through["neighborhoods_crossed"], ["brickell"])
        self.assertEqual(through["hazards_on_route"], [])

    def test_unknown_or_unavoided_neighborhood_costs_nothing(self):
        for prefs in (DEFAULTS, merge_preferences({"avoid_neighborhoods": ["no-such-place"]})):
            self.assertEqual(rank([self.through], [], prefs)[0]["score"], 20)


class RankTests(unittest.TestCase):
    def test_sorted_by_cost_with_one_recommended(self):
        flood_on_north = hazard("f", "flood", -80.25, 25.80, 0.9)
        ranked = rank([NORTH, SOUTH], [flood_on_north], DEFAULTS)
        self.assertEqual([a["summary"] for a in ranked], ["south", "north"])
        self.assertEqual([a["recommended"] for a in ranked], [True, False])

    def test_ties_keep_googles_order(self):
        twin = alt([[-80.30, 25.70], [-80.20, 25.70]], 20, "twin")
        self.assertEqual([a["summary"] for a in rank([NORTH, twin], [], DEFAULTS)], ["north", "twin"])


class MergeTests(unittest.TestCase):
    def test_precedence_and_per_category_merge(self):
        user = {"categories": {"construction": "avoid"}, "avoid_neighborhoods": ["brickell"], "avoid_tolls": True}
        routine = {"categories": {"flood": "prefer_avoid"}}
        request = {"categories": {"construction": "ignore"}, "avoid_tolls": None}
        merged = merge_preferences(user, routine, request)
        self.assertEqual(merged["categories"]["construction"], "ignore")
        self.assertEqual(merged["categories"]["flood"], "prefer_avoid")
        self.assertEqual(merged["categories"]["closure"], "avoid")  # AGENTS.md default
        self.assertEqual(merged["avoid_neighborhoods"], ["brickell"])
        self.assertTrue(merged["avoid_tolls"])  # None doesn't override

    def test_defaults_are_not_shared(self):
        merge_preferences({"categories": {"flood": "ignore"}})
        self.assertEqual(merge_preferences()["categories"]["flood"], "avoid")


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length=None):
        return list(self.docs)


class Collection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        return FakeCursor([d for d in self.docs if all(d.get(k) == v for k, v in query.items())])

    async def find_one(self, query):
        return next((d for d in self.docs if all(d.get(k) == v for k, v in query.items())), None)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        flood = {**hazard("flood:x", "flood", -80.25, 25.80, 0.9), "type": "hazard_belief", "evidence": {}}
        self.db = SimpleNamespace(
            intel_cache=Collection([flood]),
            users=Collection([{"_id": "dev-1", "preferences": {"categories": {"flood": "ignore"}, "avoid_tolls": True}}]),
            routines=Collection([]))
        app = FastAPI()
        app.include_router(routes.router)
        self.client = TestClient(app)

    def post(self, body, headers=None):
        seen = []

        def handler(request):
            seen.append(json.loads(request.content))
            polyline = {"north": '_an|C~qbiN?_pR', "south": 'obl|C~qbiN?_pR'}  # the two fixture lines
            return httpx.Response(200, json={"routes": [
                {"description": "north", "duration": "1200s", "staticDuration": "1200s", "distanceMeters": 1,
                 "polyline": {"encodedPolyline": polyline["north"]}},
                {"description": "south", "duration": "1500s", "staticDuration": "1500s", "distanceMeters": 1,
                 "polyline": {"encodedPolyline": polyline["south"]}}]})

        real = httpx.AsyncClient
        with patch("app.routers.routes.get_db", return_value=self.db), \
             patch("app.routing.google_routes.get_settings", return_value=SimpleNamespace(google_maps_api_key="k")), \
             patch("app.routing.google_routes.httpx.AsyncClient",
                   lambda **kw: real(transport=httpx.MockTransport(handler))):
            response = self.client.post("/route", json=body, headers=headers or {})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), seen[0]

    def test_defaults_route_around_the_flood(self):
        body, google = self.post({"origin": [25.80, -80.30], "destination": [25.80, -80.20]})
        self.assertEqual([a["summary"] for a in body["alternatives"]], ["via south", "via north"])
        self.assertEqual(body["alternatives"][1]["hazards_on_route"][0]["hazard_id"], "flood:x")
        self.assertEqual(body["hazards_on_route"], [])
        self.assertEqual(body["route_geojson"], body["alternatives"][0]["route_geojson"])
        self.assertEqual(body["alternatives"][0]["score"], 25.0)
        self.assertFalse(google["routeModifiers"]["avoidTolls"])

    def test_user_defaults_then_request_overrides(self):
        body, google = self.post({"origin": [25.80, -80.30], "destination": [25.80, -80.20]},
                                 {"X-Device-Id": "dev-1"})
        self.assertEqual(body["alternatives"][0]["summary"], "via north")  # the user ignores floods
        self.assertTrue(google["routeModifiers"]["avoidTolls"])
        body, google = self.post({"origin": [25.80, -80.30], "destination": [25.80, -80.20], "avoid_tolls": False,
                                  "preferences": {"categories": {"flood": "avoid"}}}, {"X-Device-Id": "dev-1"})
        self.assertEqual(body["alternatives"][0]["summary"], "via south")
        self.assertFalse(google["routeModifiers"]["avoidTolls"])
