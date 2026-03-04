"""Tests for raw data helper fallbacks."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from asyncpg import exceptions as pg_exc

from src.services.raw_data import fetch_latest_raw


@pytest.mark.asyncio
async def test_fetch_latest_raw_fallback_to_synced_at(monkeypatch):
    """Should retry with synced_at/id when created_at column missing."""

    pool = AsyncMock()
    pool.fetchrow = AsyncMock(
        side_effect=[
            pg_exc.UndefinedColumnError("missing created_at"),
            {"raw_data": {"foo": "bar"}},
        ]
    )

    result = await fetch_latest_raw(pool, "qnh_inventory_raw")

    assert result == {"foo": "bar"}
    assert pool.fetchrow.await_count == 2
