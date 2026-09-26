"""Offline tests for the news pipeline: saved feeds, stubbed Gemini and Laya clients."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from google.genai import errors

from app.agents import news_extraction, news_triage
from app.ingestion import news
from app.routing.belief_config import BELIEF_CONFIG as C
from app.routing.beliefs import log_odds

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
MISSING = object()

CRASH_URL = "https://www.nbcmiami.com/news/local/crash-i95-ne-125th/"
BAKERY_URL = "https://www.nbcmiami.com/news/local/bakery-little-havana/"
FLOOD_URL = "https://www.wlrn.org/environment/brickell-flooding/"
CONSTRUCTION_URL = "https://www.local10.com/news/local/biscayne-construction/"
HIT_AND_RUN_URL = "https://www.miamiherald.com/news/local/palmetto-hit-and-run/"
POLICE_URL = "https://www.cbsnews.com/miami/news/sr-826-police-activity/"
CLOSURE_URL = "https://www.cbsnews.com/miami/news/sw-8th-closure/"
WATER_MAIN_URL = "https://example.com/news/miami-beach-water-main/"

FEED_FILES = {
    "nbc6": "news_nbc6.xml",
    "wlrn": "news_wlrn.xml",
    "local10": "news_local10.xml",
    "miami_herald": "news_herald.xml",
    "cbs_miami": "news_cbs.xml",
}
FEED_BY_URL = {news.RSS_FEEDS[source]: FIXTURES / name for source, name in FEED_FILES.items()}

ROAD_TITLES = (
    "Crash blocks two lanes",
    "Flooding reported on Brickell Bay Drive",
    "Construction closes a lane",
    "fatal hit-and-run",
    "police activity shuts down",
    "SW 8th Street closed",
)

GEOCODE_POINTS = {
    "I-95 northbound near NE 125th Street": (-80.204, 25.89),
    "Brickell Bay Drive": (-80.191, 25.7605),
    "Biscayne Boulevard near NE 135th Street": (-80.157, 25.9),
    "Palmetto Expressway near Flagler Street": (-80.335, 25.77),
    "SW 8th Street at SW 17th Avenue": (-80.221, 25.7655),
}


def _extraction(url, category, location_text, severity, summary, relevant=True, **extra):
    identifier = news.item_id(url)
    return identifier, {"id": identifier, "relevant": relevant, "category": category,
                        "location_text": location_text, "starts_at": "", "ends_at": "",
                        "severity": severity, "summary": summary, "confidence": 0.8, **extra}


EXTRACTIONS = dict([
    _extraction(CRASH_URL, "incident", "I-95 northbound near NE 125th Street", 3,
                "Crash blocks two lanes on I-95 northbound."),
    _extraction(BAKERY_URL, "event", "", 1, "A bakery opened.", relevant=False),
    _extraction(FLOOD_URL, "flood", "Brickell Bay Drive", 3,
                "King tide flooding was reported on Brickell Bay Drive."),
    _extraction(CONSTRUCTION_URL, "construction", "Biscayne Boulevard near NE 135th Street", 2,
                "A lane is closed for a road-widening project."),
    _extraction(HIT_AND_RUN_URL, "incident", "Palmetto Expressway near Flagler Street", 4,
                "Police are looking for a hit-and-run driver on the Palmetto."),
    _extraction(POLICE_URL, "incident", "SR 826 at Flagler Street", 2,
                "Police activity closed the SR 826 ramp at Flagler Street."),
    _extraction(CLOSURE_URL, "closure", "SW 8th Street at SW 17th Avenue", 3,
                "SW 8th Street is closed for event setup.",
                ends_at="2026-09-26T22:00:00-04:00"),
])


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for doc in self._docs:
            yield doc


def _get_path(doc, path):
    current = doc
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def _set_path(doc, path, value):
    parts = path.split(".")
    current = doc
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


class FakeCollection:
    """Just enough motor semantics for register_hazard / add_evidence / claims."""

    def __init__(self, docs=()):
        self.docs = [dict(doc) for doc in docs]

    @staticmethod
    def _matches(doc, query):
        for key, expected in query.items():
            actual = _get_path(doc, key)
            if isinstance(expected, dict) and "$exists" in expected:
                if (actual is not MISSING) != bool(expected["$exists"]):
                    return False
            elif actual != expected:
                return False
        return True

    async def find_one(self, query):
        for doc in self.docs:
            if self._matches(doc, query):
                return doc
        return None

    def find(self, query):
        return FakeCursor([doc for doc in self.docs if self._matches(doc, query)])

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if self._matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    _set_path(doc, key, value)
                for key, value in update.get("$inc", {}).items():
                    current = _get_path(doc, key)
                    _set_path(doc, key, (0 if current is MISSING else current) + value)
                for key, value in update.get("$max", {}).items():
                    current = _get_path(doc, key)
                    if current is MISSING or value > current:
                        _set_path(doc, key, value)
                return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            new = {key: value for key, value in query.items() if not isinstance(value, dict)}
            for key, value in update.get("$setOnInsert", {}).items():
                _set_path(new, key, value)
            self.docs.append(new)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=new.get("_id"))
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)


class FakeDb(SimpleNamespace):
    def __init__(self, docs=()):
        super().__init__(intel_cache=FakeCollection(docs))


def belief(hazard_id, kind, lat, lng, probability):
    value = log_odds(probability)
    return {"_id": f"belief:{hazard_id}", "type": "hazard_belief", "hazard_id": hazard_id,
            "hazard_type": kind, "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "severity": 3, "prior_log_odds": value, "log_odds": value, "evidence": {},
            "created_at": NOW, "last_updated": NOW}


def seeded_db():
    return FakeDb([
        belief("incident:here-i95", "incident", 25.89, -80.204, 0.8),
        belief("flood:brickell-bay-dr", "flood", 25.7605, -80.191, 0.81),
        belief("construction:biscayne", "construction", 25.9, -80.157, 0.8),
    ])


class FakeModels:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def generate_content(self, model=None, contents=None, config=None):
        self.calls.append(contents or "")
        return SimpleNamespace(text=json.dumps({"items": list(self.results.values())}))


class FakeGenaiClient:
    def __init__(self, results=EXTRACTIONS):
        self.models = FakeModels(results)

    @property
    def aio(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def offline_handler(laya="ok", calls=None):
    calls = [] if calls is None else calls
    gdelt = json.loads((FIXTURES / "news_gdelt.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        url = str(request.url)
        if url in FEED_BY_URL:
            return httpx.Response(200, content=FEED_BY_URL[url].read_bytes())
        if request.url.host == "api.gdeltproject.org":
            return httpx.Response(200, json=gdelt)
        if request.url.host == "laya.test":
            if request.url.path == "/health":
                if laya == "down":
                    return httpx.Response(503)
                return httpx.Response(200, json={"status": "ok"})
            state = json.loads(request.content)["state"]
            probability = 0.9 if any(title in state for title in ROAD_TITLES) else 0.05
            return httpx.Response(200, json={"answers": {"road_problem": {"noul": probability}}})
        if request.url.host == "maps.googleapis.com":
            point = GEOCODE_POINTS.get(request.url.params.get("address", ""))
            if point is None:
                return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})
            lng, lat = point
            return httpx.Response(200, json={"status": "OK", "results": [
                {"geometry": {"location": {"lat": lat, "lng": lng}}}]})
        return httpx.Response(404)
    return handler


async def run_pipeline(db, *, laya="ok", laya_url="http://laya.test", gemini=None):
    gemini = FakeGenaiClient() if gemini is None else gemini
    calls = []
    transport = httpx.MockTransport(offline_handler(laya=laya, calls=calls))
    async with httpx.AsyncClient(transport=transport) as client:
        with patch.object(news, "GDELT_PAUSE_SECONDS", 0):
            summary = await news.run(db, NOW, client=client, gemini_client=gemini,
                                     laya_url=laya_url, laya_api_key="secret",
                                     geocoding_api_key="geo-key")
    return summary, gemini, calls


class ParseTests(unittest.TestCase):
    def test_parse_feed_cleans_html_and_uses_the_url_as_stable_id(self):
        payload = (FIXTURES / "news_nbc6.xml").read_bytes()
        items = news.parse_feed("nbc6", payload, NOW)
        self.assertEqual(len(items), 2)
        crash = items[0]
        self.assertEqual(crash["_id"], news.item_id(CRASH_URL))
        self.assertEqual(crash["type"], "news")
        self.assertEqual(crash["source"], "nbc6")
        self.assertEqual(crash["url"], CRASH_URL)
        self.assertNotIn("<b>", crash["summary"])
        self.assertIn("crash", crash["summary"])
        self.assertEqual(crash["created_at"], datetime(2026, 9, 26, 16, 40, tzinfo=timezone.utc))

    def test_parse_gdelt_maps_seendate_and_skips_articles_without_url(self):
        payload = json.loads((FIXTURES / "news_gdelt.json").read_text(encoding="utf-8"))
        payload["articles"].append({"title": "No link"})
        items = news.parse_gdelt("gdelt", payload, NOW)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["_id"], news.item_id(CRASH_URL))
        self.assertEqual(items[0]["created_at"], datetime(2026, 9, 26, 16, 40, tzinfo=timezone.utc))
        self.assertEqual(items[1]["source"], "gdelt")

    def test_ids_are_stable_across_case_and_whitespace(self):
        self.assertEqual(news.item_id(" HTTPS://Example.com/A "), news.item_id("https://example.com/a"))


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_all_dedupes_urls_across_rss_and_gdelt(self):
        calls = []
        transport = httpx.MockTransport(offline_handler(calls=calls))
        async with httpx.AsyncClient(transport=transport) as client:
            with patch.object(news, "GDELT_PAUSE_SECONDS", 0):
                items = await news.fetch_all(client, NOW)
        self.assertEqual(len(items), 8)
        ids = [item["_id"] for item in items]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(news.item_id(WATER_MAIN_URL), ids)
        self.assertEqual(sum(1 for url in calls if "api.gdeltproject.org" in url),
                         len(news.GDELT_QUERIES))

    async def test_one_broken_feed_does_not_stop_the_others(self):
        def handler(request):
            if "nbcmiami" in str(request.url):
                return httpx.Response(500)
            if request.url.host == "api.gdeltproject.org":
                return httpx.Response(200, json={"articles": []})
            for url, path in FEED_BY_URL.items():
                if str(request.url) == url:
                    return httpx.Response(200, content=path.read_bytes())
            return httpx.Response(404)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch.object(news, "GDELT_PAUSE_SECONDS", 0):
                items = await news.fetch_all(client, NOW)
        self.assertEqual(len(items), 5)  # NBC6's two items are gone


class ClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_new_is_idempotent(self):
        db = FakeDb()
        items = [{"_id": "a", "url": "https://example.com/a"},
                 {"_id": "b", "url": "https://example.com/b"}]
        first = await news.claim_new(db, items, NOW)
        second = await news.claim_new(db, items, NOW)
        self.assertEqual([item["_id"] for item in first], ["a", "b"])
        self.assertEqual(second, [])
        self.assertEqual(db.intel_cache.docs[0]["_id"], "news_seen:a")
        self.assertEqual(db.intel_cache.docs[0]["expires_at"], NOW + timedelta(days=3))


TRIAGE_ARTICLES = [
    {"title": "Crash blocks two lanes on I-95", "summary": "Two lanes blocked."},
    {"title": "New bakery opens in Little Havana", "summary": "Doors open on Calle Ocho."},
]


class TriageTests(unittest.IsolatedAsyncioTestCase):
    def test_question_and_state_are_frozen_for_the_fine_tune(self):
        self.assertEqual(
            news_triage.QUESTION,
            "Is this story about a current or upcoming problem on streets or roads in "
            "Miami-Dade: flooding, a crash, a closure, construction, police activity or a "
            "large event?")
        self.assertEqual(news_triage.state_for({"title": "T", "summary": "S"}), "T\n\nS")
        body = news_triage.request_body({"title": "T", "summary": "S"})
        self.assertEqual(body["model"], "multilingual")
        self.assertEqual(body["questions"]["road_problem"]["type"], "noul")
        self.assertEqual(body["questions"]["road_problem"]["instructions"], news_triage.QUESTION)
        self.assertEqual(news_triage.RELEVANCE_MIN, 0.2)

    async def test_with_laya_keeps_road_articles_and_marks_relevance(self):
        seen = {}

        def handler(request):
            seen["headers"] = dict(request.headers)
            probability = 0.9 if "I-95" in request.content.decode() else 0.05
            return httpx.Response(200, json={"answers": {"road_problem": {"noul": probability}}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            kept = await news_triage.triage(TRIAGE_ARTICLES, client=client,
                                            base_url="http://laya.test", api_key="secret")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["title"], TRIAGE_ARTICLES[0]["title"])
        self.assertEqual(kept[0]["relevance"], 0.9)
        self.assertEqual(seen["headers"]["authorization"], "Bearer secret")
        self.assertEqual(seen["headers"]["ngrok-skip-browser-warning"], "1")

    async def test_threshold_boundary_keeps_exactly_at_relevance_min(self):
        async def triage_with(probability):
            def handler(request):
                return httpx.Response(200, json={"answers": {"road_problem": {"noul": probability}}})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await news_triage.triage(TRIAGE_ARTICLES[:1], client=client, base_url="http://laya.test")

        self.assertEqual(len(await triage_with(news_triage.RELEVANCE_MIN)), 1)
        self.assertEqual(await triage_with(news_triage.RELEVANCE_MIN - 0.01), [])

    async def test_unreachable_laya_keeps_every_article(self):
        def handler(request):
            raise httpx.ConnectError("connection refused")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            kept = await news_triage.triage(TRIAGE_ARTICLES, client=client,
                                            base_url="http://laya.test")
        self.assertEqual(len(kept), 2)

    async def test_health_failure_keeps_every_article(self):
        def handler(request):
            if request.url.path == "/health":
                return httpx.Response(503)
            return httpx.Response(500)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            kept = await news_triage.triage(TRIAGE_ARTICLES, client=client, base_url="http://laya.test")
        self.assertEqual([item["title"] for item in kept], [a["title"] for a in TRIAGE_ARTICLES])

    async def test_article_failure_fails_open(self):
        def handler(request):
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(500)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            kept = await news_triage.triage(TRIAGE_ARTICLES, client=client, base_url="http://laya.test")
        self.assertEqual(len(kept), 2)
        self.assertNotIn("relevance", kept[0])

    async def test_missing_answer_keeps_the_article(self):
        def handler(request):
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(200, json={"answers": {}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            kept = await news_triage.triage(TRIAGE_ARTICLES, client=client, base_url="http://laya.test")
        self.assertEqual(len(kept), 2)

    async def test_no_configured_url_keeps_everything_without_http(self):
        kept = await news_triage.triage(TRIAGE_ARTICLES, base_url="")
        self.assertEqual(len(kept), 2)
        self.assertNotIn("relevance", kept[0])

    def test_endpoint_falls_back_to_empty_without_settings(self):
        with patch.object(news_triage, "get_settings", side_effect=RuntimeError("no settings")):
            self.assertEqual(news_triage.endpoint(), ("", ""))
        settings = SimpleNamespace(laya_url="http://laya.test/", laya_api_key="k")
        with patch.object(news_triage, "get_settings", return_value=settings):
            self.assertEqual(news_triage.endpoint(), ("http://laya.test", "k"))


class ExtractionTests(unittest.IsolatedAsyncioTestCase):
    def article(self, index):
        return {"_id": f"id{index}", "title": f"Article {index}", "summary": "", "source": "test"}

    async def test_extract_batches_calls_and_merges_by_id(self):
        articles = [self.article(index) for index in range(news_extraction.BATCH_SIZE + 1)]
        results = {article["_id"]: {"id": article["_id"], "relevant": True, "category": "incident",
                                    "location_text": "I-95", "starts_at": "", "ends_at": "",
                                    "severity": 3, "summary": "Crash.", "confidence": 0.9}
                   for article in articles}
        client = FakeGenaiClient(results)
        extracted = await news_extraction.extract(articles, client=client)
        self.assertEqual(len(client.models.calls), 2)
        self.assertEqual(len(extracted), news_extraction.BATCH_SIZE + 1)
        self.assertEqual(extracted[0]["category"], "incident")
        self.assertEqual(extracted[0]["severity"], 3)

    async def test_irrelevant_and_unknown_categories_are_dropped(self):
        articles = [self.article(0), self.article(1)]
        results = {
            "id0": {"id": "id0", "relevant": False, "category": "event", "location_text": "",
                    "starts_at": "", "ends_at": "", "severity": 1, "summary": "x", "confidence": 0.5},
            "id1": {"id": "id1", "relevant": True, "category": "aliens", "location_text": "",
                    "starts_at": "", "ends_at": "", "severity": 1, "summary": "x", "confidence": 0.5},
        }
        extracted = await news_extraction.extract(articles, client=FakeGenaiClient(results))
        self.assertEqual(extracted, [])

    async def test_api_error_is_logged_and_skips_the_batch(self):
        class FailingModels:
            async def generate_content(self, **kwargs):
                raise errors.APIError(429, {"error": {"message": "quota"}})

        class FailingClient(FakeGenaiClient):
            def __init__(self):
                super().__init__({})
                self.models = FailingModels()

        with patch.object(news_extraction, "log_api_error") as log:
            extracted = await news_extraction.extract([self.article(0)], client=FailingClient())
        self.assertEqual(extracted, [])
        log.assert_called_once()

    async def test_invalid_json_is_dropped(self):
        class BadModels:
            async def generate_content(self, **kwargs):
                return SimpleNamespace(text="not json")

        class BadClient(FakeGenaiClient):
            def __init__(self):
                super().__init__({})
                self.models = BadModels()

        self.assertEqual(await news_extraction.extract([self.article(0)], client=BadClient()), [])


class GeocodingTests(unittest.IsolatedAsyncioTestCase):
    async def test_point_geocode_is_bounded_to_miami_dade(self):
        captured = {}

        def handler(request):
            captured.update(request.url.params)
            return httpx.Response(200, json={"status": "OK", "results": [
                {"geometry": {"location": {"lat": 25.89, "lng": -80.204}}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            geometry = await news.geocode_location("I-95 northbound near NE 125th Street",
                                                   client=client, api_key="geo-key")
        self.assertEqual(geometry, {"type": "Point", "coordinates": [-80.204, 25.89]})
        self.assertEqual(captured["components"], "administrative_area:FL|country:US")
        self.assertEqual(captured["bounds"], "25.55,-80.45|25.98,-80.1")
        self.assertEqual(captured["key"], "geo-key")

    async def test_result_outside_miami_dade_is_skipped(self):
        def handler(request):
            return httpx.Response(200, json={"status": "OK", "results": [
                {"geometry": {"location": {"lat": 28.54, "lng": -81.38}}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            geometry = await news.geocode_location("Orlando", client=client, api_key="geo-key")
        self.assertIsNone(geometry)

    async def test_neighbourhood_only_mention_uses_a5_polygon(self):
        def handler(request):
            return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            geometry = await news.geocode_location("Brickell", client=client, api_key="geo-key")
        self.assertIn(geometry["type"], ("Polygon", "MultiPolygon"))
        self.assertIn("-80.", json.dumps(geometry["coordinates"]))

    async def test_nothing_placeable_returns_none(self):
        def handler(request):
            return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            geometry = await news.geocode_location("Nowhere Land", client=client, api_key="geo-key")
        self.assertIsNone(geometry)

    async def test_blank_text_returns_none(self):
        self.assertIsNone(await news.geocode_location("  "))


class MatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_nearest_same_kind_belief_within_the_radius_wins(self):
        db = seeded_db()
        match = await news.match_hazard(db, "flood", {"type": "Point",
                                                      "coordinates": [-80.191, 25.76055]})
        self.assertEqual(match["hazard_id"], "flood:brickell-bay-dr")

    async def test_far_or_other_kind_beliefs_do_not_match(self):
        db = seeded_db()
        far = await news.match_hazard(db, "flood", {"type": "Point", "coordinates": [-80.30, 25.80]})
        wrong_kind = await news.match_hazard(db, "incident", {"type": "Point",
                                                              "coordinates": [-80.191, 25.7605]})
        self.assertIsNone(far)
        self.assertIsNone(wrong_kind)


class ExpiryTests(unittest.TestCase):
    def test_expiry_windows_follow_the_spec(self):
        self.assertEqual(news.evidence_expiry("incident", None, NOW), NOW + timedelta(hours=3))
        self.assertEqual(news.evidence_expiry("flood", None, NOW), NOW + timedelta(hours=12))
        self.assertEqual(news.evidence_expiry("construction", None, NOW), NOW + timedelta(days=30))
        self.assertEqual(news.evidence_expiry("weather", None, NOW), NOW + timedelta(hours=24))

    def test_closure_uses_its_stated_end_then_24h(self):
        stated = "2026-09-26T22:00:00-04:00"
        self.assertEqual(news.evidence_expiry("closure", stated, NOW),
                         datetime(2026, 9, 27, 2, 0, tzinfo=timezone.utc))
        self.assertEqual(news.evidence_expiry("closure", None, NOW), NOW + timedelta(hours=24))


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_with_laya_end_to_end(self):
        db = seeded_db()
        summary, gemini, calls = await run_pipeline(db)

        self.assertEqual(summary, {"fetched": 8, "new": 8, "triaged": 6, "dropped": 2,
                                   "extracted": 6, "evidence": 3, "incidents": 1, "skipped": 2})
        self.assertEqual(sum(1 for url in calls if "/v1/systemone" in url), 8)
        self.assertEqual(sum(1 for url in calls if "/health" in url), 1)

        sent = " ".join(gemini.models.calls)
        self.assertIn(news.item_id(CRASH_URL), sent)
        self.assertNotIn(news.item_id(BAKERY_URL), sent)
        self.assertNotIn(news.item_id(WATER_MAIN_URL), sent)

        flood = await db.intel_cache.find_one({"_id": "belief:flood:brickell-bay-dr"})
        self.assertAlmostEqual(flood["log_odds"], log_odds(0.81) + 0.5)
        crash = await db.intel_cache.find_one({"_id": "belief:incident:here-i95"})
        self.assertAlmostEqual(crash["log_odds"], log_odds(0.8) + 0.5)
        construction = await db.intel_cache.find_one({"_id": "belief:construction:biscayne"})
        self.assertAlmostEqual(construction["log_odds"], log_odds(0.8) + 0.5)

        new_id = f"incident:news-{news.item_id(HIT_AND_RUN_URL)}"
        new_incident = await db.intel_cache.find_one({"_id": f"belief:{new_id}"})
        self.assertIsNotNone(new_incident)
        self.assertAlmostEqual(new_incident["log_odds"],
                               log_odds(C["incident_probability"]) + 0.5)

        evidence = [doc for doc in db.intel_cache.docs
                    if str(doc["_id"]).startswith("evidence:news:")]
        self.assertEqual(len(evidence), 4)
        flood_evidence = next(doc for doc in evidence if doc["source_url"] == FLOOD_URL)
        self.assertEqual(flood_evidence["hazard_id"], "flood:brickell-bay-dr")
        self.assertEqual(flood_evidence["expires_at"], NOW + timedelta(hours=12))

    async def test_run_without_laya_sends_everything_to_gemini(self):
        db = seeded_db()
        summary, gemini, calls = await run_pipeline(db, laya_url="")

        self.assertEqual(summary["triaged"], 8)
        self.assertEqual(summary["dropped"], 0)
        self.assertEqual(summary["extracted"], 6)
        self.assertEqual(summary["evidence"], 3)
        self.assertEqual(summary["incidents"], 1)
        self.assertEqual(summary["skipped"], 2)
        self.assertFalse(any("laya.test" in url for url in calls))
        self.assertIn(news.item_id(BAKERY_URL), " ".join(gemini.models.calls))

    async def test_run_with_laya_down_sends_everything_to_gemini(self):
        db = seeded_db()
        summary, gemini, calls = await run_pipeline(db, laya="down")

        self.assertEqual(summary["triaged"], 8)
        self.assertEqual(summary["dropped"], 0)
        self.assertEqual(summary["extracted"], 6)
        self.assertEqual(sum(1 for url in calls if "/health" in url), 1)
        self.assertEqual(sum(1 for url in calls if "/v1/systemone" in url), 0)
        self.assertIn(news.item_id(BAKERY_URL), " ".join(gemini.models.calls))

    async def test_second_run_never_re_extracts_seen_articles(self):
        db = seeded_db()
        await run_pipeline(db)
        gemini = FakeGenaiClient(EXTRACTIONS)
        summary, _, calls = await run_pipeline(db, gemini=gemini)
        self.assertEqual(summary["fetched"], 8)
        self.assertEqual(summary["new"], 0)
        self.assertEqual(summary["extracted"], 0)
        self.assertEqual(gemini.models.calls, [])
        self.assertEqual(sum(1 for url in calls if "/v1/systemone" in url), 0)


if __name__ == "__main__":
    unittest.main()
