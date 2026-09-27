"""The calling device's default preferences. Shape: frontend/public/mocks/preferences.json."""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.db.models import Preferences
from app.db.mongo import get_db
from app.deps import current_user
from app.routing.scoring import merge_preferences

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/preferences")
async def get_preferences(user: Annotated[dict, Depends(current_user)]):
    # Merged over the AGENTS.md defaults, so a category added later still has a value.
    return merge_preferences(user.get("preferences"))


@router.put("/preferences")
async def put_preferences(preferences: Preferences, user: Annotated[dict, Depends(current_user)]):
    merged = merge_preferences(preferences.model_dump())
    await get_db().users.update_one({"_id": user["_id"]}, {"$set": {"preferences": merged}})
    return merged
