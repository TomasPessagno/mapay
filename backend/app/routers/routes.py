from fastapi import APIRouter

from app.db.models import RouteRequest, RouteResponse

router = APIRouter(prefix="/route", tags=["route"])


@router.post("", response_model=RouteResponse)
async def compute_route(req: RouteRequest) -> RouteResponse:
    # TODO: check routes_cache -> routing.engine.weighted_route -> briefing agent -> cache
    return RouteResponse(route_geojson={"type": "FeatureCollection", "features": []})
