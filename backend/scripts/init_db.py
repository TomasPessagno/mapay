"""Create indexes and print what's in Atlas. Run from backend/: python -m scripts.init_db"""
import asyncio

from app.config import get_settings
from app.db.mongo import close_client, get_db, init_indexes

COLLECTIONS = ["routes_cache", "intel_cache", "hazard_reports", "routines"]


async def main() -> None:
    await init_indexes()
    db = get_db()

    print(f"Connected to database: {get_settings().mongodb_db_name}")
    print(f"Collections present: {await db.list_collection_names()}")

    for name in COLLECTIONS:
        indexes = await db[name].index_information()
        print(f"\n{name} indexes:")
        for idx_name, idx_info in indexes.items():
            print(f"  {idx_name}: {idx_info}")

    close_client()


if __name__ == "__main__":
    asyncio.run(main())
