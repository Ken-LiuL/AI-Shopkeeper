"""动态定价建议服务 — 基于竞品价格和毛利分析生成调价建议。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.db import postgres as pg

logger = logging.getLogger(__name__)


@dataclass
class PricingAnalysis:
    product_id: str
    product_name: str
    current_price: float
    cost_price: float
    gross_margin: float  # 毛利率
    competitor_avg: float
    competitor_min: float
    competitor_max: float
    competitor_count: int
    price_elasticity: float  # 估算
    recommendation: str  # "lower" | "raise" | "hold" | "promote"


@dataclass
class PricingSuggestion:
    product_id: str
    product_name: str
    current_price: float
    suggested_price: float
    reason: str
    current_margin: float
    projected_margin: float
    competitor_ref: dict[str, Any] = field(default_factory=dict)


class PricingService:
    """动态定价服务

    融合财务结算数据:
      - 定价建议考虑真实平台扣费和配送费
      - 毛利计算用实际结算数据（佣金率、配送费、活动分摊）
    """

    MARGIN_FLOOR = 0.20  # 最低毛利率20%
    OVERPRICED_THRESHOLD = 0.15  # 高于竞品均价15%认为偏高

    async def _get_platform_fee_rate(self, pool, channel: str = "meituan") -> dict:
        """从结算数据计算实际平台费率。"""
        try:
            row = await pool.fetchrow(
                """
                SELECT
                    AVG(CASE WHEN gross_income > 0 THEN platform_fee / gross_income ELSE 0 END) as avg_platform_rate,
                    AVG(CASE WHEN gross_income > 0 THEN commission_fee / gross_income ELSE 0 END) as avg_commission_rate,
                    AVG(CASE WHEN order_count > 0 THEN delivery_fee / order_count ELSE 0 END) as avg_delivery_per_order,
                    AVG(CASE WHEN gross_income > 0 THEN promotion_fee / gross_income ELSE 0 END) as avg_promotion_rate
                FROM qnh_settlements
                WHERE channel = $1
                  AND period_end >= CURRENT_DATE - INTERVAL '90 days'
                """,
                channel,
            )
            if row:
                return {
                    "platform_rate": float(row["avg_platform_rate"] or 0),
                    "commission_rate": float(row["avg_commission_rate"] or 0),
                    "delivery_per_order": float(row["avg_delivery_per_order"] or 0),
                    "promotion_rate": float(row["avg_promotion_rate"] or 0),
                }
        except Exception as e:
            logger.warning(f"Failed to get platform fee rates: {e}")
        return {
            "platform_rate": 0.05,
            "commission_rate": 0.03,
            "delivery_per_order": 5.0,
            "promotion_rate": 0.02,
        }

    async def analyze_pricing(self, product_id: str) -> PricingAnalysis:
        """单品价格分析（融合实际结算费率）"""
        pool = pg.get_pool()

        product = await pool.fetchrow(
            "SELECT product_id, name, retail_price, cost_price FROM products WHERE product_id = $1",
            product_id,
        )
        if not product:
            raise ValueError(f"Product {product_id} not found")

        price = float(product["retail_price"] or 0)
        cost = float(product["cost_price"] or 0)

        # 使用实际结算费率计算真实毛利
        fee_rates = await self._get_platform_fee_rate(pool)
        total_fee_rate = (
            fee_rates["platform_rate"] + fee_rates["commission_rate"] + fee_rates["promotion_rate"]
        )
        real_cost = cost + price * total_fee_rate + fee_rates["delivery_per_order"]
        margin = (price - real_cost) / price if price > 0 else 0

        # 竞品价格
        comp_rows = await pool.fetch(
            """SELECT price FROM competitor_products
               WHERE category = (SELECT category FROM products WHERE product_id = $1)
                 AND price > 0""",
            product_id,
        )
        comp_prices = [float(r["price"]) for r in comp_rows]

        comp_avg = sum(comp_prices) / len(comp_prices) if comp_prices else price
        comp_min = min(comp_prices) if comp_prices else price
        comp_max = max(comp_prices) if comp_prices else price

        # 价格弹性估算（基于历史调价记录）
        elasticity = await self._estimate_elasticity(pool, product_id)

        # 推荐
        if comp_prices and price > comp_avg * (1 + self.OVERPRICED_THRESHOLD):
            rec = "lower"
        elif margin < self.MARGIN_FLOOR:
            rec = "raise"
        else:
            # 检查销量趋势
            trend = await self._sales_trend(pool, product_id)
            rec = "promote" if trend < -0.1 else "hold"

        return PricingAnalysis(
            product_id=product_id,
            product_name=product["name"],
            current_price=price,
            cost_price=cost,
            gross_margin=round(margin, 4),
            competitor_avg=round(comp_avg, 2),
            competitor_min=round(comp_min, 2),
            competitor_max=round(comp_max, 2),
            competitor_count=len(comp_prices),
            price_elasticity=round(elasticity, 2),
            recommendation=rec,
        )

    async def get_pricing_suggestions(self) -> list[PricingSuggestion]:
        """批量扫描生成定价建议"""
        pool = pg.get_pool()
        products = await pool.fetch(
            "SELECT product_id FROM products WHERE status = 'active' AND retail_price > 0"
        )

        suggestions = []
        for p in products:
            try:
                analysis = await self.analyze_pricing(p["product_id"])
                if analysis.recommendation == "hold":
                    continue

                suggested, reason = self._calc_suggested_price(analysis)
                cost = analysis.cost_price
                proj_margin = (suggested - cost) / suggested if suggested > 0 else 0

                suggestions.append(
                    PricingSuggestion(
                        product_id=analysis.product_id,
                        product_name=analysis.product_name,
                        current_price=analysis.current_price,
                        suggested_price=round(suggested, 2),
                        reason=reason,
                        current_margin=round(analysis.gross_margin, 4),
                        projected_margin=round(proj_margin, 4),
                        competitor_ref={
                            "avg": analysis.competitor_avg,
                            "min": analysis.competitor_min,
                            "max": analysis.competitor_max,
                            "count": analysis.competitor_count,
                        },
                    )
                )
            except Exception as e:
                logger.warning(f"Pricing analysis failed for {p['product_id']}: {e}")

        return suggestions

    async def apply_price_changes(self, changes: list[dict]) -> list[dict]:
        """批量应用调价并记录历史"""
        pool = pg.get_pool()
        results = []

        for c in changes:
            pid = c["product_id"]
            new_price = float(c["new_price"])
            reason = c.get("reason", "manual")

            old = await pool.fetchval(
                "SELECT retail_price FROM products WHERE product_id = $1", pid
            )
            old_price = float(old or 0)

            await pool.execute(
                "UPDATE products SET retail_price = $1 WHERE product_id = $2",
                new_price,
                pid,
            )
            await pool.execute(
                """INSERT INTO price_history (product_id, old_price, new_price, reason, changed_at)
                   VALUES ($1, $2, $3, $4, NOW())""",
                pid,
                old_price,
                new_price,
                reason,
            )
            results.append(
                {
                    "product_id": pid,
                    "old_price": old_price,
                    "new_price": new_price,
                    "status": "applied",
                }
            )

        return results

    # ── 私有方法 ──

    def _calc_suggested_price(self, a: PricingAnalysis) -> tuple[float, str]:
        if a.recommendation == "lower":
            # 降到竞品均价附近，但保证最低毛利
            target = a.competitor_avg * 0.98
            floor = a.cost_price / (1 - self.MARGIN_FLOOR) if a.cost_price > 0 else target
            suggested = max(target, floor)
            return (
                suggested,
                f"价格高于竞品均价{((a.current_price / a.competitor_avg - 1) * 100):.0f}%，建议降价",
            )

        elif a.recommendation == "raise":
            # 提价到至少20%毛利
            target = a.cost_price / (1 - self.MARGIN_FLOOR)
            return (
                target,
                f"当前毛利率{a.gross_margin:.0%}低于{self.MARGIN_FLOOR:.0%}下限，建议涨价",
            )

        elif a.recommendation == "promote":
            # 促销价降5-10%
            suggested = a.current_price * 0.92
            floor = a.cost_price / (1 - 0.10)  # 至少10%毛利
            return max(suggested, floor), "销量下降，建议促销引流"

        return a.current_price, "维持现价"

    async def _estimate_elasticity(self, pool, product_id: str) -> float:
        """基于历史调价记录估算价格弹性"""
        rows = await pool.fetch(
            """SELECT old_price, new_price, sales_before, sales_after
               FROM price_history
               WHERE product_id = $1 AND sales_before > 0 AND sales_after > 0
               ORDER BY changed_at DESC LIMIT 5""",
            product_id,
        )
        if not rows:
            return -1.0  # 默认弹性

        elasticities = []
        for r in rows:
            pct_price = (r["new_price"] - r["old_price"]) / r["old_price"]
            pct_sales = (r["sales_after"] - r["sales_before"]) / r["sales_before"]
            if abs(pct_price) > 0.01:
                elasticities.append(pct_sales / pct_price)

        return sum(elasticities) / len(elasticities) if elasticities else -1.0

    async def _sales_trend(self, pool, product_id: str) -> float:
        """近期vs前期销量变化率"""
        recent = (
            await pool.fetchval(
                """SELECT COALESCE(SUM(oi.quantity), 0)
               FROM order_items oi JOIN orders o ON oi.order_id = o.order_id
               WHERE oi.product_id = $1 AND o.order_time >= CURRENT_DATE - INTERVAL '7 days'""",
                product_id,
            )
            or 0
        )

        prev = (
            await pool.fetchval(
                """SELECT COALESCE(SUM(oi.quantity), 0)
               FROM order_items oi JOIN orders o ON oi.order_id = o.order_id
               WHERE oi.product_id = $1
                 AND o.order_time >= CURRENT_DATE - INTERVAL '14 days'
                 AND o.order_time < CURRENT_DATE - INTERVAL '7 days'""",
                product_id,
            )
            or 0
        )

        if prev == 0:
            return 0.0
        return (recent - prev) / prev
