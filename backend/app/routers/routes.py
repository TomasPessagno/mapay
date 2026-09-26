from datetime import datetime, timezone

import networkx as nx
from fastapi import APIRouter, HTTPException, Request

from app.db.models import RouteRequest, RouteResponse
from app.db.mongo import get_db
from app.routing.engine import baseline_route, weighted_route
from app.routing.pre_route import current_hazards, on_route

router = APIRouter(prefix="/route", tags=["route"])


@router.post("", response_model=RouteResponse)
async def compute_route(req: RouteRequest, request: Request) -> RouteResponse:
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        raise HTTPException(503, "Routing graph is not loaded")
    if req.mode != "drive":
        raise HTTPException(422, "A walking graph is not available")
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
        route = weighted_route(graph, req.origin, req.destination, hazards, req.avoid_tolls)
        baseline = baseline_route(graph, req.origin, req.destination)
    except nx.NetworkXNoPath as exc:
        raise HTTPException(422, "No route found") from exc
    if req.routine_id:
        await db.routines.update_one({'_id': req.routine_id}, {'$set': {'route_state': {
            'departure': req.depart_at, 'computed_at': now, 'route_geojson': route,
            'beliefs': on_route(route, hazards)}}})
    return RouteResponse(route_geojson=route, baseline_geojson=baseline)
