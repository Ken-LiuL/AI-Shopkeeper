"""FastAPI application entry point for AI Store Manager."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings
from src.db import neo4j as neo4j_db
from src.db import postgres as pg_db
from src.db import redis as redis_db

logger = logging.getLogger("ai_store_manager")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle hooks."""
    # ── Startup ──────────────────────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting AI Store Manager …")

    settings = get_settings()

    # Init database connections
    await pg_db.init_pool()
    await neo4j_db.init_driver()
    await redis_db.init_redis()

    # Prometheus metrics endpoint (if enabled)
    if settings.system.prometheus.get("enabled"):
        try:
            from prometheus_client import start_http_server

            prom_port = settings.system.prometheus.get("port", 9090)
            start_http_server(prom_port)
            logger.info("Prometheus metrics server on :%s", prom_port)
        except Exception:
            logger.warning("Failed to start Prometheus metrics server", exc_info=True)

    logger.info("All services initialised ✓")

    yield

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("Shutting down …")
    await redis_db.close_redis()
    await neo4j_db.close_driver()
    await pg_db.close_pool()
    logger.info("Shutdown complete ✓")


app = FastAPI(
    title="AI Store Manager",
    description="美团即时零售（医疗器械）智能运营系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health check ────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Basic liveness probe."""
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
async def readiness_check() -> dict[str, str | bool]:
    """Deep readiness probe — verify all dependencies."""
    checks: dict[str, bool] = {}

    # PostgreSQL
    try:
        await pg_db.fetchval("SELECT 1")
        checks["postgres"] = True
    except Exception:
        checks["postgres"] = False

    # Neo4j
    try:
        await neo4j_db.query("RETURN 1 AS n")
        checks["neo4j"] = True
    except Exception:
        checks["neo4j"] = False

    # Redis
    try:
        await redis_db.get_redis().ping()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    all_ok = all(checks.values())
    return {"status": "ok" if all_ok else "degraded", **checks}  # type: ignore[return-value]
