import base64
import hashlib
import hmac
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.briefings import builder
from app.deps import current_user
from app.routers import demo, routines
from app.scheduling.occurrences import leg_occurrences, upcoming

NY = ZoneInfo("America/New_York")
MOCK = json.loads((Path(__file__).resolve().parents[2] / "frontend/public/mocks/routines-upcoming.json").read_text())


def routine(**overrides):
    base = {"_id": "rt-fiu", "user_id": "dev", "name": "FIU campuses", "active": True, "tz": "America/New_York",
            "heads_up_minutes": 30, "repeat": {"kind": "custom", "weekdays": ["mon", "tue", "wed", "thu", "fri"]},
            "legs": [{"from_place": "pl-mmc", "to_place": "pl-bbc", "when": {"kind": "at", "time": "09:30"}},
                     {"from_place": "pl-bbc", "to_place": "pl-mmc",
                      "when": {"kind": "window", "start": "17:00", "end": "19:00"}}]}
    return {**base, **overrides}


def local(*args):
    return datetime(*args, tzinfo=NY)


MONDAY_0840 = local(2026, 9, 28, 8, 40)


class OccurrenceTests(unittest.TestCase):
    def test_weekdays_from_now_soonest_first(self):
        found = leg_occurrences(routine(), 0, MONDAY_0840, 7)
        self.assertEqual([o.local_date.isoformat() for o in found],
                         ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05"])
        first = found[0]
        self.assertEqual(first.departure_at.isoformat(), "2026-09-28T09:30:00-04:00")
        self.assertEqual(first.heads_up_at.isoformat(), "2026-09-28T09:00:00-04:00")
        self.assertIsNone(first.window)

    def test_departed_today_starts_tomorrow(self):
        found = leg_occurrences(routine(), 0, local(2026, 9, 28, 9, 31), 1)
        self.assertEqual([o.local_date.isoformat() for o in found], ["2026-09-29"])

    def test_window_leg_departs_at_its_start(self):
        found = leg_occurrences(routine(), 1, MONDAY_0840, 0)
        self.assertEqual(found[0].departure_at.isoformat(), "2026-09-28T17:00:00-04:00")
        self.assertEqual([t.isoformat() for t in found[0].window],
                         ["2026-09-28T17:00:00-04:00", "2026-09-28T19:00:00-04:00"])
        self.assertEqual(found[0].heads_up_at.isoformat(), "2026-09-28T16:30:00-04:00")

    def test_repeat_rules_and_leg_override(self):
        daily = routine(repeat={"kind": "daily"})
        self.assertEqual(len(leg_occurrences(daily, 0, MONDAY_0840, 6)), 7)
        weekly = routine(repeat={"kind": "weekly", "weekday": "wed"})
        self.assertEqual([o.local_date.isoformat() for o in leg_occurrences(weekly, 0, MONDAY_0840, 13)],
                         ["2026-09-30", "2026-10-07"])
        overridden = routine()
        overridden["legs"][0]["days"] = ["sat"]
        self.assertEqual([o.local_date.isoformat() for o in leg_occurrences(overridden, 0, MONDAY_0840, 7)],
                         ["2026-10-03"])

    def test_dst_fall_back_keeps_the_wall_clock(self):
        daily = routine(repeat={"kind": "daily"})
        found = leg_occurrences(daily, 0, local(2026, 10, 31, 8, 0), 2)  # DST ends Sun Nov 1
        utc_times = [o.departure_at.astimezone(timezone.utc).strftime("%m-%d %H:%M") for o in found]
        self.assertEqual(utc_times, ["10-31 13:30", "11-01 14:30", "11-02 14:30"])
        self.assertTrue(all(o.departure_at.strftime("%H:%M") == "09:30" for o in found))

    def test_dst_spring_forward_gap(self):
        early = routine(repeat={"kind": "daily"})
        early["legs"][0]["when"] = {"kind": "at", "time": "02:30"}  # doesn't exist on Sun Mar 14 2027
        found = leg_occurrences(early, 0, local(2027, 3, 13, 12, 0), 1)
        self.assertEqual(found[0].departure_at.isoformat(), "2027-03-14T03:30:00-04:00")

    def test_inactive_routines_and_demo_first(self):
        now = MONDAY_0840
        override = {"routine_id": "rt-fiu", "leg": 1, "departure_at": now + timedelta(minutes=30)}
        items = upcoming([routine(), routine(_id="off", active=False)], [override], now, 1)
        self.assertEqual(items[0].leg, 1)
        self.assertTrue(items[0].demo)
        self.assertEqual(items[0].heads_up_at, now)
        self.assertNotIn("off", {o.routine_id for o in items})
        self.assertEqual([o.departure_at for o in items], sorted(o.departure_at for o in items))


def encode(points):
    from app.routing.google_routes import encode_polyline
    return encode_polyline([[lng, lat] for lat, lng in points])


class Collection:
    def __init__(self, docs=()):
        self.docs = list(docs)

    def find(self, query, projection=None):
        def ok(doc):
            for key, value in query.items():
                if isinstance(value, dict) and "$in" in value:
                    if doc.get(key) not in value["$in"]:
                        return False
                elif doc.get(key) != value:
                    return False
            return True
        return SimpleNamespace(to_list=AsyncMock(return_value=[d for d in self.docs if ok(d)]))

    async def find_one(self, query):
        found = await self.find(query).to_list()
        return found[0] if found else None

    async def replace_one(self, query, doc, upsert=False):
        self.docs = [d for d in self.docs if d.get("_id") != query["_id"]] + [doc]


class UpcomingEndpointTests(unittest.TestCase):
    def setUp(self):
        builder._route_cache.clear()
        self.routes_calls = []
        self.fail_routes = False
        self.db = SimpleNamespace(
            routines=Collection([routine()]),
            places=Collection([
                {"_id": "pl-mmc", "name": "MMC", "location": {"type": "Point", "coordinates": [-80.3733, 25.7574]}},
                {"_id": "pl-bbc", "name": "BBC", "location": {"type": "Point", "coordinates": [-80.1392, 25.9104]}}]),
            demo_overrides=Collection(), users=Collection(), briefings=Collection(),
            intel_cache=Collection([{"_id": "belief:flood:x", "type": "hazard_belief", "hazard_id": "flood:x",
                                     "hazard_type": "flood", "severity": 2, "log_odds": 2.0, "prior_log_odds": 2.0,
                                     "evidence": {}, "geometry": {"type": "Point", "coordinates": [-80.25, 25.85]}}]))
        app = FastAPI()
        app.include_router(routines.router)
        app.include_router(demo.router)
        app.dependency_overrides[current_user] = lambda: {"_id": "dev", "preferences": {}}
        self.client = TestClient(app)

    def handler(self, request):
        self.routes_calls.append(json.loads(request.content))
        if self.fail_routes:
            return httpx.Response(403, json={"error": {"message": "blocked"}})
        origin = self.routes_calls[-1]["origin"]["location"]["latLng"]
        start = (origin["latitude"], origin["longitude"])
        end = (25.9104, -80.1392) if start[0] < 25.8 else (25.7574, -80.3733)
        return httpx.Response(200, json={"routes": [{
            "description": "SR-826 and I-95", "duration": "2460s", "staticDuration": "1980s", "distanceMeters": 31800,
            "polyline": {"encodedPolyline": encode([start, (25.85, -80.25), end])}}]})

    def get(self, path, secret="", now=MONDAY_0840):
        real = httpx.AsyncClient
        settings = SimpleNamespace(google_maps_api_key="k", google_maps_signing_secret=secret)
        with patch("app.routers.routines.get_db", return_value=self.db), \
             patch("app.routers.demo.get_db", return_value=self.db), \
             patch("app.routers.routines.datetime", wraps=datetime) as clock, \
             patch("app.routing.google_routes.get_settings", return_value=settings), \
             patch("app.briefings.builder.get_settings", return_value=settings), \
             patch("httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(self.handler))):
            clock.now.return_value = now.astimezone(timezone.utc)
            return self.client.get(path)

    def test_mock_shape_and_links(self):
        body = self.get("/routines/upcoming?days=1").json()
        self.assertEqual(set(body), set(MOCK))
        first, mock_first = body["items"][0], MOCK["items"][0]
        self.assertEqual(set(first), set(mock_first))
        self.assertEqual((first["from"]["name"], first["to"]["name"], first["departure_at"]),
                         ("MMC", "BBC", "2026-09-28T09:30:00-04:00"))
        self.assertEqual(first["deep_links"]["start"], "mapay://start?routine=rt-fiu&leg=0")
        self.assertEqual(first["deep_links"]["customize"], "mapay://customize?routine=rt-fiu&leg=0")
        self.assertTrue(first["deep_links"]["google_maps"].startswith(
            "https://www.google.com/maps/dir/?api=1&origin=25.7574,-80.3733&destination=25.9104,-80.1392"))
        self.assertEqual((first["duration_s"], first["summary"]), (2460, "via SR-826 and I-95"))
        self.assertEqual(first["top_hazards"][0]["hazard_id"], "flood:x")
        self.assertEqual(first["top_hazards"][0]["status"], "predicted")  # tides-style prior only
        self.assertIsNone(first["image_url"])  # no signing secret
        self.assertEqual(body["items"][1]["window"]["end"], "2026-09-28T19:00:00-04:00")

    def test_each_leg_is_routed_once_and_cached(self):
        self.get("/routines/upcoming?days=7")
        # 2 legs routed once each (12 items), plus best-time checks (9 departures, 17:00-19:00) for the
        # two windows starting within 48 h (Mon and Tue); later windows aren't checked.
        self.assertEqual(len(self.routes_calls), 2 + 9 + 9)
        self.get("/routines/upcoming?days=7")
        self.assertEqual(len(self.routes_calls), 20)  # everything served from the caches

    def test_compact_and_limit(self):
        body = self.get("/routines/upcoming?compact=1&limit=3", secret="c2VjcmV0").json()
        self.assertEqual(len(body["items"]), 3)
        self.assertTrue(all(i["image_url"] is None and len(i["top_hazards"]) <= 2 for i in body["items"]))

    def test_signed_static_map(self):
        secret = base64.urlsafe_b64encode(b"test-secret").decode()
        url = self.get("/routines/upcoming?days=0", secret=secret).json()["items"][0]["image_url"]
        parts = urlsplit(url)
        self.assertEqual(parts.netloc, "maps.googleapis.com")
        signed, signature = url.split("&signature=")
        path_and_query = signed[len("https://maps.googleapis.com"):]
        expected = base64.urlsafe_b64encode(hmac.new(b"test-secret", path_and_query.encode(), hashlib.sha1).digest())
        self.assertEqual(signature, expected.decode())
        query = parse_qs(parts.query)
        self.assertTrue(query["path"][0].startswith("color:0x007AFFff|weight:5|enc:"))
        self.assertIn("color:0x32ADE6", query["markers"][0])  # flood marker in the legend colour

    def test_route_failure_still_lists_the_leg(self):
        self.fail_routes = True
        item = self.get("/routines/upcoming?days=0").json()["items"][0]
        self.assertEqual((item["duration_s"], item["top_hazards"], item["route_error"]),
                         (0, [], "Route unavailable right now"))
        self.assertEqual(item["heads_up_at"], "2026-09-28T09:00:00-04:00")

    def test_demo_heads_up_end_to_end(self):
        with patch("app.routers.demo.get_db", return_value=self.db):
            self.assertEqual(self.client.post("/demo/heads-up", json={"routine_id": "nope", "leg": 0}).status_code, 404)
            self.assertEqual(self.client.post("/demo/heads-up", json={"routine_id": "rt-fiu", "leg": 9}).status_code, 422)
            fired = self.client.post("/demo/heads-up", json={"routine_id": "rt-fiu", "leg": 1}).json()
        departure = datetime.fromisoformat(fired["departure_at"])
        self.assertAlmostEqual((departure - datetime.now(timezone.utc)).total_seconds(), 1800, delta=5)
        now = datetime.now(timezone.utc)
        body = self.get("/routines/upcoming?days=0", now=now).json()
        first = body["items"][0]
        self.assertTrue(first["demo"])
        self.assertEqual(first["leg"], 1)
        self.assertLessEqual(datetime.fromisoformat(first["heads_up_at"]), now + timedelta(seconds=5))
        # The pre-route check accepts the off-schedule demo departure.
        with patch("app.routers.routines.get_db", return_value=self.db), \
             patch("app.routers.routines.check_routine", AsyncMock(return_value={"recalculated": False})) as check:
            response = self.client.post("/routines/rt-fiu/pre-route-check",
                                        json={"leg": 1, "departure": fired["departure_at"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(check.await_args.kwargs["demo"])
