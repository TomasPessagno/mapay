"""Persistence adapter for location-matched news and confirmed Street View results.

Call after extraction/confirmation with the registered source-layer hazard ID.
Satellite imagery is NOT automatically treated as a Street View confirmation.
Retries are safe: a stable intel _id is also the evidence deduplication key.
"""
from datetime import datetime

from app.routing.beliefs import add_evidence, contribution, utc


async def record_evidence(db, hazard_id: str, item: dict, now: datetime,
                          *, street_view_confirmed: bool = False) -> None:
    source = "street_view" if street_view_confirmed else "news"
    if item["type"] != ("satellite_check" if street_view_confirmed else "news"):
        raise ValueError("Evidence type does not match its confirmed source")
    if not await db.intel_cache.find_one({"_id": f"belief:{hazard_id}"}):
        raise ValueError(f"Unknown hazard: {hazard_id}")
    # Namespace evidence documents separately from canonical running beliefs.
    doc = {**item, "_id": f"evidence:{source}:{item['_id']}", "hazard_id": hazard_id,
           "log_odds": contribution(source, item["created_at"], now), "last_updated": utc(now)}
    await db.intel_cache.update_one({"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
    await add_evidence(db, hazard_id, doc["_id"], source, item["created_at"], now)
