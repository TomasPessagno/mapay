from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

router = APIRouter(prefix="/layers", tags=["layers"])


@router.get("")
async def get_layers(t: Annotated[datetime | None, Query(description="Departure time; defaults to now")] = None):
    # TODO: combine tide-activated flood zones, closures, potholes, AADT, reports for time t
    return {
        "t": t,
        "flood": {"type": "FeatureCollection", "features": []},
        "closures": {"type": "FeatureCollection", "features": []},
        "potholes": {"type": "FeatureCollection", "features": []},
        "reports": {"type": "FeatureCollection", "features": []},
    }
