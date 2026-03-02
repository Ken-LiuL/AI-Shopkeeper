"""Data sync status, trigger, and cookie management API routes."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/sync", tags=["sync"])
logger = logging.getLogger(__name__)

SYNC_API_KEY = os.environ.get("SYNC_API_KEY", "")


# ── Pydantic models ─────────────────────────────────────────────────────────

class CookieSubmitRequest(BaseModel):
    """商家提交 Cookie 请求。"""
    cookie_string: str | None = None   # 原始 cookie 字符串，如 "a=1; b=2"
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

        # Upsert cookie — use UPDATE first, then INSERT (avoids partial-index ON CONFLICT issue)
        updated = await pool.execute(
            """
            UPDATE merchant_sync_cookies
            SET cookie_json = $2::jsonb,
                cookie_string = $3,
                is_active = true,
                updated_at = NOW()
            WHERE merchant_id = $1
            """,
            req.merchant_id,
            json.dumps(cookies, ensure_ascii=False),
            req.cookie_string,
        )
        if updated == "UPDATE 0":
            await pool.execute(
                """
                INSERT INTO merchant_sync_cookies
                    (merchant_id, cookie_json, cookie_string, is_active, updated_at)
                VALUES ($1, $2::jsonb, $3, true, NOW())
                ON CONFLICT DO NOTHING
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
                "last_verified_at": row["last_verified_at"].isoformat() if row["last_verified_at"] else None,
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

async def _get_stored_cookies(merchant_id: str = "default") -> dict[str, str] | None:
    """从数据库读取商家存储的 Cookie。"""
    import json as _json
    pool = await _get_pool()
    try:
        row = await pool.fetchrow(
            "SELECT cookie_json FROM merchant_sync_cookies WHERE merchant_id = $1 AND is_active = true LIMIT 1",
            merchant_id,
        )
        if row and row["cookie_json"]:
            data = row["cookie_json"]
            if isinstance(data, str):
                return _json.loads(data)
            return dict(data)
    except Exception as e:
        logger.warning("读取 Cookie 失败: %s", e)
    return None


async def _verify_cookie_with_qnh(cookies: dict[str, str]) -> tuple[bool, str]:
    """用 Cookie 直接发 HTTP 请求到牵牛花 API 验证有效性。
    返回 (success, message)。
    """
    import aiohttp

    QNH_BASE = "https://qnh.meituan.com"
    # 使用一个简单的接口验证 Cookie 有效性
    test_url = f"{QNH_BASE}/api/v1/tenant/modules"
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = {
        "Cookie": cookie_header,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://qnh.meituan.com/",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(test_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                text = await resp.text()
                if resp.status == 200:
                    return True, f"Cookie 验证成功 (HTTP {resp.status})"
                elif resp.status in (401, 403):
                    return False, f"Cookie 已过期或无效 (HTTP {resp.status})"
                else:
                    # 非标准响应，可能是重定向到登录页
                    if "login" in text.lower() or "登录" in text:
                        return False, "Cookie 已失效，需要重新登录"
                    return True, f"服务器响应 {resp.status}，Cookie 可能有效"
    except Exception as e:
        return False, f"网络请求失败: {e}"


async def _trigger_sync_all() -> None:
    """Run all syncers once in background, using stored cookies from DB."""
    pool = await _get_pool()

    # 先从 DB 读取 Cookie
    cookies = await _get_stored_cookies()
    if not cookies:
        logger.error("同步失败：未找到存储的 Cookie，请先在设置页配置牵牛花 Cookie")
        await pool.execute(
            """UPDATE merchant_sync_cookies SET last_sync_status = 'failed',
               last_sync_error = 'Cookie 未配置，请先在设置页配置牵牛花 Cookie',
               last_sync_at = NOW(), updated_at = NOW()
               WHERE is_active = true"""
        )
        return

    # 验证 Cookie
    cookie_valid, verify_msg = await _verify_cookie_with_qnh(cookies)
    logger.info("Cookie 验证结果: %s - %s", cookie_valid, verify_msg)

    if not cookie_valid:
        logger.error("Cookie 无效，停止同步: %s", verify_msg)
        await pool.execute(
            """UPDATE merchant_sync_cookies SET last_sync_status = 'failed',
               last_sync_error = $1, last_verified_at = NOW(),
               last_sync_at = NOW(), updated_at = NOW()
               WHERE is_active = true""",
            f"Cookie 验证失败: {verify_msg}",
        )
        return

    # Cookie 有效，更新验证时间，标记同步中
    await pool.execute(
        """UPDATE merchant_sync_cookies SET last_sync_status = 'running',
           last_verified_at = NOW(), last_sync_error = NULL, updated_at = NOW()
           WHERE is_active = true"""
    )

    # 将 Cookie 写入配置文件，供 QNHAuth 读取
    _try_save_cookie_config(cookies)

    # 尝试用 syncers 同步（QNHAuth 会从配置文件读取 Cookie）
    total_records = 0
    errors = []
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
                result = await s.sync()
                if not result.success:
                    errors.append(f"{s.name}: {result.error}")
                    logger.error("Sync failed for %s: %s", s.name, result.error)
                else:
                    total_records += result.records_synced
                    logger.info("Sync OK for %s: %d records", s.name, result.records_synced)
            except Exception as exc:
                errors.append(f"{s.name}: {exc}")
                logger.exception("Sync exception for %s", s.name)
    except Exception as exc:
        errors.append(f"初始化同步器失败: {exc}")
        logger.exception("Failed to initialize syncers")

    # 更新同步结果
    if errors and total_records == 0:
        error_summary = "; ".join(errors[:3])
        await pool.execute(
            """UPDATE merchant_sync_cookies SET last_sync_status = 'failed',
               last_sync_error = $1, last_sync_at = NOW(), updated_at = NOW()
               WHERE is_active = true""",
            error_summary,
        )
    else:
        await pool.execute(
            """UPDATE merchant_sync_cookies SET last_sync_status = 'success',
               last_sync_error = NULL, last_sync_at = NOW(),
               records_synced_total = records_synced_total + $1, updated_at = NOW()
               WHERE is_active = true""",
            total_records,
        )
        logger.info("同步完成，共同步 %d 条记录", total_records)


@router.post("/trigger", response_model=APIResponse[dict])
async def trigger_sync(bg: BackgroundTasks) -> APIResponse[dict]:
    """手动触发全量同步。"""
    bg.add_task(_trigger_sync_all)
    return APIResponse(data={"status": "triggered", "triggered_at": datetime.now(UTC).isoformat()}, message="已在后台触发全量同步")


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
        row = await pool.fetchrow(
            "SELECT * FROM sync_state WHERE syncer_name = $1", syncer_name
        )
        if not row:
            from .errors import NotFoundError
            raise NotFoundError("Syncer", syncer_name)
        return APIResponse(data=dict(row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
