from __future__ import annotations

from app.api.chat import router as chat_router
from app.core.config import settings
from app.infra.transport.pool import TransportPool
from app.services.topology import TopologyService
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.topology = TopologyService.from_yaml(settings.topology_seed_path)
    app.state.transport_pool = TransportPool(
        idle_ttl=settings.transport_idle_ttl,
        reap_interval=settings.transport_reap_interval,
    )
    await app.state.transport_pool.startup()
    try:
        yield
    finally:
        await app.state.transport_pool.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
