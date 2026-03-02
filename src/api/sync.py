"""Data sync status, trigger, and cookie management API routes."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/sync", tags=["sync"])
logger = logging.getLogger(__name__)

SYNC_API_KEY = os.environ.get("SYNC_API_KEY", "")


# ── Pydantic models ─────────────────────────────────────────────────────────


class CookieSubmitRequest(BaseModel):
    """商家提交 Cookie 请求。"""

    cookie_string: str | None = None  # 原始 cookie 字符串，如 "a=1; b=2"
    cookie_json: dict[str, str] | None = None  # 结构化 JSON
    merchant_id: str = "default"


class CookieSubmitResponse(BaseModel):
    ok: bool
    message: str
    cookie_count: int = 0


# ── Helper ──────────────────────────────────────────────────────────────────


def _parse_cookie_string(cookie_string: str) -> dict[str, str]:
    """解析 cookie 字符串为字典。"""
    cookies: dict[str, str] = {}
    for part in cookie_string.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            cookies[k.strip()] = v.strip()
    return cookies


async def _get_pool():
    return pg.get_pool()


# ── Cookie API ──────────────────────────────────────────────────────────────


@router.post("/cookie", response_model=CookieSubmitResponse)
async def submit_cookie(req: CookieSubmitRequest) -> CookieSubmitResponse:
    """商家提交 QNH Cookie。

    支持两种格式：
    1. cookie_string: "token=xxx; session=yyy; ..."
    2. cookie_json: {"token": "xxx", "session": "yyy"}
    """
    import json

    # 解析 Cookie
    if req.cookie_json:
        cookies = req.cookie_json
    elif req.cookie_string:
        cookies = _parse_cookie_string(req.cookie_string.strip())
    else:
        raise HTTPException(status_code=400, detail="需要提供 cookie_string 或 cookie_json")

    if not cookies:
        raise HTTPException(status_code=400, detail="解析后 Cookie 为空，请检查格式")

    pool = await _get_pool()
    try:
        # 确保表存在
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS merchant_sync_cookies (
                id SERIAL PRIMARY KEY,
                merchant_id VARCHAR(100) NOT NULL DEFAULT 'default',
                cookie_json JSONB NOT NULL,
                cookie_string TEXT,
                is_active BOOLEAN NOT NULL DEFAULT true,
                last_verified_at TIMESTAMP,
                last_sync_at TIMESTAMP,
                last_sync_status VARCHAR(50),
                last_sync_error TEXT,
                records_synced_total INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Upsert cookie
        await pool.execute(
            """
            INSERT INTO merchant_sync_cookies
                (merchant_id, cookie_json, cookie_string, is_active, updated_at)
            VALUES ($1, $2::jsonb, $3, true, NOW())
            ON CONFLICT (merchant_id) DO UPDATE SET
                cookie_json = $2::jsonb,
                cookie_string = $3,
                is_active = true,
                updated_at = NOW()
            """,
            req.merchant_id,
            json.dumps(cookies, ensure_ascii=False),
            req.cookie_string,
        )

        # 同时更新环境文件（写到配置目录，供本地 daemon 使用）
        _try_save_cookie_config(cookies)

        logger.info("商家 %s 提交了 %d 个 Cookie", req.merchant_id, len(cookies))
        return CookieSubmitResponse(
            ok=True,
            message=f"Cookie 已保存，共 {len(cookies)} 个键值对",
            cookie_count=len(cookies),
        )
    except Exception as e:
        logger.error("保存 Cookie 失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存失败: {e}") from e


def _try_save_cookie_config(cookies: dict[str, str]) -> None:
    """尝试将 Cookie 保存到配置文件（供本地 daemon 使用）。"""
    import json
    from pathlib import Path

    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "qnh_cookies.json"
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
        logger.debug("Cookie 已写入 %s", config_path)
    except Exception as e:
        logger.warning("写入 Cookie 配置文件失败 (非致命): %s", e)


# ── Status API ──────────────────────────────────────────────────────────────


@router.get("/status", response_model=APIResponse[dict[str, Any]])
async def sync_status() -> APIResponse[dict[str, Any]]:
    """查看整体同步状态：最后同步时间、是否正常、数据量。"""
    pool = await _get_pool()

    # 获取 sync_state 表数据
    syncer_rows: list[dict] = []
    try:
        rows = await pool.fetch(
            """SELECT syncer_name, last_full_sync, last_incremental_sync,
                      last_sync_status, last_sync_error, records_synced,
                      last_sync_duration_ms, updated_at
               FROM sync_state ORDER BY syncer_name"""
        )
        syncer_rows = [dict(r) for r in rows]
    except Exception:
        pass  # 表可能不存在

    # 获取商家 Cookie 状态
    cookie_status: dict[str, Any] = {"configured": False}
    try:
        row = await pool.fetchrow(
            """SELECT merchant_id, last_verified_at, last_sync_at,
                      last_sync_status, last_sync_error, records_synced_total,
                      updated_at, is_active
               FROM merchant_sync_cookies WHERE is_active = true LIMIT 1"""
        )
        if row:
            cookie_status = {
                "configured": True,
                "merchant_id": row["merchant_id"],
                "last_verified_at": row["last_verified_at"].isoformat()
                if row["last_verified_at"]
                else None,
                "last_sync_at": row["last_sync_at"].isoformat() if row["last_sync_at"] else None,
                "last_sync_status": row["last_sync_status"],
                "last_sync_error": row["last_sync_error"],
                "records_synced_total": row["records_synced_total"],
                "cookie_updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
    except Exception:
        pass

    # 获取各数据表的实际数据量
    data_counts: dict[str, Any] = {}
    tables = {
        "products": "qnh_products",
        "orders": "qnh_orders_raw",
        "metrics": "qnh_store_metrics_raw",
        "customers": "qnh_customers_raw",
        "traffic": "qnh_traffic_raw",
        "channels": "qnh_traffic_channels_raw",
    }
    for source, table in tables.items():
        try:
            row = await pool.fetchrow(
                f"SELECT COUNT(*) as cnt, MAX(synced_at) as last FROM {table}"
            )
            data_counts[source] = {
                "count": row["cnt"] if row else 0,
                "last_sync": str(row["last"]) if row and row["last"] else None,
            }
        except Exception:
            data_counts[source] = {"count": 0, "last_sync": None}

    # 整体健康状态
    is_healthy = bool(cookie_status.get("configured")) and (
        cookie_status.get("last_sync_status") in (None, "success", "running")
    )

    return APIResponse(
        data={
            "healthy": is_healthy,
            "cookie": cookie_status,
            "syncers": syncer_rows,
            "data_counts": data_counts,
            "checked_at": datetime.now(UTC).isoformat(),
        },
        message="同步状态正常" if is_healthy else "Cookie 未配置或同步异常，请检查",
    )


# ── Trigger API ─────────────────────────────────────────────────────────────


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
            ProductSyncer(client, None),
            OrderSyncer(client, None),
            InventorySyncer(client, None),
            MetricsSyncer(client, None),
            TrafficSyncer(client, None),
            ReviewSyncer(client, None),
        ]
        for s in syncers:
            try:
                result = await s.sync()  # ← 修复: 调用 sync() 而非 sync_full()
                if not result.success:
                    logger.error("Sync failed for %s: %s", s.name, result.error)
                else:
                    logger.info("Sync OK for %s: %d records", s.name, result.records_synced)
            except Exception:
                logger.exception("Sync exception for %s", s.name)
    except Exception:
        logger.exception("Failed to trigger sync")


@router.post("/trigger", response_model=APIResponse[dict])
async def trigger_sync(bg: BackgroundTasks) -> APIResponse[dict]:
    """手动触发全量同步。"""
    bg.add_task(_trigger_sync_all)
    return APIResponse(
        data={"status": "triggered", "triggered_at": datetime.now(UTC).isoformat()},
        message="已在后台触发全量同步",
    )


@router.post("/{syncer_name}/trigger", response_model=APIResponse[dict])
async def trigger_single_syncer(syncer_name: str, bg: BackgroundTasks) -> APIResponse[dict]:
    syncer_map = {
        "products": ("src.sync.products", "ProductSyncer"),
        "orders": ("src.sync.orders", "OrderSyncer"),
        "inventory": ("src.sync.inventory", "InventorySyncer"),
        "metrics": ("src.sync.metrics", "MetricsSyncer"),
        "traffic": ("src.sync.traffic", "TrafficSyncer"),
        "reviews": ("src.sync.reviews", "ReviewSyncer"),
    }
    if syncer_name not in syncer_map:
        from .errors import NotFoundError

        raise NotFoundError("Syncer", syncer_name)

    module_path, class_name = syncer_map[syncer_name]

    async def _run() -> None:
        try:
            import importlib

            from src.sync.qnh_client import QNHClient

            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            syncer = cls(QNHClient(), None)
            result = await syncer.sync()  # ← 修复: 调用 sync() 而非 sync_full()
            if result.success:
                logger.info("Single sync OK: %s, %d records", syncer_name, result.records_synced)
            else:
                logger.error("Single sync FAILED: %s — %s", syncer_name, result.error)
        except Exception:
            logger.exception("Single sync exception for %s", syncer_name)

    bg.add_task(_run)
    return APIResponse(data={"syncer": syncer_name, "status": "triggered"})


# ── History & legacy ─────────────────────────────────────────────────────────


@router.get("/history", response_model=APIResponse[list[dict]])
async def sync_history(limit: int = 50) -> APIResponse[list[dict]]:
    pool = await _get_pool()
    try:
        rows = await pool.fetch(
            "SELECT * FROM sync_history ORDER BY started_at DESC LIMIT $1", limit
        )
        return APIResponse(data=[dict(r) for r in rows])
    except Exception:
        return APIResponse(data=[], message="sync_history 表不存在")


@router.get("/{syncer_name}/status", response_model=APIResponse[dict])
async def single_syncer_status(syncer_name: str) -> APIResponse[dict]:
    pool = await _get_pool()
    try:
        row = await pool.fetchrow("SELECT * FROM sync_state WHERE syncer_name = $1", syncer_name)
        if not row:
            from .errors import NotFoundError

            raise NotFoundError("Syncer", syncer_name)
        return APIResponse(data=dict(row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
