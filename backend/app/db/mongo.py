from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

_client: AsyncIOMotorClient | None = None


def get_db() -> AsyncIOMotorDatabase:
    global _client
    settings = get_settings()
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client[settings.mongodb_db_name]


async def init_indexes() -> None:
    """Single source of truth for indexes. Idempotent; runs at app startup and from scripts/init_db.py."""
    db = get_db()

    # routes_cache — TTL 15 min, keyed by hash(origin, destination, departure_bucket)
    await db.routes_cache.create_index("computed_at", expireAfterSeconds=900)

    # intel_cache — per-doc expiry: each doc sets its own expires_at (datetime) on insert
    await db.intel_cache.create_index("expires_at", expireAfterSeconds=0)
    await db.intel_cache.create_index("type")
    await db.intel_cache.create_index("hazard_id")
    await db.intel_cache.create_index([("location", "2dsphere")])

    # hazard_reports — persistent, user-submitted, geo-queryable
    await db.hazard_reports.create_index([("location", "2dsphere")])
    await db.hazard_reports.create_index("reported_at")

    # routines — persistent saved schedules
    await db.routines.create_index("user_id")


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
