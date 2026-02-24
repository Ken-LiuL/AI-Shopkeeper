"""Shared dependencies for API routes."""

from __future__ import annotations

import uuid
from functools import lru_cache

from src.agents.orchestrator import Orchestrator


@lru_cache(maxsize=1)
def get_orchestrator() -> Orchestrator:
    return Orchestrator()


async def get_pool():
    """Get asyncpg connection pool."""
    from src.db import postgres as pg_db

    return pg_db.get_pool()


def gen_id(prefix: str = "") -> str:
    short = uuid.uuid4().hex[:12]
    return f"{prefix}{short}" if prefix else short
