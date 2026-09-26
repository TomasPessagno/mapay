import unittest
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.deps import current_user
from app.routers import reports, routines

DEVICE_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DEVICE_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return list(self._docs if length is None else self._docs[:length])


class FakeCollection:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _matches(doc, query):
        return all(doc.get(key) == value for key, value in query.items())

    async def find_one(self, query):
        for doc in self.docs:
            if self._matches(doc, query):
                return doc
        return None

    def find(self, query):
        return FakeCursor([doc for doc in self.docs if self._matches(doc, query)])

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("_id"))

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if self._matches(doc, query):
                doc.update(update.get("$set", {}))
                return SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            new = dict(query)
            new.update(update.get("$setOnInsert", {}))
            new.update(update.get("$set", {}))
            self.docs.append(new)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=new.get("_id"))
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def delete_one(self, query):
        for index, doc in enumerate(self.docs):
            if self._matches(doc, query):
                del self.docs[index]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class FakeDb(SimpleNamespace):
    def __init__(self):
        super().__init__(users=FakeCollection(), routines=FakeCollection(), hazard_reports=FakeCollection())


def whoami_app():
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(user: Annotated[dict, Depends(current_user)]):
        return {"device_id": user["_id"], "preferences": user["preferences"]}

    return app


def api_app(db, user_id=DEVICE_A, override_user=True):
    app = FastAPI()
    app.include_router(routines.router)
    app.include_router(reports.router)
    if override_user:
        app.dependency_overrides[current_user] = lambda: {"_id": user_id, "preferences": {}}
    return app


ROUTINE_BODY = {
    "user_id": DEVICE_B,
    "origin": [25.0, -80.0],
    "destination": [26.0, -80.0],
    "days": ["mon"],
    "time_window": ["09:00", "10:00"],
}


class DeviceIdTests(unittest.TestCase):
    def test_missing_header_is_401(self):
        with patch("app.deps.get_db", return_value=FakeDb()):
            response = TestClient(whoami_app()).get("/whoami")
        self.assertEqual(response.status_code, 401)

    def test_blank_header_is_401(self):
        with patch("app.deps.get_db", return_value=FakeDb()):
            response = TestClient(whoami_app()).get("/whoami", headers={"X-Device-Id": "   "})
        self.assertEqual(response.status_code, 401)

    def test_first_call_upserts_default_preferences(self):
        db = FakeDb()
        with patch("app.deps.get_db", return_value=db):
            client = TestClient(whoami_app())
            response = client.get("/whoami", headers={"X-Device-Id": DEVICE_A})
            client.get("/whoami", headers={"X-Device-Id": DEVICE_A})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["device_id"], DEVICE_A)
        self.assertEqual(response.json()["preferences"]["categories"]["flood"], "avoid")
        self.assertEqual(response.json()["preferences"]["nav_app"], "google_maps")
        self.assertEqual(len(db.users.docs), 1)
        self.assertEqual(db.users.docs[0]["_id"], DEVICE_A)
        self.assertIsNotNone(db.users.docs[0]["created_at"])

    def test_routines_are_scoped_to_the_calling_user(self):
        db = FakeDb()
        db.routines.docs = [{"_id": "r-a", "user_id": DEVICE_A}, {"_id": "r-b", "user_id": DEVICE_B}]
        app = api_app(db)
        with patch("app.routers.routines.get_db", return_value=db), \
             patch("app.routers.reports.get_db", return_value=db):
            client = TestClient(app)
            listed = client.get("/routines")
            created = client.post("/routines", json=ROUTINE_BODY)
            deleted = client.delete("/routines/r-b")
        self.assertEqual([r["_id"] for r in listed.json()], ["r-a"])
        self.assertEqual(created.json()["user_id"], DEVICE_A)
        self.assertEqual(db.routines.docs[-1]["user_id"], DEVICE_A)
        self.assertEqual(deleted.status_code, 404)

    def test_reports_are_scoped_to_the_calling_user(self):
        db = FakeDb()
        db.hazard_reports.docs = [
            {"_id": "p-a", "user_id": DEVICE_A, "location": {"type": "Point", "coordinates": [-80.0, 25.0]}},
            {"_id": "p-b", "user_id": DEVICE_B, "location": {"type": "Point", "coordinates": [-80.1, 25.1]}},
        ]
        app = api_app(db)
        with patch("app.routers.routines.get_db", return_value=db), \
             patch("app.routers.reports.get_db", return_value=db):
            client = TestClient(app)
            listed = client.get("/report")
            created = client.post("/report", json={"type": "flood", "lat": 25.0, "lng": -80.0})
        self.assertEqual({f["properties"]["_id"] for f in listed.json()["features"]}, {"p-a"})
        self.assertTrue(created.json()["ok"])
        self.assertEqual(db.hazard_reports.docs[-1]["user_id"], DEVICE_A)

    def test_real_dependency_runs_through_router(self):
        db = FakeDb()
        app = api_app(db, override_user=False)
        with patch("app.deps.get_db", return_value=db), \
             patch("app.routers.routines.get_db", return_value=db), \
             patch("app.routers.reports.get_db", return_value=db):
            response = TestClient(app).get("/routines", headers={"X-Device-Id": DEVICE_A})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        self.assertEqual(db.users.docs[0]["_id"], DEVICE_A)
