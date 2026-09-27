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
    departure: datetime


@router.get("")
async def list_routines(user: Annotated[dict, Depends(current_user)]):
    return await get_db().routines.find({"user_id": user["_id"]}).to_list(length=100)


@router.post("")
async def create_routine(routine: Routine, user: Annotated[dict, Depends(current_user)]):
    doc = routine.model_dump(by_alias=True)
    doc["_id"] = doc["_id"] or str(uuid4())
    doc["user_id"] = user["_id"]
    await get_db().routines.insert_one(doc)
    return doc


@router.post("/{routine_id}/pre-route-check")
async def pre_route_check(routine_id: str, check: PreRouteCheck,
                          user: Annotated[dict, Depends(current_user)]):
    db = get_db()
    routine = await db.routines.find_one({"_id": routine_id, "user_id": user["_id"]})
    if routine is None:
        raise HTTPException(404, "Routine not found")
    try:
        return await check_routine(db, routine, check.departure, datetime.now(timezone.utc))
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
