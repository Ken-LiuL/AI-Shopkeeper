#!/usr/bin/env python3
"""Daily orchestration: QNH sync → store stock sync → ETL → daily insights warmup."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.etl_qnh_to_business import (  # type: ignore  # pylint: disable=wrong-import-position
    build_product_index,
    generate_alerts,
    snapshot_price_history,
    sync_products,
    sync_sales_history,
    sync_store_metrics,
)
from scripts.sync_qnh_data import (  # type: ignore  # pylint: disable=wrong-import-position
    DEFAULT_POI_IDS,
    DEFAULT_SQLITE_PATH,
    DEFAULT_TENANT_ID,
    QNHDataSync,
    StorageManager,
)
from src.sync.browser_client import BrowserClient  # pylint: disable=wrong-import-position
from src.sync.store_stock import StoreStockSyncer  # pylint: disable=wrong-import-position

logger = logging.getLogger("daily_sync_and_etl")

DEFAULT_API_BASE = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")

__all__ = [
    "run_qnh_data_sync",
    "run_store_stock_sync",
    "run_etl_pipeline",
    "trigger_daily_insights",
    "run_daily_workflow",
]


# ── Individual job runners ────────────────────────────────────────────────────


async def run_qnh_data_sync(
    database_url: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    date_type: str = "d",
    page_size: int = 100,
) -> dict[str, Any]:
    """Run scripts.sync_qnh_data pipeline with defaults."""
    if not database_url:
        raise ValueError("database_url is required for QNH data sync")

    today = datetime.now()
    start = start_date or today.strftime("%Y%m%d")
    end = end_date or start

    async with StorageManager(Path(DEFAULT_SQLITE_PATH), database_url, dry_run=False) as storage:
        syncer = QNHDataSync(
            tenant_id=str(DEFAULT_TENANT_ID),
            poi_ids=list(DEFAULT_POI_IDS),
            start_date=start,
            end_date=end,
            date_type=date_type,
            page_size=page_size,
            storage=storage,
            skip_browser=False,
        )
        exit_code = await syncer.run()

    return {
        "exit_code": exit_code,
        "summary": dict(syncer.summary),
        "errors": dict(syncer.errors),
    }


async def run_store_stock_sync(
    database_url: str,
    *,
    poi_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Run the StoreStockSyncer once (auto full/incremental)."""
    if not database_url:
        raise ValueError("database_url is required for store stock sync")

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=4)
    try:
        browser = await BrowserClient.get_instance()
        syncer = StoreStockSyncer(browser, pool, poi_ids=poi_ids)
        result = await syncer.sync()
    finally:
        await pool.close()

    return {
        "success": result.success,
        "records_synced": result.records_synced,
        "details": result.details,
        "error": result.error,
    }


async def run_etl_pipeline(database_url: str, *, batch_size: int = 200) -> dict[str, Any]:
    """Run ETL pipeline defined in scripts/etl_qnh_to_business.py."""
    if not database_url:
        raise ValueError("database_url is required for ETL pipeline")

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=4)
    try:
        product_stats = await sync_products(pool, batch_size)
        product_index = await build_product_index(pool)
        sales_stats = await sync_sales_history(pool, product_index, batch_size)
        metrics_stats = await sync_store_metrics(pool, batch_size)
        alert_stats = await generate_alerts(pool, batch_size)
        price_count = await snapshot_price_history(pool)
    finally:
        await pool.close()

    return {
        "products": product_stats,
        "sales_history": sales_stats,
        "qnh_daily_metrics": metrics_stats,
        "alerts": alert_stats,
        "price_history": price_count,
    }


async def trigger_daily_insights(
    api_base_url: str = DEFAULT_API_BASE,
    *,
    force_refresh: bool = True,
) -> dict[str, Any]:
    """Call the /api/insights/daily endpoint to warm up cache."""
    url = f"{api_base_url.rstrip('/')}/api/insights/daily"
    params = {"force_refresh": str(force_refresh).lower()}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        return {
            "status_code": response.status_code,
            "payload": payload,
        }


# ── CLI orchestration ────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="PostgreSQL connection string (default: $DATABASE_URL)",
    )
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE,
        help="API base URL used for insights warmup (default: %(default)s)",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--skip-qnh-sync",
        action="store_true",
        help="Skip QNH data sync step",
    )
    parser.add_argument(
        "--skip-store-stock",
        action="store_true",
        help="Skip store stock sync step",
    )
    parser.add_argument(
        "--skip-etl",
        action="store_true",
        help="Skip ETL pipeline step",
    )
    parser.add_argument(
        "--skip-insights",
        action="store_true",
        help="Skip daily insights warmup",
    )
    return parser.parse_args()


async def run_daily_workflow(args: argparse.Namespace) -> dict[str, Any]:
    """Run all enabled steps sequentially and return a structured summary."""
    if not args.database_url:
        raise ValueError("--database-url is required or set DATABASE_URL env")

    summary: dict[str, Any] = {"steps": {}, "errors": {}}

    if not args.skip_qnh_sync:
        try:
            logger.info("Running QNH dataset sync...")
            summary["steps"]["qnh_data_sync"] = await run_qnh_data_sync(args.database_url)
        except Exception as exc:  # noqa: BLE001
            logger.exception("QNH data sync failed")
            summary["errors"]["qnh_data_sync"] = str(exc)

    if not args.skip_store_stock:
        try:
            logger.info("Running store stock sync...")
            summary["steps"]["store_stock_sync"] = await run_store_stock_sync(
                args.database_url, poi_ids=DEFAULT_POI_IDS
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Store stock sync failed")
            summary["errors"]["store_stock_sync"] = str(exc)

    if not args.skip_etl:
        try:
            logger.info("Running ETL pipeline...")
            summary["steps"]["etl_pipeline"] = await run_etl_pipeline(args.database_url)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ETL pipeline failed")
            summary["errors"]["etl_pipeline"] = str(exc)

    if not args.skip_insights:
        try:
            logger.info("Triggering daily insights warmup...")
            summary["steps"]["daily_insights"] = await trigger_daily_insights(args.api_base_url)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Daily insights warmup failed")
            summary["errors"]["daily_insights"] = str(exc)

    summary["success"] = not summary["errors"]
    return summary


async def async_main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    summary = await run_daily_workflow(args)
    logger.info("Daily workflow finished (success=%s)", summary["success"])
    if summary["errors"]:
        logger.error("Errors: %s", summary["errors"])
    logger.debug("Step details: %s", summary["steps"])
    return 0 if summary["success"] else 1


def main() -> None:
    try:
        exit_code = asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        exit_code = 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("Daily workflow failed: %s", exc)
        exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
