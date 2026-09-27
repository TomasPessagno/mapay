"""Routines CRUD (legs between saved places) + the pre-route check. Everything is scoped to the
X-Device-Id user. Shape: frontend/public/mocks/routines.json."""
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.models import Routine
from app.db.mongo import get_db
from app.deps import current_user
from app.routing.google_routes import NoRouteFound, RoutesApiError
from app.routing.pre_route import check_routine

router = APIRouter(prefix="/routines", tags=["routines"])


class PreRouteCheck(BaseModel):
    leg: int = 0
    departure: datetime


def public(doc: dict) -> dict:
    """The routine as the app sees it: each leg's saved route + belief snapshot stays server-side."""
    legs = [{k: v for k, v in leg.items() if k != "route_state"} for leg in doc.get("legs", [])]
    return {**doc, "legs": legs}


def _same_leg(a: dict, b: dict) -> bool:
    return (a.get("from_place"), a.get("to_place"), a.get("when")) == \
           (b.get("from_place"), b.get("to_place"), b.get("when"))


async def _save(routine: Routine, user: dict, routine_id: str | None = None) -> dict:
    db = get_db()
    doc = routine.model_dump(by_alias=True)
    # Like the mock: `repeat` and `when` carry only the fields their kind uses (legs keep days: null).
    doc["repeat"] = routine.repeat.model_dump(exclude_none=True)
    for leg, model in zip(doc["legs"], routine.legs, strict=True):
        leg["when"] = model.when.model_dump(exclude_none=True)
    doc["_id"] = routine_id or doc.get("_id") or str(uuid4())
    doc["user_id"] = user["_id"]
    existing = await db.routines.find_one({"_id": doc["_id"]})
    if existing and existing.get("user_id") != user["_id"]:
        raise HTTPException(404, "Routine not found")  # never reveal or overwrite another device's routine
    # A leg that didn't change keeps its saved route, so the next pre-route check can compare beliefs.
    for index, leg in enumerate(doc["legs"]):
        old_legs = (existing or {}).get("legs", [])
        if index < len(old_legs) and _same_leg(old_legs[index], leg) and old_legs[index].get("route_state"):
            leg["route_state"] = old_legs[index]["route_state"]
    doc["updated_at"] = datetime.now(timezone.utc)
    if existing:
        await db.routines.replace_one({"_id": doc["_id"], "user_id": user["_id"]}, doc)
    else:
        await db.routines.insert_one(doc)
    return public(doc)


@router.get("")
async def list_routines(user: Annotated[dict, Depends(current_user)]):
    docs = await get_db().routines.find({"user_id": user["_id"]}).to_list(length=100)
    return [public(doc) for doc in docs]


@router.post("")
async def save_routine(routine: Routine, user: Annotated[dict, Depends(current_user)]):
    """Create, or replace when `_id` names one of this device's routines (the app re-POSTs on edit)."""
    return await _save(routine, user)


@router.get("/{routine_id}")
async def get_routine(routine_id: str, user: Annotated[dict, Depends(current_user)]):
    doc = await get_db().routines.find_one({"_id": routine_id, "user_id": user["_id"]})
    if doc is None:
        raise HTTPException(404, "Routine not found")
    return public(doc)


@router.put("/{routine_id}")
async def update_routine(routine_id: str, routine: Routine, user: Annotated[dict, Depends(current_user)]):
    if not await get_db().routines.find_one({"_id": routine_id, "user_id": user["_id"]}):
        raise HTTPException(404, "Routine not found")
    return await _save(routine, user, routine_id)


@router.post("/{routine_id}/pre-route-check")
async def pre_route_check(routine_id: str, check: PreRouteCheck,
                          user: Annotated[dict, Depends(current_user)]):
    db = get_db()
    routine = await db.routines.find_one({"_id": routine_id, "user_id": user["_id"]})
    if routine is None:
        raise HTTPException(404, "Routine not found")
    try:
        return await check_routine(db, routine, check.leg, check.departure, datetime.now(timezone.utc))
    except NoRouteFound as exc:
        raise HTTPException(422, "No route found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RoutesApiError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.delete("/{routine_id}")
async def delete_routine(routine_id: str, user: Annotated[dict, Depends(current_user)]):
    result = await get_db().routines.delete_one({"_id": routine_id, "user_id": user["_id"]})
    if not result.deleted_count:
        raise HTTPException(404, "Routine not found")
    return {"deleted": routine_id}
