"""Gemini vision check of Sentinel-2 before/after chips: is this a construction site? (#16)

Only Copernicus Sentinel imagery goes to Gemini (never Google Maps tiles or Street View: Google's
terms forbid it). Gemini answers a yes/no with a confidence and a one-line description; it never
decides routing. Without Gemini the site stays unconfirmed (no evidence is added).
"""
import json
import logging

from google.genai import errors

from app.agents.genai_client import gemini_configured, get_genai_client, log_api_error
from app.config import get_settings

logger = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "is_construction": {"type": "boolean"},
        "confidence": {"type": "number", "description": "0 to 1"},
        "description": {"type": "string", "description": "One short sentence: what changed"},
    },
    "required": ["is_construction", "confidence", "description"],
}
PROMPT = (
    "Two Sentinel-2 true-colour chips of the same ~500 m square in Miami-Dade, 10 m pixels: the FIRST "
    "is from a year ago, the SECOND is recent. Is the change an active construction site (cleared land, "
    "new building pad or frame, road widening, bare soil with equipment tracks)? Clouds, shadows, "
    "seasonal vegetation, flooding or different lighting are NOT construction. Answer as JSON. "
    "Context: {context}"
)


def parse(raw: dict | None) -> dict | None:
    if not raw or "is_construction" not in raw:
        return None
    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {"is_construction": bool(raw["is_construction"]), "confidence": confidence,
            "description": str(raw.get("description") or "").strip()[:300]}


async def check_site(before_png: bytes, after_png: bytes, context: str = "") -> dict | None:
    """{is_construction, confidence, description}, or None when Gemini can't answer."""
    if not gemini_configured():
        return None
    try:
        from google.genai import types
        async with get_genai_client().aio as client:
            response = await client.models.generate_content(
                model=get_settings().gemini_model,
                contents=[PROMPT.format(context=context or "none"),
                          types.Part.from_bytes(data=before_png, mime_type="image/png"),
                          types.Part.from_bytes(data=after_png, mime_type="image/png")],
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=SCHEMA))
        return parse(json.loads(response.text))
    except errors.APIError as exc:
        log_api_error("Satellite construction check", exc)
    except Exception:
        logger.exception("Satellite construction check failed")
    return None


async def check_locations(locations: list[dict]) -> list[dict]:
    """[{..., before_png, after_png, context}] → the same dicts with a `check` result."""
    results = []
    for location in locations:
        check = await check_site(location["before_png"], location["after_png"], location.get("context", ""))
        results.append({**location, "check": check})
    return results
