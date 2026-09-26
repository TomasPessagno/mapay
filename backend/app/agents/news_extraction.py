"""Gemini structured extraction for news articles.

One call per ``BATCH_SIZE`` articles because AI Studio has per-minute and per-day
request limits. Articles already seen never get here: ``news.py`` claims each URL
atomically before triage. Gemini interprets only -- it never picks a route.
"""
import json
import logging

from google.genai import errors

from app.agents.genai_client import gemini_configured, get_genai_client, log_api_error
from app.config import get_settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 8
FALLBACK_MODEL = "gemini-3.8-flash"

# The legend categories a news item can map to.
CATEGORIES = ("flood", "weather", "construction", "closure", "congestion",
              "no_sidewalk", "pothole", "incident", "event")

FIELDS = ("relevant", "category", "location_text", "starts_at", "ends_at",
          "severity", "summary", "confidence")

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "relevant": {"type": "boolean"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "location_text": {"type": "string"},
                    "starts_at": {"type": "string"},
                    "ends_at": {"type": "string"},
                    "severity": {"type": "integer"},
                    "summary": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["id", "relevant", "category", "location_text",
                             "severity", "summary", "confidence"],
            },
        },
    },
    "required": ["items"],
}

PROMPT = (
    "Extract street-hazard information for the MAPAY hazard map of Miami-Dade County from the "
    "local news articles below. Return one entry per input article with the same \"id\". Set "
    "relevant=false for anything that is not about a current or upcoming problem on streets or "
    "roads in Miami-Dade. category is one of: flood, weather, construction, closure, congestion, "
    "no_sidewalk, pothole, incident, event. location_text is the most specific geocodable place "
    "the article gives (street address, intersection, road name with a city, or neighbourhood); "
    "use an empty string when there is none. starts_at/ends_at are ISO 8601 timestamps only when "
    "the article states them, otherwise empty strings. severity is 1 (minor) to 5 (extreme). "
    "summary is one neutral sentence. confidence is 0 to 1. Never invent places or times."
)


def model_name() -> str:
    try:
        return get_settings().gemini_model or FALLBACK_MODEL
    except Exception:  # noqa: BLE001 - offline callers need no app settings
        return FALLBACK_MODEL


def _parse(text: str | None) -> dict[str, dict]:
    try:
        data = json.loads(text or "{}")
    except (json.JSONDecodeError, TypeError):
        logger.warning("Gemini returned invalid JSON for news extraction")
        return {}
    return {str(item["id"]): item for item in data.get("items") or [] if item.get("id")}


def _merge(batch: list[dict], extracted: dict[str, dict]) -> list[dict]:
    """Flat article+extraction dicts for the relevant, known-category items only."""
    merged = []
    for article in batch:
        result = extracted.get(article["_id"])
        if not result or not result.get("relevant"):
            continue
        if result.get("category") not in CATEGORIES:
            logger.info("Gemini returned unknown category %r for %r",
                        result.get("category"), article.get("title"))
            continue
        merged.append({**article, **{field: result.get(field) for field in FIELDS}})
    return merged


async def _extract_batch(batch: list[dict], *, client=None) -> list[dict]:
    payload = [{"id": article["_id"], "source": article.get("source"),
                "title": article["title"], "summary": article.get("summary", "")}
               for article in batch]
    genai_client = client or get_genai_client()
    try:
        from google.genai import types
        async with genai_client.aio as aio:
            response = await aio.models.generate_content(
                model=model_name(),
                contents=f"{PROMPT}\n{json.dumps(payload, ensure_ascii=False)}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EXTRACTION_SCHEMA,
                ),
            )
    except errors.APIError as exc:
        log_api_error("News extraction", exc)
        return []
    except Exception:
        logger.exception("News extraction failed for a batch of %d articles", len(batch))
        return []
    return _merge(batch, _parse(response.text))


async def extract(articles: list[dict], *, client=None) -> list[dict]:
    """Relevant extracted articles; irrelevant or unparseable ones are dropped."""
    items = [article for article in articles if article.get("title") and article.get("_id")]
    if not items:
        return []
    if client is None and not gemini_configured():
        logger.warning("Gemini is not configured: skipping extraction for %d articles", len(items))
        return []
    extracted = []
    for start in range(0, len(items), BATCH_SIZE):
        extracted.extend(await _extract_batch(items[start:start + BATCH_SIZE], client=client))
    return extracted
