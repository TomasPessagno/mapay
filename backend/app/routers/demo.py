"""POST /demo/heads-up: make a routine leg "due in 30 min" for the live demo (AGENTS.md › Demo).

It writes a demo_overrides document; /routines/upcoming then lists that leg departing
heads_up_minutes from now, so its heads-up window starts immediately, and the pre-route check
accepts that departure. The document expires an hour after the departure (TTL index).
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.mongo import get_db
from app.deps import current_user

router = APIRouter(prefix="/demo", tags=["demo"])
KEEP_AFTER_DEPARTURE = timedelta(hours=1)


class HeadsUpRequest(BaseModel):
    routine_id: str
    leg: int = 0


@router.post("/heads-up")
async def fire_heads_up(req: HeadsUpRequest, user: Annotated[dict, Depends(current_user)]):
    db = get_db()
    routine = await db.routines.find_one({"_id": req.routine_id, "user_id": user["_id"]})
    if routine is None:
        raise HTTPException(404, "Routine not found")
    if not 0 <= req.leg < len(routine.get("legs", [])):
        raise HTTPException(422, f"Routine has no leg {req.leg}")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    departure = now + timedelta(minutes=routine.get("heads_up_minutes", 30))
    doc = {"_id": f"{user['_id']}:{req.routine_id}:{req.leg}", "user_id": user["_id"],
           "routine_id": req.routine_id, "leg": req.leg, "departure_at": departure,
           "expires_at": departure + KEEP_AFTER_DEPARTURE, "created_at": now}
    await db.demo_overrides.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return {"routine_id": req.routine_id, "leg": req.leg, "departure_at": departure.isoformat(),
            "heads_up_at": now.isoformat(), "expires_at": doc["expires_at"].isoformat()}
