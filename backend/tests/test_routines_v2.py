import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models import leg_days
from app.deps import current_user
from app.routers import me, places, routines
from app.routing.pre_route import check_departure

MOCKS = Path(__file__).resolve().parents[2] / "frontend" / "public" / "mocks"
DEV_A, DEV_B = "device-a", "device-b"


def mock(name):
    return json.loads((MOCKS / name).read_text())


def _get(doc, path):
    """Dotted path; through a list it matches if any element has the value (Mongo semantics)."""
    values = [doc]
    for key in path.split("."):
        nxt = []
        for value in values:
            if isinstance(value, list):
                if key.isdigit():
                    nxt.extend([value[int(key)]] if int(key) < len(value) else [])
                else:
                    nxt.extend(v.get(key) for v in value if isinstance(v, dict))
            elif isinstance(value, dict):
                nxt.append(value.get(key))
        values = nxt
    return values


def matches(doc, query):
    for key, value in query.items():
        if key == "$or":
            if not any(matches(doc, q) for q in value):
                return False
        elif value not in _get(doc, key) and not (value is None and not _get(doc, key)):
            return False
    return True


class Collection:
    def __init__(self, docs=()):
        self.docs = [copy.deepcopy(d) for d in docs]

    def find(self, query):
        found = [d for d in self.docs if matches(d, query)]
        return SimpleNamespace(to_list=AsyncMock(return_value=found))

    async def find_one(self, query):
        return next((d for d in self.docs if matches(d, query)), None)

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))

    async def replace_one(self, query, doc):
        for i, d in enumerate(self.docs):
            if matches(d, query):
                self.docs[i] = copy.deepcopy(doc)
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    async def update_one(self, query, update, upsert=False):
        doc = await self.find_one(query)
        if doc is None:
            return SimpleNamespace(matched_count=0)
        doc.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=1)

    async def delete_one(self, query):
        for i, d in enumerate(self.docs):
            if matches(d, query):
                del self.docs[i]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class Api:
    def __init__(self):
        self.db = SimpleNamespace(routines=Collection(), places=Collection(), demo_overrides=Collection(), users=Collection([
            {"_id": DEV_A, "preferences": {"categories": {"flood": "ignore"}}}]))
        self.device = DEV_A
        app = FastAPI()
        for module in (routines, places, me):
            app.include_router(module.router)
        app.dependency_overrides[current_user] = lambda: next(
            (u for u in self.db.users.docs if u["_id"] == self.device), {"_id": self.device, "preferences": {}})
        self.client = TestClient(app)
        self.patches = [patch(f"app.routers.{m}.get_db", return_value=self.db) for m in ("routines", "places", "me")]

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()

    def __getattr__(self, verb):  # api.get / api.post / ...
        return getattr(self.client, verb)


def fiu_routine():
    routine = mock("routines.json")[0]
    routine.pop("user_id")
    return routine


class RoutineModelTests(unittest.TestCase):
    def test_invalid_shapes_are_422(self):
        bad = [
            {"repeat": {"kind": "weekly"}},
            {"repeat": {"kind": "custom", "weekdays": []}},
            {"legs": [{"from_place": "a", "to_place": "b", "when": {"kind": "window", "start": "19:00", "end": "17:00"}}]},
            {"legs": [{"from_place": "a", "to_place": "b", "when": {"kind": "at", "time": "9:30"}}]},
            {"legs": [{"from_place": "a", "to_place": "b", "when": {"kind": "at"}}]},
            {"tz": "Mars/Olympus"},
            {"heads_up_minutes": -5},
        ]
        with Api() as api:
            for body in bad:
                self.assertEqual(api.post("/routines", json={**fiu_routine(), **body}).status_code, 422, body)

    def test_leg_days(self):
        self.assertEqual(leg_days({"repeat": {"kind": "daily"}}, {}), ["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
        self.assertEqual(leg_days({"repeat": {"kind": "weekly", "weekday": "wed"}}, {}), ["wed"])
        self.assertEqual(leg_days({"repeat": {"kind": "custom", "weekdays": ["mon", "fri"]}}, {"days": ["sat"]}), ["sat"])


class RoutineCrudTests(unittest.TestCase):
    def test_mock_routine_round_trips_in_the_mock_shape(self):
        with Api() as api:
            saved = api.post("/routines", json=fiu_routine()).json()
            listed = api.get("/routines").json()
        expected = mock("routines.json")[0]
        self.assertEqual(saved["user_id"], DEV_A)
        self.assertEqual(listed, [saved])
        for key in expected:
            if key != "user_id":
                self.assertEqual(saved[key], expected[key], key)

    def test_repost_updates_and_other_devices_cannot_touch_it(self):
        with Api() as api:
            api.post("/routines", json=fiu_routine())
            api.post("/routines", json={**fiu_routine(), "name": "Campuses"})
            self.assertEqual([r["name"] for r in api.get("/routines").json()], ["Campuses"])
            api.device = DEV_B
            self.assertEqual(api.get("/routines").json(), [])
            self.assertEqual(api.post("/routines", json={**fiu_routine(), "name": "stolen"}).status_code, 404)
            self.assertEqual(api.get("/routines/rt-fiu").status_code, 404)
            self.assertEqual(api.put("/routines/rt-fiu", json=fiu_routine()).status_code, 404)
            self.assertEqual(api.delete("/routines/rt-fiu").status_code, 404)
            api.device = DEV_A
            self.assertEqual(api.get("/routines/rt-fiu").json()["name"], "Campuses")
            self.assertEqual(api.delete("/routines/rt-fiu").status_code, 200)
            self.assertEqual(api.get("/routines").json(), [])

    def test_new_routine_gets_an_id(self):
        with Api() as api:
            body = fiu_routine()
            body.pop("_id")
            self.assertTrue(api.post("/routines", json=body).json()["_id"])

    def test_route_state_is_kept_for_unchanged_legs_and_never_returned(self):
        with Api() as api:
            api.post("/routines", json=fiu_routine())
            api.db.routines.docs[0]["legs"][0]["route_state"] = {"route_geojson": {}, "beliefs": {}}
            api.db.routines.docs[0]["legs"][1]["route_state"] = {"route_geojson": {}, "beliefs": {}}
            edited = fiu_routine()
            edited["legs"][1]["when"] = {"kind": "window", "start": "18:00", "end": "19:30"}
            response = api.put("/routines/rt-fiu", json=edited).json()
            stored = api.db.routines.docs[0]["legs"]
        self.assertIn("route_state", stored[0])
        self.assertNotIn("route_state", stored[1])  # its time changed: the old snapshot no longer applies
        self.assertTrue(all("route_state" not in leg for leg in response["legs"]))


class PlaceTests(unittest.TestCase):
    def test_mock_places_and_the_apps_lat_lng_body(self):
        with Api() as api:
            for place in mock("places.json"):
                place.pop("user_id")
                api.post("/places", json=place)
            created = api.post("/places", json={"name": "Home", "address": "Home",
                                                "location": {"lat": 25.76, "lng": -80.19}}).json()
            listed = api.get("/places").json()
        self.assertEqual(created["location"], {"type": "Point", "coordinates": [-80.19, 25.76]})
        self.assertEqual([p["name"] for p in listed], ["MMC", "BBC", "Home"])
        self.assertEqual(listed[0]["google_place_id"], "mock-place-mmc")
        self.assertTrue(all(p["user_id"] == DEV_A for p in listed))

    def test_scoped_update_and_delete_guard(self):
        with Api() as api:
            api.post("/places", json={"_id": "pl-mmc", "name": "MMC", "location": {"lat": 25.75, "lng": -80.37}})
            self.assertEqual(api.put("/places/pl-mmc", json={"name": "FIU MMC", "location": {"lat": 25.75,
                                                                                           "lng": -80.37}}).json()["name"],
                             "FIU MMC")
            api.post("/routines", json=fiu_routine())
            self.assertEqual(api.delete("/places/pl-mmc").status_code, 409)  # a routine leg uses it
            api.device = DEV_B
            self.assertEqual(api.get("/places").json(), [])
            self.assertEqual(api.delete("/places/pl-mmc").status_code, 404)
            self.assertEqual(api.put("/places/pl-mmc", json={"name": "x", "location": {"lat": 0, "lng": 0}}).status_code, 404)


class PreferenceTests(unittest.TestCase):
    def test_get_merges_defaults_and_put_stores_the_full_shape(self):
        with Api() as api:
            got = api.get("/me/preferences").json()
            self.assertEqual(got["categories"]["flood"], "ignore")  # the user's own choice
            self.assertEqual(got["categories"]["closure"], "avoid")  # default
            self.assertEqual(set(got), set(mock("preferences.json")))
            saved = api.put("/me/preferences", json=mock("preferences.json")).json()
            self.assertEqual(saved, mock("preferences.json"))
            self.assertEqual(api.db.users.docs[0]["preferences"], saved)

    def test_invalid_values_are_422(self):
        with Api() as api:
            self.assertEqual(api.put("/me/preferences", json={"categories": {"flood": "maybe"}}).status_code, 422)
            self.assertEqual(api.put("/me/preferences", json={"categories": {"sharks": "avoid"}}).status_code, 422)
            self.assertEqual(api.put("/me/preferences", json={"nav_app": "mapquest"}).status_code, 422)


class DepartureTests(unittest.TestCase):
    routine: ClassVar[dict] = {"tz": "America/New_York", "repeat": {"kind": "custom", "weekdays": ["mon", "tue", "wed", "thu", "fri"]},
               "legs": [{"from_place": "a", "to_place": "b", "when": {"kind": "at", "time": "09:30"}},
                        {"from_place": "b", "to_place": "a", "when": {"kind": "window", "start": "17:00", "end": "19:00"},
                         "days": ["sat"]}]}

    def test_at_leg_only_at_its_time_on_its_days(self):
        monday = datetime(2026, 9, 28, 13, 30, tzinfo=timezone.utc)  # 09:30 EDT
        self.assertEqual(check_departure(self.routine, 0, monday)["when"]["time"], "09:30")
        for bad in (monday + timedelta(minutes=5), monday - timedelta(days=2)):  # 09:35; Saturday
            with self.assertRaises(ValueError):
                check_departure(self.routine, 0, bad)

    def test_dst_uses_the_routine_timezone(self):
        after_dst = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)  # Monday 09:30 EST
        self.assertTrue(check_departure(self.routine, 0, after_dst))

    def test_window_leg_with_day_override(self):
        saturday = datetime(2026, 9, 26, 22, 0, tzinfo=timezone.utc)  # 18:00 EDT
        self.assertTrue(check_departure(self.routine, 1, saturday))
        with self.assertRaises(ValueError):
            check_departure(self.routine, 1, saturday + timedelta(hours=2))  # 20:00
        with self.assertRaises(ValueError):
            check_departure(self.routine, 1, saturday + timedelta(days=2))  # Monday: overridden away

    def test_bad_leg_or_naive_time(self):
        with self.assertRaises(ValueError):
            check_departure(self.routine, 5, datetime(2026, 9, 28, 13, 30, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            check_departure(self.routine, 0, datetime(2026, 9, 28, 9, 30))  # noqa: DTZ001


class PreRouteEndpointTests(unittest.TestCase):
    def test_takes_leg_and_departure(self):
        with Api() as api, patch("app.routers.routines.check_routine",
                                 AsyncMock(return_value={"recalculated": False})) as check:
            api.post("/routines", json=fiu_routine())
            response = api.post("/routines/rt-fiu/pre-route-check",
                                json={"leg": 1, "departure": "2026-09-28T17:30:00-04:00"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(check.await_args.args[2], 1)
            check.side_effect = ValueError("Routine has no leg 7")
            response = api.post("/routines/rt-fiu/pre-route-check", json={"leg": 7, "departure": "2026-09-28T17:30:00-04:00"})
            self.assertEqual(response.status_code, 422)
