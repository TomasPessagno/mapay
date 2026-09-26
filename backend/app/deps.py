"""Anonymous identity: every user endpoint reads X-Device-Id and knows its caller."""
from datetime import datetime, timezone

from fastapi import Header, HTTPException, status

from app.db.mongo import get_db

DEFAULT_PREFERENCES: dict = {
    "categories": {
        "flood": "avoid",
        "closure": "avoid",
        "construction": "prefer_avoid",
        "congestion": "prefer_avoid",
        "incident": "prefer_avoid",
        "weather": "prefer_avoid",
        "pothole": "ignore",
        "no_sidewalk": "ignore",
        "event": "ignore",
    },
    "avoid_neighborhoods": [],
    "avoid_tolls": False,
    "avoid_highways": False,
    "nav_app": "google_maps",
}


def default_preferences() -> dict:
    categories = dict(DEFAULT_PREFERENCES["categories"])
    return {**DEFAULT_PREFERENCES, "categories": categories, "avoid_neighborhoods": []}


async def current_user(
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
) -> dict:
    device_id = (x_device_id or "").strip()
    if not device_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Device-Id header")
    db = get_db()
    await db.users.update_one(
        {"_id": device_id},
        {"$setOnInsert": {"preferences": default_preferences(), "created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    user = await db.users.find_one({"_id": device_id})
    if user is None:  # pragma: no cover - only if the upsert was rolled back between the two calls
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not load user")
    return user
