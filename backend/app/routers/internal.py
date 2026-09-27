"""POST /internal/ingest/{job}: Cloud Scheduler's entry point for every ingestion job.

Cloud Run throttles CPU between requests, so there are no in-process pollers: each job runs
inside the request that triggers it. Only Cloud Scheduler may call this. It sends an OIDC ID
token for SCHEDULER_SERVICE_ACCOUNT with the service URL as audience (scripts/scheduler.sh),
and both are checked here. Anyone can mint a Google-signed token for any audience from their
own service account, so the email check is what actually restricts the caller.
"""
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.briefings import precompute
from app.config import get_settings
from app.db.mongo import get_db
from app.ingestion import (
    closures,
    earth_engine_s1,
    earth_engine_s2,
    gfm,
    here_flow,
    here_incidents,
    news,
    nws,
    potholes,
    sidewalks,
    tides,
    traffic_samples,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])

Job = Callable[..., Awaitable[object]]


async def _here(db, now):
    return {"incidents": await here_incidents.run(db, now), "flow": await here_flow.run(db, now)}


async def _satellite_floods(db, now):
    """GFM when an account is configured; otherwise, or if GFM fails, our own Earth Engine run."""
    if gfm.configured():
        try:
            return await gfm.run(db, now)
        except Exception:
            log.exception("GFM failed; falling back to Earth Engine")
    return await earth_engine_s1.run(db, now)


async def _satellite_construction(db, now):
    """Sentinel-2 change detection; if it fails, the fallback that checks the City's permit sites."""
    try:
        return await earth_engine_s2.run(db, now)
    except Exception:
        log.exception("Sentinel-2 change detection failed; checking permit sites instead")
        return await earth_engine_s2.run(db, now, mode="permits")


async def _sidewalks(db, now):
    return {"ways": len((await sidewalks.fetch(db=db, now=now))["features"])}


# One line per job. Names follow AGENTS.md › API contract; cadences live in scripts/scheduler.sh.
JOBS: dict[str, Job] = {
    "news": news.run,
    "weather": nws.run,
    "here": _here,
    "tides": tides.run,
    "city_gis": closures.run,
    "sidewalks": _sidewalks,
    "potholes": potholes.run,
    "gfm": _satellite_floods,
    "s1": earth_engine_s1.run,
    "s2": _satellite_construction,
    "briefings": precompute.run,
    "traffic": traffic_samples.run,
}


def _verify_token(token: str, audience: str) -> dict:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    return id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience)


async def require_scheduler(authorization: Annotated[str | None, Header()] = None) -> dict:
    """Cloud Scheduler's OIDC token: Google-signed, our audience, our scheduler service account."""
    settings = get_settings()
    if not settings.internal_audience or not settings.scheduler_service_account:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Internal jobs are not configured")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    from google.auth.exceptions import GoogleAuthError, TransportError
    try:
        claims = await run_in_threadpool(_verify_token, token, settings.internal_audience)
    except TransportError as exc:  # couldn't fetch Google's certs: retryable
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Token check unavailable") from exc
    except (ValueError, GoogleAuthError) as exc:  # malformed, bad signature, expired, wrong audience
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    if not claims.get("email_verified") or claims.get("email") != settings.scheduler_service_account:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Caller is not the scheduler")
    return claims


@router.post("/ingest/{job}")
async def ingest(job: str, _: Annotated[dict, Depends(require_scheduler)]):
    run = JOBS.get(job)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown job: {job}")
    started = datetime.now(timezone.utc)
    try:
        result = await run(get_db(), started)
    except Exception as exc:
        # A 5xx makes Cloud Scheduler retry per the job's retry config.
        log.exception("Ingestion job %s failed", job)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"{job} failed: {type(exc).__name__}") from exc
    seconds = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
    log.info("Ingestion job %s finished in %ss: %s", job, seconds, result)
    return {"job": job, "started_at": started.isoformat(), "seconds": seconds, "result": result}
