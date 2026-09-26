"""Gemini explains a completed deterministic recalculation; it never chooses routes."""
import json
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


async def explain_recalculation(changes: list[dict]) -> str:
    fallback = "Route recalculated — hazard confidence crossed the routing threshold following updated evidence."
    if not changes:
        return fallback
    settings = get_settings()
    if not settings.gemini_api_key:
        return fallback
    try:
        from google import genai
        from google.genai import types
        async with genai.Client(api_key=settings.gemini_api_key).aio as client:
            response = await client.models.generate_content(
                model="gemini-2.5-flash",
                contents="Explain this already-completed route recalculation in one short sentence. "
                         "Use only supplied facts, describe probability changes and evidence sources. "
                         "Do not make any routing decision or claim a hazard is certain. Data: " + json.dumps(changes),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema={"type": "object", "properties": {"explanation": {"type": "string"}},
                                     "required": ["explanation"]},
                ),
            )
        return json.loads(response.text)["explanation"]
    except Exception:
        logger.exception("Recalculation explanation failed")
        return fallback


async def brief_route(route: dict, hazards_avoided: list[dict]) -> str:
    # Existing general route briefing remains outside this feature.
    raise NotImplementedError
