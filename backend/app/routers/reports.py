from fastapi import APIRouter

from app.db.models import HazardReportIn

router = APIRouter(prefix="/report", tags=["reports"])


@router.post("")
async def create_report(report: HazardReportIn):
    # TODO: upsert into hazard_reports (bump confirmed_count if nearby duplicate)
    return {"ok": True}


@router.get("")
async def list_reports():
    # TODO: return hazard_reports as GeoJSON
    return {"type": "FeatureCollection", "features": []}
