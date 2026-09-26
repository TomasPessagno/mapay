from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.db.models import HazardReportIn
from app.db.mongo import get_db
from app.routing.beliefs import add_evidence

router = APIRouter(prefix="/report", tags=["reports"])


@router.post("")
async def create_report(report: HazardReportIn):
    db = get_db()
    if report.cleared and not report.hazard_id:
        raise HTTPException(422, "Cleared reports require a hazard_id")
    if report.hazard_id and not await db.intel_cache.find_one({"_id": f"belief:{report.hazard_id}"}):
        raise HTTPException(404, "Unknown hazard_id; register the source layer hazard first")
    now = datetime.now(timezone.utc)
    doc = {"_id": str(uuid4()), "type": report.type,
           "location": {"type": "Point", "coordinates": [report.lng, report.lat]},
           "reported_at": now, "confirmed_count": 1, "hazard_id": report.hazard_id,
           "cleared": report.cleared}
    await db.hazard_reports.insert_one(doc)
    if report.hazard_id:
        await add_evidence(db, report.hazard_id, doc["_id"],
                           "cleared" if report.cleared else "crowd", now, now)
    return {"ok": True, "id": doc["_id"], "belief_updated": bool(report.hazard_id)}


@router.get("")
async def list_reports():
    docs = await get_db().hazard_reports.find({}).to_list(length=1000)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": d["location"],
         "properties": {k: v for k, v in d.items() if k != "location"}} for d in docs]}
