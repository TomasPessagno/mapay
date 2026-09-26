"""Laya first pass: one ``noul`` question per article before Gemini reads it.

Laya is the open-source decision model (issue A24) served on Jean's laptop behind a
tunnel, so it may be off. It only filters: category, severity and everything else
still come from Gemini, and a story it drops never reaches the map, which is why the
threshold is deliberately permissive and any failure keeps the article.

The question wording and the ``state`` format are frozen for the A25 fine-tune
(#47): do not reword them.
"""
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

RELEVANCE_MIN = 0.2
HEALTH_TIMEOUT_SECONDS = 10.0
ARTICLE_TIMEOUT_SECONDS = 10.0
MODEL = "multilingual"
QUESTION_KEY = "road_problem"

# Exact wording from issue A16; A25 (#47) fine-tunes Laya on it.
QUESTION = (
    "Is this story about a current or upcoming problem on streets or roads in Miami-Dade: "
    "flooding, a crash, a closure, construction, police activity or a large event?"
)


def endpoint() -> tuple[str, str]:
    """``(base_url, api_key)`` from settings; empty when settings are unavailable.

    Offline callers (tests, scripts) must not need the full app settings just to
    talk to Laya.
    """
    try:
        settings = get_settings()
        return (settings.laya_url or "").rstrip("/"), settings.laya_api_key or ""
    except Exception:  # noqa: BLE001 - missing settings mean "Laya not configured"
        return "", ""


def state_for(article: dict) -> str:
    """The frozen ``state`` format: title, blank line, RSS summary."""
    return f"{article.get('title') or ''}\n\n{article.get('summary') or ''}"


def request_body(article: dict) -> dict:
    return {
        "model": MODEL,
        "state": state_for(article),
        "questions": {QUESTION_KEY: {"type": "noul", "instructions": QUESTION}},
    }


def headers(api_key: str = "") -> dict:
    result = {"ngrok-skip-browser-warning": "1"}
    if api_key:
        result["Authorization"] = f"Bearer {api_key}"
    return result


async def healthy(client: httpx.AsyncClient, base_url: str, api_key: str = "") -> bool:
    try:
        response = await client.get(f"{base_url}/health", headers=headers(api_key),
                                    timeout=HEALTH_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return False
    return response.status_code < 400


async def classify(article: dict, client: httpx.AsyncClient, base_url: str,
                   api_key: str = "") -> float | None:
    """Laya's probability that the article is about a Miami-Dade street problem."""
    response = await client.post(f"{base_url}/v1/systemone", json=request_body(article),
                                 headers=headers(api_key), timeout=ARTICLE_TIMEOUT_SECONDS)
    response.raise_for_status()
    answer = (response.json().get("answers") or {}).get(QUESTION_KEY) or {}
    value = answer.get("noul")
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


async def triage(articles: list[dict], *, client: httpx.AsyncClient | None = None,
                 base_url: str | None = None, api_key: str | None = None) -> list[dict]:
    """Articles for Gemini, each with a Laya ``relevance`` when Laya answered.

    No configured/unreachable Laya -> every article is kept: dropping is only safe
    when the first pass actually ran.
    """
    if not articles:
        return []
    url, key = base_url, api_key
    if url is None or key is None:
        settings_url, settings_key = endpoint()
        url = settings_url if url is None else url
        key = settings_key if key is None else key
    url = (url or "").rstrip("/")
    if not url:
        return list(articles)

    owned = client is None
    http = client or httpx.AsyncClient()
    try:
        if not await healthy(http, url, key):
            logger.warning("Laya unreachable at %s: sending all %d articles to Gemini",
                           url, len(articles))
            return list(articles)
        kept = []
        for article in articles:
            try:
                relevance = await classify(article, http, url, key)
            except (httpx.HTTPError, ValueError):
                logger.warning("Laya failed on %r: keeping the article for Gemini",
                               article.get("title"))
                kept.append(article)
                continue
            if relevance is None:
                kept.append(article)
                continue
            if relevance < RELEVANCE_MIN:
                logger.info("Laya dropped %s (p=%.3f): %s",
                            article.get("source"), relevance, article.get("title"))
                continue
            kept.append({**article, "relevance": relevance})
        return kept
    finally:
        if owned:
            await http.aclose()
