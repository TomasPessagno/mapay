"""Gemini explains a completed deterministic recalculation; it never chooses routes."""
import json
import logging

from google.genai import errors

from app.agents.genai_client import gemini_configured, get_genai_client, log_api_error
from app.config import get_settings

logger = logging.getLogger(__name__)


async def explain_recalculation(changes: list[dict]) -> str:
    fallback = "Route recalculated — hazard confidence crossed the routing threshold following updated evidence."
    if not changes:
        return fallback
    if not gemini_configured():
        return fallback
    try:
        from google.genai import types
        async with get_genai_client().aio as client:
            response = await client.models.generate_content(
                model=get_settings().gemini_model,
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
    except errors.APIError as exc:
        log_api_error("Recalculation explanation", exc)
        return fallback
    except Exception:
        logger.exception("Recalculation explanation failed")
        return fallback


async def brief_route(route: dict, hazards_avoided: list[dict]) -> str:
    # Existing general route briefing remains outside this feature.
    raise NotImplementedError
