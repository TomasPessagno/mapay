from datetime import datetime, timezone
from uuid import uuid4

import networkx as nx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.db.models import Routine
from app.db.mongo import get_db
from app.routing.pre_route import check_routine

router = APIRouter(prefix="/routines", tags=["routines"])


class PreRouteCheck(BaseModel):
    departure: datetime


@router.get("")
async def list_routines(user_id: str):
    return await get_db().routines.find({"user_id": user_id}).to_list(length=100)


@router.post("")
async def create_routine(routine: Routine):
    doc = routine.model_dump(by_alias=True)
    doc["_id"] = doc["_id"] or str(uuid4())
    await get_db().routines.insert_one(doc)
    return doc


@router.post("/{routine_id}/pre-route-check")
async def pre_route_check(routine_id: str, check: PreRouteCheck, request: Request):
    db = get_db()
    routine = await db.routines.find_one({"_id": routine_id})
    if routine is None:
        raise HTTPException(404, "Routine not found")
    try:
        return await check_routine(db, routine, check.departure, datetime.now(timezone.utc),
                                   getattr(request.app.state, "graph", None))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except nx.NetworkXNoPath as exc:
        raise HTTPException(422, "No route found") from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.delete("/{routine_id}")
async def delete_routine(routine_id: str):
    await get_db().routines.delete_one({"_id": routine_id})
    return {"deleted": routine_id}
