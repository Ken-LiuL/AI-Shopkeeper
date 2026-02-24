"""Data sync status and trigger API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/sync", tags=["sync"])
logger = logging.getLogger(__name__)


@router.get("/history", response_model=APIResponse[list[dict]])
async def sync_history(
    limit: int = 50,
) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT * FROM sync_history ORDER BY started_at DESC LIMIT $1""",
        limit,
    )
    return APIResponse(data=[dict(r) for r in rows])


@router.get("/{syncer_name}/status", response_model=APIResponse[dict])
async def single_syncer_status(syncer_name: str) -> APIResponse[dict]:
    pool = pg.get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM sync_state WHERE syncer_name = $1",
        syncer_name,
    )
    if not row:
        from .errors import NotFoundError

        raise NotFoundError("Syncer", syncer_name)
    return APIResponse(data=dict(row))


@router.post("/{syncer_name}/trigger", response_model=APIResponse[dict])
async def trigger_single_syncer(syncer_name: str, bg: BackgroundTasks) -> APIResponse[dict]:
    syncer_map = {
        "products": "src.sync.products:ProductSyncer",
        "orders": "src.sync.orders:OrderSyncer",
        "inventory": "src.sync.inventory:InventorySyncer",
        "metrics": "src.sync.metrics:MetricsSyncer",
        "traffic": "src.sync.traffic:TrafficSyncer",
        "reviews": "src.sync.reviews:ReviewSyncer",
    }
    if syncer_name not in syncer_map:
        from .errors import NotFoundError

        raise NotFoundError("Syncer", syncer_name)

    async def _run() -> None:
        try:
            module_path, class_name = syncer_map[syncer_name].rsplit(":", 1)
            import importlib

            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            from src.sync.qnh_client import QNHClient

            syncer = cls(QNHClient())
            await syncer.sync_full()
        except Exception:
            logger.exception("Single sync failed for %s", syncer_name)

    bg.add_task(_run)
    return APIResponse(data={"syncer": syncer_name, "status": "triggered"})


@router.get("/status", response_model=APIResponse[list[dict]])
async def sync_status() -> APIResponse[list[dict]]:
    """Return sync state for all registered syncers."""
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT syncer_name, last_full_sync, last_incremental_sync,
                  last_sync_status, last_sync_error, records_synced,
                  last_sync_duration_ms, updated_at
           FROM sync_state ORDER BY syncer_name"""
    )
    return APIResponse(data=[dict(r) for r in rows])


async def _trigger_sync_all() -> None:
    """Run all syncers once in background."""
    try:
        from src.sync.inventory import InventorySyncer
        from src.sync.metrics import MetricsSyncer
        from src.sync.orders import OrderSyncer
        from src.sync.products import ProductSyncer
        from src.sync.qnh_client import QNHClient
        from src.sync.reviews import ReviewSyncer
        from src.sync.traffic import TrafficSyncer

        client = QNHClient()
        syncers = [
            ProductSyncer(client),
            OrderSyncer(client),
            InventorySyncer(client),
            MetricsSyncer(client),
            TrafficSyncer(client),
            ReviewSyncer(client),
        ]
        for s in syncers:
            try:
                await s.sync_full()
            except Exception:
                logger.exception("Sync failed for %s", s.name)
    except Exception:
        logger.exception("Failed to trigger sync")


@router.post("/trigger", response_model=APIResponse[dict])
async def trigger_sync(bg: BackgroundTasks) -> APIResponse[dict]:
    """Manually trigger a full sync of all data sources."""
    bg.add_task(_trigger_sync_all)
    return APIResponse(data={"status": "triggered"}, message="Full sync triggered in background")
