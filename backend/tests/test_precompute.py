import asyncio
from datetime import timedelta, timezone
from unittest.mock import patch

import httpx

from app.briefings import precompute
from tests.test_upcoming import MONDAY_0840, UpcomingEndpointTests


class PrecomputeTests(UpcomingEndpointTests):
    """Reuses the upcoming endpoint fixtures (fake db, mocked Routes API, FIU routine)."""

    def precompute(self, now=MONDAY_0840):
        real = httpx.AsyncClient
        from types import SimpleNamespace
        settings = SimpleNamespace(google_maps_api_key="k", google_maps_signing_secret="")
        with patch("app.routing.google_routes.get_settings", return_value=settings), \
             patch("app.briefings.builder.get_settings", return_value=settings), \
             patch("httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(self.handler))):
            return asyncio.run(precompute.run(self.db, now.astimezone(timezone.utc)))

    def test_only_legs_departing_within_two_hours(self):
        result = self.precompute()
        self.assertEqual(result, {"users": 1, "briefings": 1})
        [doc] = self.db.briefings.docs
        self.assertEqual(doc["_id"], "rt-fiu:0:2026-09-28")  # 09:30 today; 17:00 is further than 2 h
        self.assertEqual(doc["item"]["summary"], "via SR-826 and I-95")

    def test_upcoming_serves_the_stored_briefing(self):
        self.precompute()
        calls_after_precompute = len(self.routes_calls)
        from app.briefings import builder
        builder._route_cache.clear()  # prove the item comes from the briefings collection
        self.db.briefings.docs[0]["item"]["summary"] = "from the precomputed briefing"
        body = self.get("/routines/upcoming?days=0").json()
        self.assertEqual(body["items"][0]["summary"], "from the precomputed briefing")
        self.assertEqual(body["items"][1]["summary"], "via SR-826 and I-95")  # built on the fly
        self.assertGreater(len(self.routes_calls), calls_after_precompute)  # only for the other leg

    def test_stale_briefing_is_rebuilt_and_compact_trims(self):
        self.precompute()
        self.db.briefings.docs[0]["item"]["summary"] = "stale"
        self.db.briefings.docs[0]["item"]["top_hazards"] = [{"hazard_id": f"h{i}"} for i in range(3)]
        compact = self.get("/routines/upcoming?days=0&compact=1").json()["items"][0]
        self.assertEqual(len(compact["top_hazards"]), 2)
        self.assertIsNone(compact["image_url"])
        self.db.briefings.docs[0]["computed_at"] -= timedelta(minutes=20)
        rebuilt = self.get("/routines/upcoming?days=0").json()["items"][0]
        self.assertEqual(rebuilt["summary"], "via SR-826 and I-95")

    def test_route_failures_are_not_stored(self):
        self.fail_routes = True
        self.assertEqual(self.precompute()["briefings"], 0)
        self.assertEqual(self.db.briefings.docs, [])

    def test_job_is_registered(self):
        from app.routers import internal
        self.assertIs(internal.JOBS["briefings"], precompute.run)
