"""Best time to leave inside a window leg (#39): "Leave at 17:45: 24 min instead of 38".

Departures every 15 min across the window are scored like /route (A6): the Routes API's predicted
duration for that future departure time plus hazard penalties with the beliefs evaluated at that
time. Results are cached per leg and local day, and only windows starting within the next 48 h are
checked, to keep Routes API usage small (~9 calls per leg per day).
"""
import asyncio
import json
import time
from datetime import datetime, timedelta

from app.routing.beliefs import belief_at
from app.routing.engine import route_alternatives
from app.routing.google_routes import NoRouteFound, RoutesApiError
from app.routing.scoring import rank

STEP = timedelta(minutes=15)
HORIZON = timedelta(hours=48)
CACHE_SECONDS = 6 * 3600
MAX_PARALLEL = 5
_cache: dict[str, tuple[float, dict | None]] = {}


def departures(start: datetime, end: datetime, now: datetime) -> list[datetime]:
    """start, start+15, ..., end, skipping any already in the past."""
    times, t = [], start
    while t <= end:
        if t > now:
            times.append(t)
        t += STEP
    return times


async def best_departure(origin, destination, window: tuple[datetime, datetime], preferences: dict,
                         belief_docs: list[dict], now: datetime) -> dict | None:
    """{best_departure_at, duration_s, window_start_duration_s, saving_s} or None (too far ahead,
    window over, or no route)."""
    start, end = window
    if start - now > HORIZON or end <= now:
        return None
    key = json.dumps([origin, destination, preferences, start.isoformat(), end.isoformat()], sort_keys=True,
                     default=str)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    limit = asyncio.Semaphore(MAX_PARALLEL)

    async def score(departure: datetime):
        async with limit:
            try:
                alternatives = await route_alternatives(origin, destination, departure, preferences["avoid_tolls"],
                                                        preferences["avoid_highways"], "drive")
            except (NoRouteFound, RoutesApiError):
                return None
        hazards = [belief_at(doc, departure) for doc in belief_docs]  # decay evaluated at that departure
        return departure, rank(alternatives, hazards, preferences)[0]

    scored = [s for s in await asyncio.gather(*(score(t) for t in departures(start, end, now))) if s]
    result = None
    if scored:
        best_time, best = min(scored, key=lambda item: (item[1]["score"], item[0]))
        first_time, first = scored[0]
        result = {"best_departure_at": best_time, "duration_s": best["duration_s"],
                  "window_start_duration_s": first["duration_s"],
                  "saving_s": max(0, first["duration_s"] - best["duration_s"]) if best_time != first_time else 0}
    _cache[key] = (time.monotonic(), result)
    return result


def clear_cache() -> None:
    _cache.clear()
