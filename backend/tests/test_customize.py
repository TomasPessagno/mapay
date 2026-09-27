import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import unquote_plus

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents import customize as agent
from app.routers import customize
from app.routers.customize import (
    local_departure,
    match_neighborhoods,
    overpass_road_query,
)

MOCK = json.loads((Path(__file__).resolve().parents[2] / "frontend/public/mocks/customize.json").read_text())


def encode(points):
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


def route(name, points, seconds):
    return {"description": name, "duration": f"{seconds}s", "distanceMeters": 10000,
            "polyline": {"encodedPolyline": encode(points)}}


NEAR_STARBUCKS = (25.789, -80.25)
ORIGIN, DESTINATION = {"lat": 25.80, "lng": -80.30}, {"lat": 25.80, "lng": -80.20}


class Upstreams:
    """One MockTransport for Routes, Places and Overpass; records every request."""

    def __init__(self, overpass_ok=True, places=None):
        self.calls = {"routes": [], "places": [], "overpass": []}
        self.overpass_ok = overpass_ok
        self.places = places if places is not None else [
            {"id": "sb-far", "displayName": {"text": "Starbucks"}, "location": {"latitude": 25.95, "longitude": -80.25}},
            {"id": "sb-near", "displayName": {"text": "Starbucks"}, "formattedAddress": "SW 40th St",
             "location": {"latitude": NEAR_STARBUCKS[0], "longitude": NEAR_STARBUCKS[1]}}]

    def __call__(self, request):
        host = request.url.host
        if host == "routes.googleapis.com":
            body = json.loads(request.content)
            self.calls["routes"].append(body)
            if body.get("intermediates"):
                via = body["intermediates"][0]["location"]["latLng"]
                return httpx.Response(200, json={"routes": [route(
                    "SW 40th St", [(25.80, -80.30), (via["latitude"], via["longitude"]), (25.80, -80.20)], 1500)]})
            return httpx.Response(200, json={"routes": [route("the Palmetto", [(25.80, -80.30), (25.80, -80.20)], 1200),
                                                        route("Bird Rd", [(25.79, -80.30), (25.79, -80.20)], 1320)]})
        if host == "places.googleapis.com":
            self.calls["places"].append(json.loads(request.content))
            return httpx.Response(200, json={"places": self.places})
        if "overpass" in host:
            self.calls["overpass"].append(unquote_plus(request.content.decode()))
            if not self.overpass_ok:
                return httpx.Response(504)
            # The "Palmetto" runs along the fast route between -80.28 and -80.22.
            return httpx.Response(200, json={"elements": [{"geometry": [
                {"lat": 25.80, "lon": -80.28}, {"lat": 25.80, "lon": -80.22}]}]})
        return httpx.Response(404)


class Db:
    def __init__(self):
        self.intel_cache = SimpleNamespace(find=lambda q: SimpleNamespace(to_list=AsyncMock(return_value=[])))
        self.users = SimpleNamespace(find_one=AsyncMock(return_value=None))
        places = {"pl-a": {"_id": "pl-a", "name": "MMC", "location": {"coordinates": [-80.30, 25.80]}},
                  "pl-b": {"_id": "pl-b", "name": "BBC", "location": {"coordinates": [-80.20, 25.80]}}}
        self.places = SimpleNamespace(find_one=AsyncMock(side_effect=lambda q: places.get(q["_id"])))
        routine = {"_id": "rt", "user_id": "dev", "tz": "America/New_York",
                   "legs": [{"from_place": "pl-a", "to_place": "pl-b", "when": {"kind": "at", "time": "09:30"}}]}
        self.routines = SimpleNamespace(find_one=AsyncMock(
            side_effect=lambda q: routine if q == {"_id": "rt", "user_id": "dev"} else None))


GEMINI_CONSTRAINTS = {**agent.EMPTY, "add_stops": [{"query": "Starbucks"}], "avoid_roads": ["SR 826"]}


class EndpointTests(unittest.TestCase):
    def post(self, body, upstreams=None, gemini=True, headers=None):
        upstreams = upstreams or Upstreams()
        customize._road_cache.clear()
        app = FastAPI()
        app.include_router(customize.router)
        real = httpx.AsyncClient
        extract = AsyncMock(return_value=(GEMINI_CONSTRAINTS, "gemini")) if gemini else None
        explain = AsyncMock(return_value="Gemini explanation.") if gemini else None
        patches = [
            patch("app.routers.customize.get_db", return_value=Db()),
            patch("app.routing.google_routes.get_settings", return_value=SimpleNamespace(google_maps_api_key="k")),
            patch("app.routers.customize.get_settings", return_value=SimpleNamespace(google_maps_api_key="k")),
            patch("httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(upstreams))),
        ]
        if gemini:
            patches += [patch("app.routers.customize.extract_constraints", extract),
                        patch("app.routers.customize.explain", explain)]
        else:
            patches.append(patch("app.agents.customize.gemini_configured", return_value=False))
        for p in patches:
            p.start()
        try:
            response = TestClient(app).post("/customize", json=body, headers=headers or {})
        finally:
            for p in reversed(patches):
                p.stop()
        return response, upstreams, explain

    def test_starbucks_and_the_palmetto(self):
        response, up, explain = self.post({"prompt": MOCK["prompt"], "origin": ORIGIN, "destination": DESTINATION})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(set(MOCK) <= set(body))
        self.assertEqual(body["constraints"], GEMINI_CONSTRAINTS)
        self.assertEqual(body["old_route"]["summary"], "via the Palmetto")  # what Mapay picked before
        new = body["new_route"]
        self.assertEqual(set(new), set(MOCK["new_route"]))
        self.assertEqual([s["place_id"] for s in new["stops"]], ["sb-near"])  # closest to the route
        self.assertIn("stopping at Starbucks", new["summary"])
        self.assertIn("25.7890,-80.2500", body["deep_links"]["google_maps"])
        self.assertEqual(body["explanation"], "Gemini explanation.")
        self.assertEqual(body["unmet"], [])
        # Places was biased to the old route; the stop went to Google as a real stop, not a via point.
        bias = up.calls["places"][0]["locationBias"]["rectangle"]
        self.assertLess(bias["low"]["latitude"], 25.80)
        self.assertEqual(up.calls["routes"][-1]["intermediates"][0].get("via"), None)
        self.assertIn('ref~"(^|[ ;])(826)($|[ ;])"', up.calls["overpass"][0])
        facts = explain.await_args.args[0]
        self.assertEqual((facts["minutes_delta"], facts["avoided"]), (5, ["SR 826"]))

    def test_without_gemini_the_keyword_parser_and_template_answer(self):
        response, _, _ = self.post({"prompt": "stay off the Palmetto", "origin": ORIGIN, "destination": DESTINATION},
                                   gemini=False)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["constraints_source"], "keywords")
        self.assertEqual(body["constraints"]["avoid_roads"], ["SR 826"])
        self.assertEqual(body["old_route"]["summary"], "via the Palmetto")
        self.assertEqual(body["new_route"]["summary"], "via Bird Rd")
        self.assertEqual(body["explanation"], "Kept you off SR 826. About 2 min longer than before.")

    def test_unresolved_road_and_stop_are_reported(self):
        response, _, _ = self.post({"prompt": MOCK["prompt"], "origin": ORIGIN, "destination": DESTINATION},
                                   Upstreams(overpass_ok=False, places=[]))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["unmet"], ["couldn't find SR 826", "no Starbucks near the route"])
        self.assertEqual(response.json()["new_route"]["stops"], [])

    def test_routine_leg_request(self):
        body = {"prompt": MOCK["prompt"], "routine_id": "rt", "leg": 0}
        self.assertEqual(self.post(body)[0].status_code, 401)
        self.assertEqual(self.post(body, headers={"X-Device-Id": "someone-else"})[0].status_code, 404)
        self.assertEqual(self.post({**body, "leg": 4}, headers={"X-Device-Id": "dev"})[0].status_code, 422)
        response, up, _ = self.post(body, headers={"X-Device-Id": "dev"})
        self.assertEqual(response.status_code, 200, response.text)
        origin = up.calls["routes"][0]["origin"]["location"]["latLng"]
        self.assertEqual((origin["latitude"], origin["longitude"]), (25.80, -80.30))  # the leg's saved place

    def test_request_validation(self):
        self.assertEqual(self.post({"prompt": "x", "origin": ORIGIN})[0].status_code, 422)
        self.assertEqual(self.post({"prompt": "  ", "origin": ORIGIN, "destination": DESTINATION})[0].status_code, 422)


class ResolverTests(unittest.TestCase):
    def test_neighborhood_names(self):
        self.assertEqual(match_neighborhoods(["Brickell", "little havana", "Atlantis"]),
                         (["brickell", "little-havana"], ["Atlantis"]))

    def test_overpass_query_by_ref_or_name(self):
        self.assertIn('[ref~"(^|[ ;])(95)($|[ ;])"]', overpass_road_query("I-95"))
        query = overpass_road_query('the Palmetto"];out;')
        self.assertIn('[name~"Palmettoout",i]', query)  # no quote or bracket gets through

    def test_local_departure(self):
        now = datetime(2026, 9, 28, 23, 0, tzinfo=timezone.utc)  # 19:00 EDT
        self.assertEqual(local_departure("18:15", None, "America/New_York", now).isoformat(),
                         "2026-09-29T18:15:00-04:00")  # already past today → tomorrow
        self.assertEqual(local_departure("20:00", None, "America/New_York", now).isoformat(),
                         "2026-09-28T20:00:00-04:00")


class AgentTests(unittest.IsolatedAsyncioTestCase):
    def test_normalise_drops_junk(self):
        out = agent.normalise({"add_stops": [{"query": " gas "}, {"nope": 1}], "avoid_categories": ["flood", "lava"],
                               "depart_at": "6pm", "travel_mode": "fly", "extra": 1})
        self.assertEqual(out["add_stops"], [{"query": "gas"}])
        self.assertEqual(out["avoid_categories"], ["flood"])
        self.assertIsNone(out["depart_at"])
        self.assertIsNone(out["travel_mode"])
        self.assertNotIn("extra", out)

    def test_keyword_parser(self):
        out = agent.keyword_constraints("Stop at a Starbucks and stay off the Palmetto, no tolls")
        self.assertEqual((out["add_stops"], out["avoid_roads"], out["avoid_tolls"]),
                         ([{"query": "starbucks"}], ["SR 826"], True))
        self.assertEqual(agent.keyword_constraints("always avoid Brickell")["avoid_neighborhoods"], ["Brickell"])
        self.assertTrue(agent.keyword_constraints("always avoid Brickell")["save_as_preference"])

    async def test_gemini_path_uses_the_structured_schema(self):
        with patch("app.agents.customize.gemini_configured", return_value=True), \
             patch("app.agents.customize._generate", AsyncMock(return_value={**agent.EMPTY, "avoid_roads": ["SR 826"]})) as gen:
            constraints, source = await agent.extract_constraints("stay off the Palmetto", {"from": "MMC"})
        self.assertEqual((constraints["avoid_roads"], source), (["SR 826"], "gemini"))
        self.assertIs(gen.await_args.args[1], agent.CONSTRAINTS_SCHEMA)

    async def test_gemini_failure_falls_back(self):
        with patch("app.agents.customize.gemini_configured", return_value=True), \
             patch("app.agents.customize._generate", AsyncMock(side_effect=RuntimeError("boom"))):
            constraints, source = await agent.extract_constraints("stay off the Palmetto", {})
            text = await agent.explain({"avoided": ["SR 826"], "minutes_delta": -3})
        self.assertEqual((constraints["avoid_roads"], source), (["SR 826"], "keywords"))
        self.assertEqual(text, "Kept you off SR 826. About 3 min shorter than before.")
