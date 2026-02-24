"""采集失败告警模块。"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


async def alert_scrape_failure(
    source: str,
    keyword: str,
    error: str,
    db_pool: Any | None = None,
    notifier: Any | None = None,
):
    """采集失败时发送告警。

    Args:
        source: 数据源名称（如 '1688', 'pdd', 'meituan_h5'）
        keyword: 搜索关键词或 URL
        error: 错误信息
        db_pool: 数据库连接池（可选，写入 alerts 表）
        notifier: NotifierSkill 实例（可选，发企业微信）
    """
    msg = f"[采集失败] source={source} keyword={keyword} error={error}"
    logger.error(msg)

    # 1. 写入 alerts 表
    if db_pool:
        try:
            await db_pool.execute(
                """
                INSERT INTO alerts (type, source, keyword, error_message, created_at)
                VALUES ('scrape_failure', $1, $2, $3, $4)
                """,
                source,
                keyword,
                error,
                datetime.now(CST),
            )
        except Exception as e:
            logger.error(f"Failed to write alert to DB: {e}")

    # 2. 发送企业微信通知
    if notifier:
        try:
            await notifier.send(
                title="⚠️ 采集失败告警",
                content=msg,
            )
        except Exception as e:
            logger.error(f"Failed to send alert notification: {e}")
