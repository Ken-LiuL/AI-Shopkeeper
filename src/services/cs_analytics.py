"""客服效果追踪服务 — 统计客服数据、意图分布、转化追踪。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from src.db import postgres as pg

logger = logging.getLogger(__name__)


@dataclass
class CSStats:
    total_inquiries: int = 0
    ai_handled: int = 0
    human_transfer: int = 0
    avg_response_ms: int = 0
    ai_ratio: float = 0
    intent_distribution: dict[str, float] = field(default_factory=dict)
    satisfaction_score: float = 0


@dataclass
class ConversionRecord:
    session_id: str
    product_id: str
    product_name: str
    recommended_at: str
    purchased: bool
    order_id: str | None = None


class CSAnalyticsService:
    """客服效果分析服务"""

    async def get_cs_stats(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> CSStats:
        """获取客服统计数据"""
        pool = pg.get_pool()

        if not start_date:
            start_date = date.today() - timedelta(days=7)
        if not end_date:
            end_date = date.today()

        # 从 cs_analytics 表聚合
        row = await pool.fetchrow(
            """SELECT
                 COALESCE(SUM(total_inquiries), 0)::int AS total,
                 COALESCE(SUM(ai_handled), 0)::int AS ai,
                 COALESCE(SUM(human_transfer), 0)::int AS human,
                 COALESCE(AVG(avg_response_ms), 0)::int AS avg_ms,
                 COALESCE(AVG(satisfaction_score), 0) AS sat
               FROM cs_analytics
               WHERE date >= $1 AND date <= $2""",
            start_date, end_date,
        )

        total = row["total"]
        ai = row["ai"]
        human = row["human"]

        # 如果没有数据，从 sessions 表回退
        if total == 0:
            total = await pool.fetchval(
                """SELECT COUNT(*)::int FROM cs_sessions
                   WHERE created_at::date >= $1 AND created_at::date <= $2""",
                start_date, end_date,
            ) or 0

        # 意图分布聚合
        intent_rows = await pool.fetch(
            """SELECT intent_distribution FROM cs_analytics
               WHERE date >= $1 AND date <= $2 AND intent_distribution != '{}'""",
            start_date, end_date,
        )
        merged: dict[str, int] = {}
        for r in intent_rows:
            dist = r["intent_distribution"] or {}
            if isinstance(dist, str):
                import json
                dist = json.loads(dist)
            for k, v in dist.items():
                merged[k] = merged.get(k, 0) + int(v)

        total_intents = sum(merged.values()) or 1
        intent_pct = {k: round(v / total_intents, 4) for k, v in merged.items()}

        return CSStats(
            total_inquiries=total,
            ai_handled=ai,
            human_transfer=human,
            avg_response_ms=row["avg_ms"],
            ai_ratio=round(ai / max(total, 1), 4),
            intent_distribution=intent_pct,
            satisfaction_score=round(float(row["sat"]), 2),
        )

    async def get_conversion_tracking(
        self, days: int = 7
    ) -> list[ConversionRecord]:
        """获取客服推荐→购买转化记录"""
        pool = pg.get_pool()

        rows = await pool.fetch(
            """SELECT c.session_id, c.product_id, p.name AS product_name,
                      c.recommended_at, c.purchased, c.order_id
               FROM cs_conversion c
               LEFT JOIN products p ON c.product_id = p.product_id
               WHERE c.recommended_at >= CURRENT_DATE - make_interval(days => $1)
               ORDER BY c.recommended_at DESC LIMIT 100""",
            days,
        )

        return [
            ConversionRecord(
                session_id=r["session_id"],
                product_id=r["product_id"],
                product_name=r["product_name"] or "",
                recommended_at=str(r["recommended_at"]),
                purchased=r["purchased"],
                order_id=r["order_id"],
            )
            for r in rows
        ]

    async def record_recommendation(
        self, session_id: str, product_id: str
    ) -> None:
        """记录客服推荐事件"""
        pool = pg.get_pool()
        await pool.execute(
            """INSERT INTO cs_conversion (session_id, product_id, recommended_at)
               VALUES ($1, $2, NOW())""",
            session_id, product_id,
        )

    async def check_conversions(self) -> int:
        """检查24h内推荐后是否产生订单（定时任务调用）"""
        pool = pg.get_pool()

        # 找未确认购买的推荐记录
        pending = await pool.fetch(
            """SELECT c.id, c.product_id, c.recommended_at
               FROM cs_conversion c
               WHERE c.purchased = FALSE
                 AND c.recommended_at >= NOW() - INTERVAL '48 hours'"""
        )

        updated = 0
        for rec in pending:
            # 检查是否有对应订单
            order = await pool.fetchrow(
                """SELECT o.order_id FROM orders o
                   JOIN order_items oi ON o.order_id = oi.order_id
                   WHERE oi.product_id = $1
                     AND o.order_time >= $2
                     AND o.order_time <= $2 + INTERVAL '24 hours'
                   LIMIT 1""",
                rec["product_id"], rec["recommended_at"],
            )
            if order:
                await pool.execute(
                    """UPDATE cs_conversion SET purchased = TRUE, purchased_at = NOW(), order_id = $1
                       WHERE id = $2""",
                    order["order_id"], rec["id"],
                )
                updated += 1

        return updated
