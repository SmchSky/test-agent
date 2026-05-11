"""Test Agent — FastAPI 应用入口"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.chat import router as chat_router
from core.config import settings
from infra.transport.pool import TransportPool
from services.topology import TopologyService


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _app.state.topology = TopologyService.from_yaml(settings.topology_seed_path)
    _app.state.transport_pool = TransportPool(
        idle_ttl=settings.transport_idle_ttl,
        reap_interval=settings.transport_reap_interval,
    )
    await _app.state.transport_pool.startup()
    try:
        yield
    finally:
        await _app.state.transport_pool.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,  # type: ignore
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
