import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import internal

AUDIENCE = "https://mapay-api-xyz.a.run.app"
SCHEDULER = "gemini-runner@proj.iam.gserviceaccount.com"


def make_client(override=True):
    app = FastAPI()
    app.include_router(internal.router)
    if override:
        app.dependency_overrides[internal.require_scheduler] = lambda: {"email": SCHEDULER}
    return TestClient(app)


def settings(audience=AUDIENCE, account=SCHEDULER):
    return patch("app.routers.internal.get_settings",
                 return_value=SimpleNamespace(internal_audience=audience, scheduler_service_account=account))


class IngestTests(unittest.TestCase):
    def test_runs_the_named_job_with_db_and_now(self):
        job = AsyncMock(return_value={"registered": 15})
        with patch.dict(internal.JOBS, {"tides": job}), patch("app.routers.internal.get_db", return_value="db"):
            response = make_client().post("/internal/ingest/tides")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["job"], body["result"]), ("tides", {"registered": 15}))
        db, now = job.await_args.args
        self.assertEqual(db, "db")
        self.assertIsNotNone(now.tzinfo)

    def test_unknown_job_is_404(self):
        self.assertEqual(make_client().post("/internal/ingest/nope").status_code, 404)

    def test_failing_job_is_502_so_scheduler_retries(self):
        with patch.dict(internal.JOBS, {"tides": AsyncMock(side_effect=RuntimeError("NOAA down"))}), \
             patch("app.routers.internal.get_db"):
            response = make_client().post("/internal/ingest/tides")
        self.assertEqual(response.status_code, 502)

    def test_successful_ingest_invalidates_the_layers_snapshot(self):
        with patch.dict(internal.JOBS, {"tides": AsyncMock(return_value={})}), \
             patch("app.routers.internal.get_db") as get_db, \
             patch("app.routers.internal.invalidate_snapshot") as invalidate:
            response = make_client().post("/internal/ingest/tides")
        self.assertEqual(response.status_code, 200, response.text)
        invalidate.assert_called_once_with(get_db.return_value)

    def test_failed_ingest_still_invalidates_the_layers_snapshot(self):
        with patch.dict(internal.JOBS, {"tides": AsyncMock(side_effect=RuntimeError("NOAA down"))}), \
             patch("app.routers.internal.get_db") as get_db, \
             patch("app.routers.internal.invalidate_snapshot") as invalidate:
            response = make_client().post("/internal/ingest/tides")
        self.assertEqual(response.status_code, 502)
        invalidate.assert_called_once_with(get_db.return_value)

    def test_registry_has_the_merged_jobs(self):
        self.assertTrue({"news", "weather", "here", "tides", "city_gis", "sidewalks", "potholes"} <= set(internal.JOBS))

    def test_successful_ingest_records_that_run(self):
        db = SimpleNamespace(ingest_runs=AsyncMock())
        with patch.dict(internal.JOBS, {"news": AsyncMock(return_value={"fetched": 0, "new": 0})}), \
             patch("app.routers.internal.get_db", return_value=db), \
             patch("app.routers.internal.invalidate_snapshot"):
            response = make_client().post("/internal/ingest/news")
        self.assertEqual(response.status_code, 200, response.text)
        query, update = db.ingest_runs.update_one.await_args.args[:2]
        self.assertEqual(query, {"_id": "run:news"})
        self.assertEqual(update["$set"]["job"], "news")
        self.assertEqual(update["$set"]["items_seen"], 0)

    def test_failed_ingest_records_no_run(self):
        db = SimpleNamespace(ingest_runs=AsyncMock())
        with patch.dict(internal.JOBS, {"news": AsyncMock(side_effect=RuntimeError("boom"))}), \
             patch("app.routers.internal.get_db", return_value=db), \
             patch("app.routers.internal.invalidate_snapshot"):
            response = make_client().post("/internal/ingest/news")
        self.assertEqual(response.status_code, 502)
        db.ingest_runs.update_one.assert_not_awaited()

    def test_here_job_runs_incidents_and_flow(self):
        async def check():
            with patch("app.ingestion.here_incidents.run", AsyncMock(return_value={"registered": 2})), \
                 patch("app.ingestion.here_flow.run", AsyncMock(return_value={"registered": 3})):
                return await internal.JOBS["here"]("db", None)
        import asyncio
        self.assertEqual(asyncio.run(check()), {"incidents": {"registered": 2}, "flow": {"registered": 3}})


class TokenTests(unittest.TestCase):
    """The real require_scheduler, with Google's signature check stubbed out."""

    def post(self, headers=None, claims=None, error=None):
        verify = patch("app.routers.internal._verify_token",
                       side_effect=error or (lambda token, audience: claims))
        with verify as fake, patch.dict(internal.JOBS, {"tides": AsyncMock(return_value={})}), \
             patch("app.routers.internal.get_db"):
            response = make_client(override=False).post("/internal/ingest/tides", headers=headers or {})
        return response, fake

    def test_valid_scheduler_token(self):
        with settings():
            response, fake = self.post({"Authorization": "Bearer t"}, {"email": SCHEDULER, "email_verified": True})
        self.assertEqual(response.status_code, 200, response.text)
        fake.assert_called_once_with("t", AUDIENCE)

    def test_missing_token_is_401(self):
        with settings():
            self.assertEqual(self.post()[0].status_code, 401)
            self.assertEqual(self.post({"Authorization": "Basic x"})[0].status_code, 401)

    def test_bad_signature_or_audience_is_401(self):
        with settings():
            response, _ = self.post({"Authorization": "Bearer t"}, error=ValueError("Token has wrong audience"))
        self.assertEqual(response.status_code, 401)

    def test_real_google_auth_errors_map_to_401(self):
        from google.auth.exceptions import MalformedError
        with settings():
            response, _ = self.post({"Authorization": "Bearer t"}, error=MalformedError("Wrong number of segments"))
        self.assertEqual(response.status_code, 401)

    def test_other_service_account_is_403(self):
        with settings():
            response, _ = self.post({"Authorization": "Bearer t"},
                                    {"email": "attacker@evil.iam.gserviceaccount.com", "email_verified": True})
            self.assertEqual(response.status_code, 403)
            response, _ = self.post({"Authorization": "Bearer t"}, {"email": SCHEDULER, "email_verified": False})
            self.assertEqual(response.status_code, 403)

    def test_unconfigured_fails_closed(self):
        with settings(audience=""):
            response, fake = self.post({"Authorization": "Bearer t"}, {"email": SCHEDULER, "email_verified": True})
        self.assertEqual(response.status_code, 503)
        fake.assert_not_called()


class RunMetadataTests(unittest.IsolatedAsyncioTestCase):
    """A28: every successful run is recorded, even when it changed nothing."""

    class FakeRuns:
        def __init__(self):
            self.ops = []

        async def update_one(self, query, update, upsert=False):
            self.ops.append((query, update, upsert))
            return SimpleNamespace(matched_count=0, upserted_id=query.get("_id"))

    async def test_nothing_new_still_writes_the_run(self):
        runs = self.FakeRuns()
        started = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
        await internal.record_ingest_run(SimpleNamespace(ingest_runs=runs), "news", started,
                                         {"fetched": 0, "new": 0, "hazards_added": 0,
                                          "hazards_updated": 0})
        query, update, upsert = runs.ops[0]
        self.assertEqual(query, {"_id": "run:news"})
        self.assertTrue(upsert)
        self.assertEqual(update["$set"], {"job": "news", "last_run_at": started,
                                          "items_seen": 0, "items_new": 0,
                                          "hazards_added": 0, "hazards_updated": 0})

    def test_job_specific_counter_names_are_mapped(self):
        started = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(internal.run_metadata("weather", started, {"registered": 15}),
                         {"job": "weather", "last_run_at": started, "hazards_added": 15})
        self.assertEqual(internal.run_metadata("tides", started, None),
                         {"job": "tides", "last_run_at": started})
