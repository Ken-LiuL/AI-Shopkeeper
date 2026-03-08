"""
决策效果评估 ETL
- 找到所有 status='accepted' 且创建超过 3 天的决策
- 查询当前指标 vs 基线指标
- 计算效果评分
- 更新 action_tracking 表
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _safe_json_obj(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _calculate_effect_score(
    action_type: str,
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> float:
    """根据行动类型计算效果评分 0-1。"""
    if not baseline or not current:
        return 0.5

    if action_type == "price_adjust":
        old_sales = float(baseline.get("sales_7d") or 0)
        new_sales = float(current.get("sales_7d") or 0)
        if old_sales > 0:
            change = (new_sales - old_sales) / old_sales
            return min(1.0, max(0.0, 0.5 + change))
        return 0.5

    if action_type == "restock":
        new_stock = float(current.get("stock") or 0)
        return 1.0 if new_stock > 10 else 0.3

    if action_type == "promotion":
        old_sales = float(baseline.get("sales_7d") or 0)
        new_sales = float(current.get("sales_7d") or 0)
        if old_sales > 0:
            change = (new_sales - old_sales) / old_sales
            return min(1.0, max(0.0, 0.3 + change * 0.7))
        return 0.5

    return 0.5


async def run_effect_evaluation_etl(pool) -> None:
    """执行效果评估任务。"""
    if not pool:
        return

    pending: list[dict[str, Any]] = []
    try:
        rows = await pool.fetch(
            """
            SELECT *
            FROM action_tracking
            WHERE status = 'accepted'
              AND effect_evaluated_at IS NULL
              AND created_at < NOW() - INTERVAL '3 days'
            ORDER BY created_at
            LIMIT 50
            """
        )
        pending = [dict(row) for row in rows]
    except Exception:
        logger.exception("Failed to query pending action evaluations")
        return

    for action in pending:
        action_id = action.get("action_id", "")
        try:
            baseline = _safe_json_obj(action.get("baseline_metrics"))
            product_id = action.get("product_id")
            action_type = str(action.get("action_type") or "")

            current: dict[str, Any] = {}
            if product_id:
                try:
                    row = await pool.fetchrow(
                        """
                        SELECT stock, retail_price
                        FROM qnh_products
                        WHERE spu_id = $1
                        """,
                        product_id,
                    )
                    if row:
                        current["stock"] = row["stock"]
                        current["price"] = (
                            float(row["retail_price"])
                            if row["retail_price"] is not None
                            else None
                        )
                except Exception:
                    logger.exception("Failed to query product snapshot for %s", action_id)

                try:
                    sales = await pool.fetchval(
                        """
                        SELECT COUNT(*)
                        FROM qnh_orders_raw
                        WHERE payload::text ILIKE '%' || $1 || '%'
                          AND synced_at > NOW() - INTERVAL '7 days'
                        """,
                        product_id,
                    )
                    current["sales_7d"] = int(sales or 0)
                except Exception:
                    logger.exception("Failed to query sales_7d for %s", action_id)

            score = _calculate_effect_score(action_type, baseline, current)

            try:
                await pool.execute(
                    """
                    UPDATE action_tracking
                    SET effect_metrics = $1::jsonb,
                        effect_score = $2,
                        effect_evaluated_at = NOW(),
                        status = 'evaluated',
                        updated_at = NOW()
                    WHERE action_id = $3
                    """,
                    json.dumps(current, default=str),
                    score,
                    action_id,
                )
            except Exception:
                logger.exception("Failed to update effect evaluation for %s", action_id)
        except Exception:
            logger.exception("Effect evaluation failed for %s", action_id)
