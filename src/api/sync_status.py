"""同步健康状态 API。

提供 GET /api/sync/health 端点，返回：
- Cookie 健康状态
- 最后同步时间
- 各数据源新鲜度
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter

from src.db import postgres as pg
from .schemas import APIResponse

router = APIRouter(prefix="/api/sync", tags=["sync"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=APIResponse[dict])
async def sync_health() -> APIResponse[dict]:
    """返回 Cookie 状态、最后同步时间及各数据源新鲜度。

    健康状态说明：
    - OK: 最近 2 小时内有成功同步
    - STALE: 超过 2 小时未成功同步，Cookie 可能已过期
    - UNKNOWN: 没有任何同步记录，或无法连接数据库
    """
    try:
        pool = pg.get_pool()

        from src.sync.cookie_health import check_cookie_health, get_sync_status

        cookie_health, sync_status = await _gather(
            check_cookie_health(pool),
            get_sync_status(pool),
        )

        data = {
            "cookie_health": cookie_health,
            "sync_status": sync_status,
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }

        overall_ok = cookie_health["status"] == "OK"
        return APIResponse(
            success=overall_ok,
            data=data,
            message=cookie_health["message"],
        )

    except Exception as e:
        logger.error("sync_health endpoint failed: %s", e, exc_info=True)
        return APIResponse(
            success=False,
            data={"error": str(e)},
            message=f"同步健康检查失败: {e}",
        )


async def _gather(*coros):
    """Run coroutines concurrently."""
    import asyncio
    return await asyncio.gather(*coros)
