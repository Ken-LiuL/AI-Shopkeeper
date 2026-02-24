"""BaseSyncer — abstract base class for all QNH data syncers."""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


class SyncMode(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"


@dataclass
class SyncResult:
    """Result of a sync operation."""

    syncer_name: str
    mode: SyncMode
    success: bool
    records_synced: int = 0
    records_failed: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = 0
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        status = "✅" if self.success else "❌"
        return (
            f"{status} {self.syncer_name} [{self.mode.value}] "
            f"— {self.records_synced} records in {self.duration_ms}ms"
        )


class BaseSyncer(ABC):
    """Abstract base class for data syncers.

    Subclasses implement full_sync() and incremental_sync().
    The sync() method intelligently chooses which to run.
    """

    # Override in subclass
    name: str = "base"
    full_sync_interval: timedelta = timedelta(hours=24)
    max_retries: int = 3
    retry_base_delay: float = 2.0  # seconds, exponential backoff

    def __init__(self, client: Any, db_pool: Any) -> None:
        self.client = client  # QNHClient
        self.pool = db_pool  # asyncpg pool
        self.logger = logging.getLogger(f"sync.{self.name}")

    # ── Abstract methods ────────────────────────────────────────────────

    @abstractmethod
    async def full_sync(self) -> SyncResult:
        """Full sync — first run or periodic refresh."""
        ...

    @abstractmethod
    async def incremental_sync(self, since: datetime) -> SyncResult:
        """Incremental sync — based on timestamp."""
        ...

    # ── Public API ──────────────────────────────────────────────────────

    async def sync(self) -> SyncResult:
        """Smart sync: choose full or incremental based on state."""
        state = await self._get_sync_state()

        if state is None:
            self.logger.info("No previous sync found, running full sync")
            return await self._run_with_retry(SyncMode.FULL)

        last_full = state.get("last_full_sync")
        last_incr = state.get("last_incremental_sync")
        last_time = last_full or last_incr

        if (
            last_full is None
            or (datetime.now(CST) - last_full.replace(tzinfo=CST)) > self.full_sync_interval
        ):
            self.logger.info("Full sync interval exceeded, running full sync")
            return await self._run_with_retry(SyncMode.FULL)

        since = last_time.replace(tzinfo=CST) if last_time.tzinfo is None else last_time
        self.logger.info(f"Running incremental sync since {since}")
        return await self._run_with_retry(SyncMode.INCREMENTAL, since=since)

    # ── Internal ────────────────────────────────────────────────────────

    async def _run_with_retry(self, mode: SyncMode, since: datetime | None = None) -> SyncResult:
        """Execute sync with exponential backoff retry."""
        last_error: str | None = None
        for attempt in range(1, self.max_retries + 1):
            start = time.monotonic()
            started_at = datetime.now(CST)
            try:
                await self._update_sync_state("running")

                if mode == SyncMode.FULL:
                    result = await self.full_sync()
                else:
                    assert since is not None
                    result = await self.incremental_sync(since)

                result.started_at = started_at
                result.finished_at = datetime.now(CST)
                result.duration_ms = int((time.monotonic() - start) * 1000)

                if result.success:
                    await self._save_sync_state(result)
                    self.logger.info(result.summary)
                    return result

                last_error = result.error
                self.logger.warning(f"Attempt {attempt}/{self.max_retries} failed: {result.error}")
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                self.logger.error(
                    f"Attempt {attempt}/{self.max_retries} exception: {last_error}\n"
                    f"{traceback.format_exc()}"
                )

            if attempt < self.max_retries:
                delay = self.retry_base_delay**attempt
                self.logger.info(f"Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

        # All retries exhausted
        result = SyncResult(
            syncer_name=self.name,
            mode=mode,
            success=False,
            started_at=started_at,
            finished_at=datetime.now(CST),
            duration_ms=int((time.monotonic() - start) * 1000),
            error=last_error,
        )
        await self._update_sync_state("failed", error=last_error)
        self.logger.error(f"All retries exhausted: {result.summary}")
        return result

    async def _get_sync_state(self) -> dict[str, Any] | None:
        """Get current sync state from DB."""
        if self.pool is None:
            return None
        try:
            row = await self.pool.fetchrow(
                "SELECT * FROM sync_state WHERE syncer_name = $1",
                self.name,
            )
            return dict(row) if row else None
        except Exception as e:
            self.logger.warning(f"Failed to get sync state: {e}")
            return None

    async def _update_sync_state(self, status: str, error: str | None = None) -> None:
        """Update sync state in DB."""
        if self.pool is None:
            return
        try:
            await self.pool.execute(
                """
                INSERT INTO sync_state (syncer_name, last_sync_status, last_sync_error, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (syncer_name) DO UPDATE
                SET last_sync_status = $2, last_sync_error = $3, updated_at = NOW()
                """,
                self.name,
                status,
                error,
            )
        except Exception as e:
            self.logger.warning(f"Failed to update sync state: {e}")

    async def _save_sync_state(self, result: SyncResult) -> None:
        """Save successful sync result to DB."""
        if self.pool is None:
            return
        try:
            col = "last_full_sync" if result.mode == SyncMode.FULL else "last_incremental_sync"
            await self.pool.execute(
                f"""
                INSERT INTO sync_state
                    (syncer_name, {col}, last_sync_status, records_synced,
                     last_sync_duration_ms, updated_at)
                VALUES ($1, $2, 'success', $3, $4, NOW())
                ON CONFLICT (syncer_name) DO UPDATE
                SET {col} = $2, last_sync_status = 'success',
                    records_synced = $3, last_sync_duration_ms = $4,
                    last_sync_error = NULL, updated_at = NOW()
                """,
                self.name,
                result.finished_at,
                result.records_synced,
                result.duration_ms,
            )
        except Exception as e:
            self.logger.warning(f"Failed to save sync state: {e}")
