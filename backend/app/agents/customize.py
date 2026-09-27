"""Gemini for "Customize with a prompt": prompt → constraints JSON, and router output → explanation.

Gemini never picks a route: it only turns words into constraints, and later explains what the
deterministic router did (AGENTS.md › Customize with a prompt). Two calls per request at most.
Without Gemini (unconfigured, quota, error) a small keyword parser and a template take over, so
the feature degrades instead of failing.
"""
import json
import logging
import re

from google.genai import errors

from app.agents.genai_client import gemini_configured, get_genai_client, log_api_error
from app.config import get_settings
from app.routers.neighborhoods import search

logger = logging.getLogger(__name__)

CATEGORIES = ["flood", "weather", "construction", "closure", "congestion", "no_sidewalk", "pothole", "incident",
              "event"]
EMPTY = {"add_stops": [], "avoid_categories": [], "avoid_neighborhoods": [], "avoid_roads": [],
         "avoid_tolls": None, "avoid_highways": None, "depart_at": None, "arrive_by": None,
         "travel_mode": None, "save_as_preference": False}

CONSTRAINTS_SCHEMA = {
    "type": "object",
    "properties": {
        "add_stops": {"type": "array", "items": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What to search for, e.g. 'Starbucks' or 'gas station'"}},
            "required": ["query"]}},
        "avoid_categories": {"type": "array", "items": {"type": "string", "enum": CATEGORIES}},
        "avoid_neighborhoods": {"type": "array", "items": {"type": "string"},
                                "description": "Neighbourhood or city names as the user said them"},
        "avoid_roads": {"type": "array", "items": {"type": "string"},
                        "description": "Official road ref when known (e.g. 'SR 826' for the Palmetto), else the name"},
        "avoid_tolls": {"type": "boolean", "nullable": True},
        "avoid_highways": {"type": "boolean", "nullable": True},
        "depart_at": {"type": "string", "nullable": True, "description": "HH:MM, 24 h, local time"},
        "arrive_by": {"type": "string", "nullable": True, "description": "HH:MM, 24 h, local time"},
        "travel_mode": {"type": "string", "nullable": True, "enum": ["drive", "walk"]},
        "save_as_preference": {"type": "boolean",
                               "description": "True only for lasting rules such as 'always avoid Brickell'"},
    },
    "required": list(EMPTY),
}

INSTRUCTIONS = (
    "You turn a Miami driver's request into routing constraints. Output only the constraints JSON. "
    "Never choose or describe a route. Use null / empty lists for anything the request doesn't mention. "
    "Hazard categories: " + ", ".join(CATEGORIES) + ". Miami road nicknames: the Palmetto = SR 826, "
    "the Dolphin = SR 836, the Turnpike = Florida's Turnpike, US-1 = South Dixie Highway, I-95, Biscayne Blvd."
)


def normalise(raw: dict) -> dict:
    """Schema defaults, types and HH:MM checks, whatever produced the dict."""
    out = {**EMPTY, **{k: v for k, v in (raw or {}).items() if k in EMPTY}}
    out["add_stops"] = [{"query": s["query"].strip()} for s in out["add_stops"] or []
                        if isinstance(s, dict) and str(s.get("query", "")).strip()][:3]
    out["avoid_categories"] = [c for c in out["avoid_categories"] or [] if c in CATEGORIES]
    for key in ("avoid_neighborhoods", "avoid_roads"):
        out[key] = [str(v).strip() for v in out[key] or [] if str(v).strip()]
    for key in ("depart_at", "arrive_by"):
        if out[key] is not None and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(out[key])):
            out[key] = None
    if out["travel_mode"] not in (None, "drive", "walk"):
        out["travel_mode"] = None
    out["save_as_preference"] = bool(out["save_as_preference"])
    return out


ROAD_NICKNAMES = {"palmetto": "SR 826", "dolphin": "SR 836", "turnpike": "Florida's Turnpike", "i-95": "I-95",
                  "i95": "I-95", "us-1": "US 1", "us 1": "US 1", "biscayne": "Biscayne Boulevard"}
CATEGORY_WORDS = {"flood": "flood", "construction": "construction", "roadwork": "construction", "closure": "closure",
                  "closed": "closure", "traffic": "congestion", "congestion": "congestion", "pothole": "pothole",
                  "crash": "incident", "accident": "incident", "police": "incident", "rain": "weather"}


def keyword_constraints(prompt: str) -> dict:
    """Fallback parser for when Gemini is unavailable: common phrasings only."""
    text = prompt.lower()
    out = dict(EMPTY)
    stops = re.findall(r"\bstop (?:at|by|for) (?:a |an |the |some )?([a-z0-9' &-]+?)(?=,| and | then |$|\.)", text)
    out["add_stops"] = [{"query": s.strip()} for s in stops if s.strip()]
    avoid_part = " ".join(re.findall(r"(?:avoid|stay off|stay away from|skip|no|without|around)\s+([^,.;]+)", text))
    out["avoid_roads"] = sorted({ref for nick, ref in ROAD_NICKNAMES.items() if nick in avoid_part})
    out["avoid_categories"] = sorted({c for word, c in CATEGORY_WORDS.items() if word in avoid_part})
    out["avoid_neighborhoods"] = [n["name"] for n in search() if len(n["name"]) > 3
                                  and re.search(rf"\b{re.escape(n['name'].lower())}\b", avoid_part)]
    if "toll" in avoid_part:
        out["avoid_tolls"] = True
    if "highway" in avoid_part or "expressway" in avoid_part:
        out["avoid_highways"] = True
    if re.search(r"\b(walk|walking|on foot)\b", text):
        out["travel_mode"] = "walk"
    if re.search(r"\b(always|from now on|every time)\b", text):
        out["save_as_preference"] = True
    return normalise(out)


async def _generate(contents: str, schema: dict) -> dict | None:
    from google.genai import types
    async with get_genai_client().aio as client:
        response = await client.models.generate_content(
            model=get_settings().gemini_model, contents=contents,
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema))
    return json.loads(response.text)


async def extract_constraints(prompt: str, context: dict) -> tuple[dict, str]:
    """(constraints, "gemini" | "keywords")."""
    if gemini_configured():
        try:
            raw = await _generate(f"{INSTRUCTIONS}\nTrip: {json.dumps(context)}\nRequest: {prompt}",
                                  CONSTRAINTS_SCHEMA)
            return normalise(raw), "gemini"
        except errors.APIError as exc:
            log_api_error("Customize constraints", exc)
        except Exception:
            logger.exception("Customize constraints failed; using the keyword parser")
    return keyword_constraints(prompt), "keywords"


def template_explanation(facts: dict) -> str:
    parts = []
    if facts.get("stops"):
        parts.append("Added a stop at " + " and ".join(facts["stops"]))
    if facts.get("avoided"):
        parts.append(("kept you off " if parts else "Kept you off ") + ", ".join(facts["avoided"]))
    text = (", ".join(parts) if parts else "Recalculated the route with your changes") + "."
    delta = facts.get("minutes_delta")
    if delta:
        text += f" About {abs(delta)} min {'longer' if delta > 0 else 'shorter'} than before."
    if facts.get("unmet"):
        text += " Couldn't apply: " + "; ".join(facts["unmet"]) + "."
    return text


async def explain(facts: dict) -> str:
    """1–2 sentences written only from the router's output."""
    if gemini_configured():
        try:
            raw = await _generate(
                "Explain this already-computed route change to the driver in 1-2 short sentences. Use only "
                "these facts; don't invent roads, times or hazards, and don't recommend anything else. "
                "Facts: " + json.dumps(facts),
                {"type": "object", "properties": {"explanation": {"type": "string"}}, "required": ["explanation"]})
            if raw and raw.get("explanation"):
                return raw["explanation"].strip()
        except errors.APIError as exc:
            log_api_error("Customize explanation", exc)
        except Exception:
            logger.exception("Customize explanation failed; using the template")
    return template_explanation(facts)
