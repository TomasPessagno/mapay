from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.db.models import RouteAlternative, RouteRequest, RouteResponse
from app.db.mongo import get_db
from app.routing.engine import pick_route, route_alternatives
from app.routing.google_routes import NoRouteFound, RoutesApiError
from app.routing.pre_route import current_hazards, on_route

router = APIRouter(prefix="/route", tags=["route"])


@router.post("", response_model=RouteResponse)
async def compute_route(req: RouteRequest) -> RouteResponse:
    db = get_db()
    if req.routine_id:
        routine = await db.routines.find_one({"_id": req.routine_id})
        if not routine:
            raise HTTPException(404, "Routine not found")
        if list(req.origin) != list(routine['origin']) or list(req.destination) != list(routine['destination']):
            raise HTTPException(422, "Route endpoints must match the routine")
        if req.depart_at is None or req.depart_at.tzinfo is None:
            raise HTTPException(422, "Routine route requires a timezone-aware depart_at")
        if req.avoid_tolls != routine.get('preferences', {}).get('avoid_tolls', False):
            raise HTTPException(422, "Route preferences must match the routine")
    now = datetime.now(timezone.utc)
    hazards = await current_hazards(db, now)
    try:
        alternatives = await route_alternatives(req.origin, req.destination, req.depart_at, req.avoid_tolls,
                                                req.avoid_highways, req.mode)
    except NoRouteFound as exc:
        raise HTTPException(422, "No route found") from exc
    except RoutesApiError as exc:
        raise HTTPException(502, str(exc)) from exc
    chosen = pick_route(alternatives, hazards)
    route = chosen["route_geojson"]
    if req.routine_id:
        await db.routines.update_one({'_id': req.routine_id}, {'$set': {'route_state': {
            'departure': req.depart_at, 'computed_at': now, 'route_geojson': route,
            'beliefs': on_route(route, hazards)}}})
    return RouteResponse(
        depart_at=req.depart_at,
        route_geojson=route,
        baseline_geojson=alternatives[0]["route_geojson"],
        alternatives=[RouteAlternative(**alt, recommended=alt is chosen) for alt in alternatives],
    )
