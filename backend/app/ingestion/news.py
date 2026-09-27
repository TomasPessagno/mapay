"""Ingestion: Miami local news -> Laya first pass -> Gemini -> hazard evidence.

Pipeline per run (Cloud Scheduler calls it every 15 min via A15):

1. Fetch the five local RSS feeds and five GDELT DOC queries, deduped by URL hash.
2. Claim each URL atomically in ``intel_cache`` (``news_seen:<hash>``, 3-day TTL) so
   an article is never extracted twice. Claims for articles Gemini never answered
   (batch failed, not configured) are released so the next run retries them.
3. Laya drops articles that are not about streets when it is reachable; without a
   reachable Laya every article goes to Gemini (see ``news_triage``).
4. Gemini extracts ``{relevant, category, location_text, starts_at, ends_at,
   severity, summary, confidence}`` per article, batched several per call.
5. ``location_text`` is geocoded with Google, bounded to Miami-Dade; a
   neighbourhood-only mention falls back to A5's polygons. Unplaceable items are
   skipped.
6. Items within ~150 m of a registered belief of the same kind become ``news``
   evidence on it (``record_evidence``). Unmatched crashes / police activity
   register a new ``incident`` hazard with the fixed ``incident_probability`` prior,
   then record the same evidence so the article's link is kept.

Expiry follows AGENTS.md: incident 3 h, flood 12 h, closure = stated end or 24 h,
construction 30 days. Beliefs themselves never expire.
"""
import asyncio
import hashlib
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from shapely.geometry import mapping, shape

from app.agents import news_extraction, news_triage
from app.agents.evidence import record_evidence
from app.config import get_settings
from app.routing.belief_config import BELIEF_CONFIG as C
from app.routing.beliefs import register_hazard, utc

logger = logging.getLogger(__name__)

# overpass-api.de rejects placeholder contacts (contact@example.com) with 406.
USER_AGENT = "MAPAY/0.1 (FIU ShellHacks 2026 hazard map; news pipeline; https://github.com/TomasPessagno/mapay)"

RSS_FEEDS = {
    "nbc6": "https://www.nbcmiami.com/feed/",
    "wlrn": "https://www.wlrn.org/index.rss",
    "local10": "https://www.local10.com/arc/outboundfeeds/rss/?outputType=xml",
    "miami_herald": ("https://www.miamiherald.com/news/local/"
                     "?widgetName=rssfeed&widgetContentId=712014&getXmlFeed=true"),
    "cbs_miami": "https://www.cbsnews.com/miami/latest/rss/main",
}

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERIES = ("miami crash", "miami flood", "miami closure",
                 "miami construction", "miami police")
GDELT_MAX_RECORDS = 75
GDELT_PAUSE_SECONDS = 5.0

GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# West, south, east, north. Hard post-check: Google's bounds only bias results.
MIAMI_DADE_BBOX = (-80.45, 25.55, -80.10, 25.98)

# News is placed where it is reported; beyond ~150 m from a belief it is a new event.
MATCH_RADIUS_DEGREES = 0.0015

SEEN_TTL_DAYS = 3

EXPIRY_HOURS = {"incident": 3, "flood": 12, "closure": 24, "construction": 30 * 24}
DEFAULT_EXPIRY_HOURS = 24


def _clean(text) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))).strip()


def item_id(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]


def parse_time(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return utc(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def evidence_expiry(category: str, ends_at, now: datetime) -> datetime:
    if category == "closure":
        stated_end = parse_time(ends_at)
        if stated_end and utc(stated_end) > utc(now):
            return utc(stated_end)
    return utc(now) + timedelta(hours=EXPIRY_HOURS.get(category, DEFAULT_EXPIRY_HOURS))


def in_miami_dade(lat: float, lng: float) -> bool:
    west, south, east, north = MIAMI_DADE_BBOX
    return west <= lng <= east and south <= lat <= north


def _entry_time(entry: dict, now: datetime) -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is None:
        return utc(now)
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def parse_feed(source: str, payload, now: datetime) -> list[dict]:
    """RSS/Atom feed bytes -> news items; the item link is the dedupe key."""
    items = []
    for entry in feedparser.parse(payload).entries:
        url = entry.get("link")
        if not url:
            continue
        items.append({
            "_id": item_id(url),
            "type": "news",
            "source": source,
            "title": _clean(entry.get("title")),
            "summary": _clean(entry.get("summary") or entry.get("description")),
            "url": url,
            "created_at": _entry_time(entry, now),
        })
    return items


def parse_gdelt(source: str, payload: dict, now: datetime) -> list[dict]:
    items = []
    for article in payload.get("articles") or []:
        url = article.get("url")
        if not url:
            continue
        items.append({
            "_id": item_id(url),
            "type": "news",
            "source": source,
            "domain": article.get("domain"),
            "title": _clean(article.get("title")),
            "summary": "",
            "url": url,
            "created_at": parse_time(article.get("seendate")) or utc(now),
        })
    return items


async def fetch_feeds(client: httpx.AsyncClient, now: datetime) -> list[dict]:
    items = []
    for source, url in RSS_FEEDS.items():
        try:
            response = await client.get(url, headers={"User-Agent": USER_AGENT},
                                        follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError:
            logger.warning("News feed %s failed: %s", source, url)
            continue
        items.extend(parse_feed(source, response.content, now))
    return items


async def fetch_gdelt(client: httpx.AsyncClient, now: datetime) -> list[dict]:
    """GDELT artlist queries, one every GDELT_PAUSE_SECONDS to respect its rate limit."""
    items = []
    for index, query in enumerate(GDELT_QUERIES):
        if index:
            await asyncio.sleep(GDELT_PAUSE_SECONDS)
        params = {"query": query, "mode": "artlist", "format": "json",
                  "maxrecords": str(GDELT_MAX_RECORDS), "sort": "datedesc"}
        try:
            response = await client.get(GDELT_URL, params=params,
                                        headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("GDELT query %r failed", query)
            continue
        items.extend(parse_gdelt("gdelt", payload, now))
    return items


async def fetch_all(client: httpx.AsyncClient, now: datetime) -> list[dict]:
    """RSS + GDELT, deduped by URL (RSS wins when both carry the same link)."""
    seen = set()
    unique = []
    feeds = await fetch_feeds(client, now)
    gdelt = await fetch_gdelt(client, now)
    for item in feeds + gdelt:
        if item["_id"] in seen:
            continue
        seen.add(item["_id"])
        unique.append(item)
    return unique


async def claim_new(db, items: list[dict], now: datetime) -> list[dict]:
    """Atomically claim each URL once; the TTL lets old URLs drop out of the seen set."""
    fresh = []
    for item in items:
        result = await db.intel_cache.update_one(
            {"_id": f"news_seen:{item['_id']}"},
            {"$setOnInsert": {"type": "news_seen", "url": item["url"], "created_at": utc(now),
                              "expires_at": utc(now) + timedelta(days=SEEN_TTL_DAYS)}},
            upsert=True)
        if result.upserted_id:
            fresh.append(item)
    return fresh


async def release_claims(db, item_ids: set[str] | list[str]) -> int:
    """Give back claims Gemini never answered, so the next 15-minute run retries them."""
    ids = sorted(set(item_ids))
    if not ids:
        return 0
    result = await db.intel_cache.delete_many(
        {"_id": {"$in": [f"news_seen:{item_id}" for item_id in ids]}})
    return result.deleted_count


def _google_key() -> str:
    try:
        return get_settings().google_maps_api_key or ""
    except Exception:  # noqa: BLE001 - offline callers need no app settings
        return ""


def neighbourhood_polygon(text: str) -> dict | None:
    """A5's polygon for a mention that is only a neighbourhood name."""
    from app.routers.neighborhoods import get_polygon, search

    matches = search(text)
    if not matches:
        return None
    exact = next((match for match in matches
                  if match["name"].lower() == text.strip().lower()), matches[0])
    polygon = get_polygon(exact["id"])
    if polygon is None or polygon.is_empty:
        return None
    return json.loads(json.dumps(mapping(polygon)))


async def _geocode_point(client: httpx.AsyncClient, text: str, key: str) -> dict | None:
    west, south, east, north = MIAMI_DADE_BBOX
    params = {
        "address": text,
        "components": "administrative_area:FL|country:US",
        "bounds": f"{south},{west}|{north},{east}",
        "key": key,
    }
    try:
        response = await client.get(GEOCODING_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("Geocoding failed for %r", text)
        return None
    for result in payload.get("results") or []:
        location = (result.get("geometry") or {}).get("location") or {}
        lat, lng = location.get("lat"), location.get("lng")
        if lat is None or lng is None or not in_miami_dade(lat, lng):
            continue
        return {"type": "Point", "coordinates": [lng, lat]}
    return None


async def geocode_location(location_text: str, *, client: httpx.AsyncClient | None = None,
                           api_key: str | None = None) -> dict | None:
    """GeoJSON Point from Google (bounded to Miami-Dade) or a neighbourhood Polygon."""
    text = (location_text or "").strip()
    if not text:
        return None
    key = api_key if api_key is not None else _google_key()
    if key:
        owned = client is None
        http = client or httpx.AsyncClient(timeout=15.0)
        try:
            point = await _geocode_point(http, text, key)
        finally:
            if owned:
                await http.aclose()
        if point is not None:
            return point
    return neighbourhood_polygon(text)


async def match_hazard(db, category: str, geometry: dict) -> dict | None:
    """Nearest registered belief of the same kind within MATCH_RADIUS_DEGREES, or None.

    No ``$near``: belief geometry has no 2dsphere index yet, and the per-category
    set is small, so Shapely computes the distance in Python.
    """
    try:
        news_geometry = shape(geometry)
    except Exception:  # noqa: BLE001 - a malformed geocode must not stop the run
        return None
    best, best_distance = None, None
    cursor = db.intel_cache.find({"type": "hazard_belief", "hazard_type": category})
    async for doc in cursor:
        distance = None
        try:
            distance = shape(doc["geometry"]).distance(news_geometry)
        except Exception:  # noqa: BLE001 - a malformed belief is simply not a match
            logger.debug("Skipping malformed belief geometry for %s", doc.get("hazard_id"))
        if distance is not None and distance <= MATCH_RADIUS_DEGREES \
                and (best_distance is None or distance < best_distance):
            best, best_distance = doc, distance
    return best


async def register_incident(db, item: dict, now: datetime) -> str:
    """An unmatched crash / police item becomes a new ``incident`` hazard."""
    hazard_id = f"incident:news-{item['_id']}"
    await register_hazard(db, hazard_id, "incident", item["geometry"], {
        "probability": C["incident_probability"],
        "severity": item.get("severity") or 1,
        "title": item.get("title"),
        "source_url": item.get("url"),
    }, now)
    return hazard_id


def evidence_item(item: dict, now: datetime) -> dict:
    """IntelItem-shaped evidence document for ``record_evidence``."""
    return {
        "_id": item["_id"],
        "type": "news",
        "source": item["source"],
        "title": item["title"],
        "summary": item.get("summary") or item["title"],
        "source_url": item["url"],
        "category": item["category"],
        "severity": item.get("severity") or 1,
        "confidence": item.get("confidence"),
        "relevance": item.get("relevance"),
        "starts_at": parse_time(item.get("starts_at")),
        "ends_at": parse_time(item.get("ends_at")),
        "geometry": item["geometry"],
        "created_at": item["created_at"],
        "expires_at": evidence_expiry(item["category"], item.get("ends_at"), now),
    }


async def run(db, now: datetime | None = None, *, client: httpx.AsyncClient | None = None,
              gemini_client=None, laya_url: str | None = None, laya_api_key: str | None = None,
              geocoding_api_key: str | None = None) -> dict:
    """Fetch, triage, extract and persist one news batch. Returns a summary dict."""
    moment = utc(now or datetime.now(timezone.utc))
    owned = client is None
    http = client or httpx.AsyncClient(timeout=20.0, follow_redirects=True)
    try:
        fetched = await fetch_all(http, moment)
        fresh = await claim_new(db, fetched, moment)
        kept = await news_triage.triage(fresh, client=http, base_url=laya_url,
                                        api_key=laya_api_key)
        outcome = await news_extraction.extract(kept, client=gemini_client)
        released = await release_claims(db, outcome.failed)
        if released:
            logger.warning("Gemini did not answer %d article(s); claims released for the next run",
                           released)
        extracted = outcome.items
        summary = {"fetched": len(fetched), "new": len(fresh), "triaged": len(kept),
                   "dropped": len(fresh) - len(kept), "extracted": len(extracted),
                   "evidence": 0, "incidents": 0, "skipped": 0, "released": released}
        for item in extracted:
            geometry = await geocode_location(item.get("location_text"), client=http,
                                              api_key=geocoding_api_key)
            if geometry is None:
                logger.info("News item unplaceable: %s", item.get("title"))
                summary["skipped"] += 1
                continue
            item["geometry"] = geometry
            category = item["category"]
            linked = await match_hazard(db, category, geometry)
            if linked is not None:
                await record_evidence(db, linked["hazard_id"], evidence_item(item, moment), moment)
                summary["evidence"] += 1
            elif category == "incident":
                hazard_id = await register_incident(db, item, moment)
                await record_evidence(db, hazard_id, evidence_item(item, moment), moment)
                summary["incidents"] += 1
            else:
                logger.info("No registered %s hazard near %r; item skipped", category,
                            item.get("title"))
                summary["skipped"] += 1
        return summary
    finally:
        if owned:
            await http.aclose()


async def main() -> None:
    from app.db.mongo import close_client, get_db

    summary = await run(get_db())
    print(f"News: {summary}")
    close_client()


if __name__ == "__main__":
    asyncio.run(main())
