"""Saved places (MMC, BBC, ...) scoped to the X-Device-Id user. Shape: frontend/public/mocks/places.json."""
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.db.models import PlaceIn
from app.db.mongo import get_db
from app.deps import current_user

router = APIRouter(prefix="/places", tags=["places"])


def to_doc(place: PlaceIn, user: dict, place_id: str) -> dict:
    return {"_id": place_id, "user_id": user["_id"], "name": place.name,
            "google_place_id": place.google_place_id, "address": place.address, "location": place.point(),
            "refreshed_at": datetime.now(timezone.utc)}


@router.get("")
async def list_places(user: Annotated[dict, Depends(current_user)]):
    return await get_db().places.find({"user_id": user["_id"]}).to_list(length=200)


@router.post("")
async def save_place(place: PlaceIn, user: Annotated[dict, Depends(current_user)]):
    """Create, or replace when `_id` names one of this device's places."""
    db = get_db()
    place_id = place.id or str(uuid4())
    existing = await db.places.find_one({"_id": place_id})
    if existing and existing.get("user_id") != user["_id"]:
        raise HTTPException(404, "Place not found")
    doc = to_doc(place, user, place_id)
    if existing:
        await db.places.replace_one({"_id": place_id, "user_id": user["_id"]}, doc)
    else:
        await db.places.insert_one(doc)
    return doc


@router.put("/{place_id}")
async def update_place(place_id: str, place: PlaceIn, user: Annotated[dict, Depends(current_user)]):
    db = get_db()
    if not await db.places.find_one({"_id": place_id, "user_id": user["_id"]}):
        raise HTTPException(404, "Place not found")
    doc = to_doc(place, user, place_id)
    await db.places.replace_one({"_id": place_id, "user_id": user["_id"]}, doc)
    return doc


@router.delete("/{place_id}")
async def delete_place(place_id: str, user: Annotated[dict, Depends(current_user)]):
    db = get_db()
    in_use = await db.routines.find_one({"user_id": user["_id"], "$or": [
        {"legs.from_place": place_id}, {"legs.to_place": place_id}]})
    if in_use:
        raise HTTPException(409, f"Place is used by routine {in_use.get('name') or in_use['_id']}")
    result = await db.places.delete_one({"_id": place_id, "user_id": user["_id"]})
    if not result.deleted_count:
        raise HTTPException(404, "Place not found")
    return {"deleted": place_id}
