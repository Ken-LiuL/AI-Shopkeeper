"""数据反馈闭环服务 — 追踪AI推荐的实际效果并反馈到模型权重。"""

from __future__ import annotations

import json
import logging

from src.db import postgres as pg

logger = logging.getLogger(__name__)


class FeedbackLoopService:
    """AI推荐反馈闭环"""

    async def track_selection_outcome(self, run_id: str) -> dict:
        """选品推荐后30天实际表现"""
        pool = pg.get_pool()

        run = await pool.fetchrow(
            "SELECT results, created_at FROM selection_runs WHERE run_id = $1", run_id
        )
        if not run or not run["results"]:
            return {"error": "Run not found"}

        results = run["results"] if isinstance(run["results"], dict) else json.loads(run["results"])
        recs = results.get("recommendations", [])
        created = run["created_at"]

        outcomes = []
        for rec in recs:
            keyword = rec.get("keyword", "")
            # 查找该关键词相关商品的实际销量
            sales = (
                await pool.fetchval(
                    """SELECT COALESCE(SUM(oi.quantity), 0)
                   FROM order_items oi JOIN orders o ON oi.order_id = o.order_id
                   JOIN products p ON oi.product_id = p.product_id
                   WHERE p.name ILIKE $1
                     AND o.order_time >= $2
                     AND o.order_time <= $2 + INTERVAL '30 days'""",
                    f"%{keyword}%",
                    created,
                )
                or 0
            )

            outcomes.append(
                {
                    "keyword": keyword,
                    "predicted_score": rec.get("score", 0),
                    "actual_sales_30d": int(sales),
                    "success": sales > 0,
                }
            )

        # 保存追踪记录
        await pool.execute(
            """INSERT INTO feedback_tracking (tracking_type, reference_id, outcome_data, performance_score)
               VALUES ('selection', $1, $2, $3)""",
            run_id,
            json.dumps(outcomes),
            sum(1 for o in outcomes if o["success"]) / max(len(outcomes), 1),
        )

        return {"run_id": run_id, "outcomes": outcomes}

    async def track_bundle_outcome(self, bundle_id: str) -> dict:
        """套餐推出后销售数据"""
        pool = pg.get_pool()

        bundle = await pool.fetchrow(
            "SELECT bundle_id, name, created_at, products FROM bundles WHERE bundle_id = $1",
            bundle_id,
        )
        if not bundle:
            return {"error": "Bundle not found"}

        products = (
            bundle["products"]
            if isinstance(bundle["products"], list)
            else json.loads(bundle["products"] or "[]")
        )
        product_ids = [p.get("product_id", "") for p in products if p.get("product_id")]

        # 套餐创建后的订单中同时包含这些商品的次数
        if product_ids:
            co_purchase = (
                await pool.fetchval(
                    """SELECT COUNT(DISTINCT o.order_id)
                   FROM orders o
                   WHERE o.order_time >= $1
                     AND (SELECT COUNT(DISTINCT oi.product_id) FROM order_items oi
                          WHERE oi.order_id = o.order_id AND oi.product_id = ANY($2)) = $3""",
                    bundle["created_at"],
                    product_ids,
                    len(product_ids),
                )
                or 0
            )
        else:
            co_purchase = 0

        outcome = {
            "bundle_id": bundle_id,
            "bundle_name": bundle["name"],
            "co_purchases": int(co_purchase),
            "product_count": len(product_ids),
        }

        await pool.execute(
            """INSERT INTO feedback_tracking (tracking_type, reference_id, outcome_data, performance_score)
               VALUES ('bundle', $1, $2, $3)""",
            bundle_id,
            json.dumps(outcome),
            float(co_purchase),
        )

        return outcome

    async def track_pricing_outcome(self, price_change_id: int) -> dict:
        """调价后销量变化"""
        pool = pg.get_pool()

        change = await pool.fetchrow("SELECT * FROM price_history WHERE id = $1", price_change_id)
        if not change:
            return {"error": "Price change not found"}

        # 调价前7天 vs 调价后7天
        before = (
            await pool.fetchval(
                """SELECT COALESCE(SUM(oi.quantity), 0)
               FROM order_items oi JOIN orders o ON oi.order_id = o.order_id
               WHERE oi.product_id = $1
                 AND o.order_time >= $2 - INTERVAL '7 days'
                 AND o.order_time < $2""",
                change["product_id"],
                change["changed_at"],
            )
            or 0
        )

        after = (
            await pool.fetchval(
                """SELECT COALESCE(SUM(oi.quantity), 0)
               FROM order_items oi JOIN orders o ON oi.order_id = o.order_id
               WHERE oi.product_id = $1
                 AND o.order_time >= $2
                 AND o.order_time < $2 + INTERVAL '7 days'""",
                change["product_id"],
                change["changed_at"],
            )
            or 0
        )

        # 更新price_history记录
        await pool.execute(
            "UPDATE price_history SET outcome_tracked = TRUE, sales_before = $1, sales_after = $2 WHERE id = $3",
            int(before),
            int(after),
            price_change_id,
        )

        outcome = {
            "price_change_id": price_change_id,
            "product_id": change["product_id"],
            "old_price": float(change["old_price"]),
            "new_price": float(change["new_price"]),
            "sales_before_7d": int(before),
            "sales_after_7d": int(after),
            "sales_change_pct": round((after - before) / max(before, 1) * 100, 1),
        }

        await pool.execute(
            """INSERT INTO feedback_tracking (tracking_type, reference_id, outcome_data, performance_score)
               VALUES ('pricing', $1, $2, $3)""",
            str(price_change_id),
            json.dumps(outcome),
            (after - before) / max(before, 1),
        )

        return outcome

    async def update_model_weights(self, outcomes: list[dict]) -> dict:
        """根据反馈调整 self-learning 权重"""
        try:
            from src.learning.weight_learner import WeightLearner

            learner = WeightLearner()

            adjustments = {}
            for o in outcomes:
                t = o.get("tracking_type", "")
                score = o.get("performance_score", 0)
                if t == "selection":
                    adjustments["selection_accuracy"] = score
                elif t == "pricing":
                    adjustments["pricing_effectiveness"] = score
                elif t == "bundle":
                    adjustments["bundle_conversion"] = score

            if adjustments:
                await learner.update_weights(adjustments)

            return {"status": "updated", "adjustments": adjustments}
        except ImportError:
            logger.warning("WeightLearner not available, skipping weight update")
            return {"status": "skipped", "reason": "WeightLearner not available"}
