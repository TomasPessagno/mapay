from fastapi import APIRouter

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def get_alerts():
    # TODO: NWS active alerts + news-derived items from intel_cache
    return {"nws": [], "news": []}
