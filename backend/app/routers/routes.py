from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException

from app.db.models import RouteAlternative, RouteRequest, RouteResponse
from app.db.mongo import get_db
from app.routing.engine import route_alternatives
from app.routing.google_routes import NoRouteFound, RoutesApiError
from app.routing.pre_route import current_hazards, on_route
from app.routing.scoring import merge_preferences, rank

router = APIRouter(prefix="/route", tags=["route"])


def request_overrides(req: RouteRequest) -> dict:
    """The request's preferences, plus the top-level Google flags when the client sent them."""
    overrides = dict(req.preferences or {})
    for flag in ("avoid_tolls", "avoid_highways"):
        if flag in req.model_fields_set:
            overrides[flag] = getattr(req, flag)
    return overrides


@router.post("", response_model=RouteResponse)
async def compute_route(req: RouteRequest, x_device_id: str | None = Header(default=None)) -> RouteResponse:
    db = get_db()
    routine = None
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
    # The device id is optional here: without it the AGENTS.md defaults apply.
    device_id = (x_device_id or "").strip()
    user = await db.users.find_one({"_id": device_id}) if device_id else None
    preferences = merge_preferences((user or {}).get("preferences"), (routine or {}).get("preferences"),
                                    request_overrides(req))
    now = datetime.now(timezone.utc)
    hazards = await current_hazards(db, now)
    try:
        alternatives = await route_alternatives(req.origin, req.destination, req.depart_at,
                                                preferences["avoid_tolls"], preferences["avoid_highways"], req.mode)
    except NoRouteFound as exc:
        raise HTTPException(422, "No route found") from exc
    except RoutesApiError as exc:
        raise HTTPException(502, str(exc)) from exc
    baseline = alternatives[0]["route_geojson"]  # Google's own first choice
    ranked = rank(alternatives, hazards, preferences)
    chosen = ranked[0]
    route = chosen["route_geojson"]
    if req.routine_id:
        await db.routines.update_one({'_id': req.routine_id}, {'$set': {'route_state': {
            'departure': req.depart_at, 'computed_at': now, 'route_geojson': route,
            'beliefs': on_route(route, hazards)}}})
    return RouteResponse(
        depart_at=req.depart_at,
        route_geojson=route,
        baseline_geojson=baseline,
        alternatives=[RouteAlternative(**alt) for alt in ranked],
        hazards_on_route=chosen["hazards_on_route"],
    )
