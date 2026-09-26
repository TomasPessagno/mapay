from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.mongo import close_client, init_indexes
from app.routers import alerts, layers, reports, routes, routines


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_indexes()
    # TODO: load pickled OSMnx graph into app.state (routing.graph.load_graph)
    # TODO: start ingestion pollers (tides, NWS, news)
    yield
    close_client()


settings = get_settings()
app = FastAPI(title="MAPAY API", version="0.1.0", lifespan=lifespan)

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


@app.get("/health")
async def health():
    return {"status": "ok"}
