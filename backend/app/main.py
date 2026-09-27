from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.db.mongo import close_client, init_indexes
from app.routers import (
    alerts,
    customize,
    demo,
    internal,
    layers,
    me,
    neighborhoods,
    places,
    reports,
    routes,
    routines,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_indexes()
    # No in-process pollers: Cloud Scheduler calls POST /internal/ingest/{job} (routers/internal.py).
    yield
    close_client()


settings = get_settings()
app = FastAPI(title="MAPAY API", version="0.1.0", lifespan=lifespan)

# /layers is ~14 MB of JSON for all of Miami-Dade (~20k City permits); gzip brings it under 1 MB.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router)
app.include_router(layers.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(routines.router)
app.include_router(neighborhoods.router)
app.include_router(internal.router)
app.include_router(places.router)
app.include_router(me.router)
app.include_router(customize.router)
app.include_router(demo.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
