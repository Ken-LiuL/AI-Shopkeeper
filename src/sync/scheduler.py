"""Sync Scheduler — cron-like scheduler for all QNH data syncers."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncResult

logger = logging.getLogger(__name__)

# Schedule config: when to run each syncer
SYNC_SCHEDULE: dict[str, dict[str, str]] = {
    "products": {"full": "06:00", "incremental": "every_30min"},
    "orders": {"incremental": "every_15min"},
    "metrics": {"incremental": "every_1h"},
    "inventory": {"incremental": "every_30min"},
    "traffic": {"incremental": "every_1h"},
    "reviews": {"incremental": "every_1h"},
    "competitors": {"full": "10:00"},
    # ── 新增同步器 ──
    "promotions": {"incremental": "every_6h"},
    "customers": {"full": "03:00"},  # 每天凌晨3点全量
    "refunds": {"incremental": "every_4h"},
    "finance": {"full": "02:00"},  # 每天凌晨2点全量
    "im_history": {"incremental": "every_30min"},
    "channels": {"incremental": "every_12h"},
}

# Interval parsing
INTERVAL_MAP = {
    "every_15min": timedelta(minutes=15),
    "every_30min": timedelta(minutes=30),
    "every_1h": timedelta(hours=1),
    "every_2h": timedelta(hours=2),
    "every_4h": timedelta(hours=4),
    "every_6h": timedelta(hours=6),
    "every_12h": timedelta(hours=12),
}


class SyncScheduler:
    """Manages sync schedules for all QNH data syncers.

    Usage:
        scheduler = SyncScheduler()
        scheduler.register(product_syncer)
        scheduler.register(order_syncer)
        await scheduler.run_forever()
    """

    def __init__(self, schedule: dict[str, dict[str, str]] | None = None) -> None:
        self.schedule = schedule or SYNC_SCHEDULE
        self.syncers: dict[str, BaseSyncer] = {}
        self._last_run: dict[str, datetime] = {}
        self._running = False
        self._tasks: list[asyncio.Task[Any]] = []

    def register(self, syncer: BaseSyncer) -> None:
        """Register a syncer to be scheduled."""
        self.syncers[syncer.name] = syncer
        logger.info(f"Registered syncer: {syncer.name}")

    async def run_once(self) -> list[SyncResult]:
        """Run all due syncers once (non-blocking check)."""
        results: list[SyncResult] = []
        now = datetime.now(CST)

        for name, syncer in self.syncers.items():
            sched = self.schedule.get(name, {})
            if not sched:
                continue

            if self._is_due(name, sched, now):
                logger.info(f"Running scheduled sync: {name}")
                try:
                    result = await syncer.sync()
                    results.append(result)
                    self._last_run[name] = now
                except Exception as e:
                    logger.error(f"Scheduled sync {name} failed: {e}")
                    results.append(
                        SyncResult(
                            syncer_name=name,
                            mode=syncer.name,  # type: ignore
                            success=False,
                            error=str(e),
                        )
                    )

        return results

    async def run_forever(self, check_interval: float = 60.0) -> None:
        """Run scheduler loop forever, checking every check_interval seconds."""
        self._running = True
        logger.info(f"Scheduler started with {len(self.syncers)} syncers")

        while self._running:
            try:
                results = await self.run_once()
                for r in results:
                    logger.info(r.summary)
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")

            await asyncio.sleep(check_interval)

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        logger.info("Scheduler stopped")

    async def run_all_now(self) -> list[SyncResult]:
        """Force-run all registered syncers immediately."""
        results: list[SyncResult] = []
        for name, syncer in self.syncers.items():
            logger.info(f"Force-running sync: {name}")
            try:
                result = await syncer.sync()
                results.append(result)
            except Exception as e:
                logger.error(f"Force sync {name} failed: {e}")
                results.append(
                    SyncResult(
                        syncer_name=name,
                        mode=syncer.name,  # type: ignore
                        success=False,
                        error=str(e),
                    )
                )
        return results

    # ── Internal ────────────────────────────────────────────────────────

    def _is_due(self, name: str, sched: dict[str, str], now: datetime) -> bool:
        """Check if a syncer is due to run based on schedule."""
        last = self._last_run.get(name)

        # Check fixed-time schedules (e.g., "06:00", "23:30")
        for mode in ("full", "incremental"):
            time_str = sched.get(mode, "")
            if not time_str or time_str.startswith("every_"):
                continue

            try:
                hour, minute = map(int, time_str.split(":"))
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

                # If we're within 2 minutes of the target and haven't run today
                if abs((now - target).total_seconds()) < 120:
                    if last is None or last.date() < now.date():
                        return True
            except ValueError:
                pass

        # Check interval schedules (e.g., "every_30min")
        for mode in ("full", "incremental"):
            interval_key = sched.get(mode, "")
            interval = INTERVAL_MAP.get(interval_key)
            if interval is None:
                continue

            if last is None or (now - last) >= interval:
                return True

        return False

    @property
    def status(self) -> dict[str, Any]:
        """Get scheduler status summary."""
        return {
            "running": self._running,
            "syncers": list(self.syncers.keys()),
            "last_runs": {name: ts.isoformat() for name, ts in self._last_run.items()},
            "schedule": self.schedule,
        }
