"""Precomputed heads-up briefings (#40): legs departing within the next 2 h get their
/routines/upcoming item computed ahead of time, so the app, notification refresh and widget load
instantly. Cloud Scheduler runs this every 10 min (`/internal/ingest/briefings`). The `briefings`
collection has a 1-day TTL on computed_at (db/mongo.py).
"""
from datetime import datetime, timedelta, timezone

from app.briefings.builder import build_items
from app.routing.beliefs import utc
from app.routing.pre_route import current_hazards
from app.scheduling.occurrences import Occurrence, upcoming

AHEAD = timedelta(hours=2)
FRESH = timedelta(minutes=15)  # the job runs every 10 min


def briefing_id(routine_id: str, leg: int, local_date: str) -> str:
    return f"{routine_id}:{leg}:{local_date}"


def occurrence_id(occ: Occurrence) -> str:
    return briefing_id(occ.routine_id, occ.leg, occ.local_date.isoformat())


def item_id(item: dict) -> str:
    return briefing_id(item["routine_id"], item["leg"], item["local_date"])


def compact_item(item: dict) -> dict:
    """What the widget gets (?compact=1): two hazards, no image."""
    return {**item, "top_hazards": item["top_hazards"][:2], "image_url": None}


async def fresh_briefings(db, occurrences: list[Occurrence], now: datetime) -> dict[str, dict]:
    """Stored items computed within FRESH for these (non-demo) occurrences, by briefing id."""
    ids = [occurrence_id(o) for o in occurrences if not o.demo]
    if not ids:
        return {}
    docs = await db.briefings.find({"_id": {"$in": ids}}).to_list(length=None)
    return {d["_id"]: d["item"] for d in docs if utc(d["computed_at"]) >= now - FRESH}


async def run(db, now: datetime | None = None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    routines = await db.routines.find({"active": True}).to_list(length=None)
    by_user: dict[str, list[dict]] = {}
    for routine in routines:
        by_user.setdefault(routine["user_id"], []).append(routine)
    hazards = None
    stored = 0
    for user_id, docs in by_user.items():
        soon = [o for o in upcoming(docs, [], now, days=1) if o.departure_at - now <= AHEAD]
        if not soon:
            continue
        hazards = hazards if hazards is not None else await current_hazards(db, now)
        user = await db.users.find_one({"_id": user_id})
        items = await build_items(db, soon, {d["_id"]: d for d in docs}, user, hazards, False, now)
        for item in items:
            if item.get("route_error"):
                continue  # don't pin a failure for 15 min; the next request retries
            await db.briefings.replace_one({"_id": item_id(item)}, {
                "_id": item_id(item), "routine_id": item["routine_id"], "leg": item["leg"],
                "local_date": item["local_date"], "user_id": user_id, "departure_at": item["departure_at"],
                "item": item, "computed_at": now}, upsert=True)
            stored += 1
    return {"users": len(by_user), "briefings": stored}
