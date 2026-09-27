import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from shapely.geometry import box, mapping

from app.agents import satellite_check
from app.ingestion import earth_engine_s2 as s2
from app.routers import internal
from app.routing.beliefs import log_odds
from tests.test_satellite_floods import FakeIntelCache

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
PERMIT_SITE = box(-80.2000, 25.7700, -80.1980, 25.7715)  # a City permit polygon
NEW_SITE = box(-80.3500, 25.6500, -80.3470, 25.6520)  # nothing registered there
PNG = b"\x89PNG fake"


def permit(cache, hazard_id, geometry, probability=0.8, kind="construction"):
    value = log_odds(probability)
    cache.docs[f"belief:{hazard_id}"] = {
        "_id": f"belief:{hazard_id}", "type": "hazard_belief", "hazard_id": hazard_id, "hazard_type": kind,
        "geometry": mapping(geometry), "severity": 3, "prior_log_odds": value, "log_odds": value,
        "evidence": {}, "created_at": NOW, "last_updated": NOW, "properties": {"title": "Roadway project"}}


def chips_client(calls):
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=PNG)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def site(geometry, hazard_id=None):
    return {"geometry": geometry, "before_url": "https://ee.example/before.png",
            "after_url": "https://ee.example/after.png", "hazard_id": hazard_id}


class ApplyTests(unittest.IsolatedAsyncioTestCase):
    async def run_sites(self, cache, sites, verdict):
        calls = []
        with patch("app.ingestion.earth_engine_s2.check_site", AsyncMock(return_value=verdict)) as check:
            result = await s2.confirm_and_apply(SimpleNamespace(intel_cache=cache), sites, NOW,
                                                chips_client(calls), "20261012")
        return result, check, calls

    async def test_confirmed_site_near_a_permit_adds_evidence(self):
        cache = FakeIntelCache()
        permit(cache, "city:permit:1", PERMIT_SITE)
        verdict = {"is_construction": True, "confidence": 0.9, "description": "New building pad on cleared lot"}
        result, check, calls = await self.run_sites(cache, [site(PERMIT_SITE.buffer(0.0003))], verdict)
        self.assertEqual((result["confirmed"], result["permits_confirmed"], result["new_hazards"]), (1, 1, 0))
        belief = cache.docs["belief:city:permit:1"]
        self.assertAlmostEqual(belief["log_odds"], log_odds(0.8) + 1.0)
        evidence = next(d for d in cache.docs.values() if d.get("type") == "satellite_check")
        self.assertEqual((evidence["before_image_url"], evidence["after_image_url"]),
                         ("https://ee.example/before.png", "https://ee.example/after.png"))  # chips linked
        self.assertIn("New building pad", evidence["title"])
        self.assertEqual(check.await_args.args[:2], (PNG, PNG))
        self.assertEqual(len(calls), 2)

    async def test_confirmed_site_elsewhere_registers_construction(self):
        cache = FakeIntelCache()
        verdict = {"is_construction": True, "confidence": 0.8, "description": "Road widening"}
        result, _, _ = await self.run_sites(cache, [site(NEW_SITE)], verdict)
        self.assertEqual(result["new_hazards"], 1)
        new = next(d for d in cache.docs.values() if d.get("hazard_id", "").startswith("s2:"))
        self.assertEqual(new["hazard_type"], "construction")
        self.assertAlmostEqual(new["prior_log_odds"], log_odds(0.7))
        self.assertEqual(new["properties"]["description"], "Road widening")

    async def test_rejected_low_confidence_or_no_gemini_adds_nothing(self):
        for verdict in ({"is_construction": False, "confidence": 0.9, "description": "clouds"},
                        {"is_construction": True, "confidence": 0.4, "description": "maybe"}, None):
            cache = FakeIntelCache()
            permit(cache, "city:permit:1", PERMIT_SITE)
            result, _, _ = await self.run_sites(cache, [site(PERMIT_SITE), site(NEW_SITE)], verdict)
            self.assertEqual((result["confirmed"], result["new_hazards"]), (0, 0), verdict)
            self.assertEqual(cache.docs["belief:city:permit:1"]["evidence"], {})

    async def test_permit_mode_confirms_that_permit(self):
        cache = FakeIntelCache()
        permit(cache, "city:permit:9", PERMIT_SITE)
        verdict = {"is_construction": True, "confidence": 0.95, "description": "Foundation work"}
        result, _, _ = await self.run_sites(cache, [site(PERMIT_SITE, hazard_id="city:permit:9")], verdict)
        self.assertEqual(result["permits_confirmed"], 1)
        self.assertEqual(len(cache.docs["belief:city:permit:9"]["evidence"]), 1)


class PermitSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_active_city_construction_largest_first(self):
        cache = FakeIntelCache()
        permit(cache, "city:permit:small", box(-80.20, 25.77, -80.199, 25.771))
        permit(cache, "city:permit:big", box(-80.30, 25.70, -80.29, 25.71))
        permit(cache, "city:permit:pending", box(-80.31, 25.70, -80.28, 25.73), probability=0.2)
        permit(cache, "city:permit:closure", box(-80.32, 25.70, -80.27, 25.74), kind="closure")
        permit(cache, "here:1", box(-80.33, 25.70, -80.26, 25.75))
        chosen = await s2.active_permits(SimpleNamespace(intel_cache=cache))
        self.assertEqual([d["hazard_id"] for d in chosen], ["city:permit:big", "city:permit:small"])


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_detect_mode_clears_sites_it_no_longer_confirms(self):
        cache = FakeIntelCache()
        db = SimpleNamespace(intel_cache=cache)
        verdict = {"is_construction": True, "confidence": 0.8, "description": "Road widening"}
        with patch("app.ingestion.earth_engine_s2._detect_blocking", return_value=[site(NEW_SITE)]), \
             patch("app.ingestion.earth_engine_s2.check_site", AsyncMock(return_value=verdict)):
            first = await s2.run(db, NOW, client=chips_client([]))
        with patch("app.ingestion.earth_engine_s2._detect_blocking", return_value=[]):
            second = await s2.run(db, NOW, client=chips_client([]))
        self.assertEqual((first["new_hazards"], second["cleared"]), (1, 1))

    async def test_job_falls_back_to_permit_mode(self):
        calls = []

        async def fake_run(db, now, mode="detect", client=None):
            calls.append(mode)
            if mode == "detect":
                raise RuntimeError("Earth Engine unavailable")
            return {"mode": mode}

        with patch("app.ingestion.earth_engine_s2.run", fake_run):
            self.assertEqual(await internal.JOBS["s2"]("db", NOW), {"mode": "permits"})
        self.assertEqual(calls, ["detect", "permits"])


class EarthEngineGraphTests(unittest.TestCase):
    def test_build_uses_s2_sr_cloud_mask_ndvi_and_water(self):
        ee = MagicMock()
        s2.build_candidates(ee, NOW)
        ee.ImageCollection.assert_any_call("COPERNICUS/S2_SR_HARMONIZED")
        ee.Image.assert_called_with("JRC/GSW1_4/GlobalSurfaceWater")

    def test_chips_are_true_colour_thumbnails(self):
        ee = MagicMock()
        before, after = MagicMock(), MagicMock()
        s2.chip_urls(ee, before, after, NEW_SITE)
        before.visualize.assert_called_with(bands=["B4", "B3", "B2"], min=0, max=0.3)
        params = after.visualize.return_value.getThumbURL.call_args.args[0]
        self.assertEqual((params["dimensions"], params["format"]), (256, "png"))


class GeminiCheckTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_clamps_and_validates(self):
        self.assertEqual(satellite_check.parse({"is_construction": 1, "confidence": 3, "description": " x "}),
                         {"is_construction": True, "confidence": 1.0, "description": "x"})
        self.assertIsNone(satellite_check.parse({"confidence": 0.5}))
        self.assertEqual(satellite_check.parse({"is_construction": False, "confidence": "?"})["confidence"], 0.0)

    async def test_without_gemini_no_answer(self):
        with patch("app.agents.satellite_check.gemini_configured", return_value=False):
            self.assertIsNone(await satellite_check.check_site(PNG, PNG))

    async def test_sends_both_chips_with_the_schema(self):
        response = SimpleNamespace(text='{"is_construction": true, "confidence": 0.8, "description": "Pad"}')
        aio = MagicMock()
        aio.models.generate_content = AsyncMock(return_value=response)
        client = MagicMock()
        client.aio.__aenter__ = AsyncMock(return_value=aio)
        client.aio.__aexit__ = AsyncMock(return_value=False)
        with patch("app.agents.satellite_check.gemini_configured", return_value=True), \
             patch("app.agents.satellite_check.get_settings", return_value=SimpleNamespace(gemini_model="m")), \
             patch("app.agents.satellite_check.get_genai_client", return_value=client):
            result = await satellite_check.check_site(b"before", b"after", "Roadway project")
        self.assertEqual(result["description"], "Pad")
        kwargs = aio.models.generate_content.await_args.kwargs
        self.assertEqual(len(kwargs["contents"]), 3)  # prompt + before + after
        self.assertIn("Roadway project", kwargs["contents"][0])
