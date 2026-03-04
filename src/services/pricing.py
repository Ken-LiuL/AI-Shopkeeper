"""动态定价建议服务 — 基于竞品价格和毛利分析生成调价建议。

融合数据:
  - 结算数据 (qnh_settlements) — 实际平台扣费和配送费
  - 渠道分布 (qnh_traffic_channels_raw) — 高流量渠道薄利多销策略
  - 门店KPI (qnh_store_metrics_raw) — 客单价/支付客单价参考
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.db import postgres as pg
from src.services.raw_data import fetch_latest_raw

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

    async def _get_channel_distribution(self, pool) -> dict:
        """从 qnh_traffic_channels_raw 读取各渠道流量占比。

        高流量渠道可采用薄利多销策略，低流量渠道维持正常利润。
        """
        data = await fetch_latest_raw(pool, "qnh_traffic_channels_raw")
        if not data:
            return {}
        channels = data if isinstance(data, list) else [data]
        result = {}
        for ch in channels:
            name = ch.get("channelName", ch.get("channel", ""))
            ratio = ch.get("orderRatio", ch.get("ratio", 0))
            if name:
                try:
                    result[name] = (
                        float(str(ratio).replace("%", "")) / 100
                        if "%" in str(ratio)
                        else float(ratio)
                    )
                except (ValueError, TypeError):
                    result[name] = 0
        return result

    async def _get_industry_avg_price(self, pool) -> float:
        """从 qnh_store_metrics_raw 读取客单价作为行业参考。

        定价时可参考当前客单价水平，避免定价偏离市场。
        """
        data = await fetch_latest_raw(pool, "qnh_store_metrics_raw")
        if not data:
            return 0
        item = data[0] if isinstance(data, list) else data
        for key in ("customerPrice", "payCustomerPrice", "客单价"):
            val = item.get(key)
            if val is not None:
                try:
                    return float(str(val).replace("¥", "").replace(",", ""))
                except (ValueError, TypeError):
                    continue
        return 0

    async def analyze_pricing(self, product_id: str) -> PricingAnalysis:
        """单品价格分析（融合实际结算费率）"""
        pool = pg.get_pool()

        # Try products table first
        product = await pool.fetchrow(
            "SELECT product_id, name, retail_price, cost_price FROM products WHERE product_id = $1",
            product_id,
        )

        # Fallback to qnh_products table with spu_id
        if not product:
            product = await pool.fetchrow(
                "SELECT spu_id as product_id, name, retail_price, NULL as cost_price FROM qnh_products WHERE spu_id = $1",
                product_id,
            )

        # Fallback: try numeric id lookup
        if not product:
            try:
                pid_int = int(product_id)
                product = await pool.fetchrow(
                    "SELECT spu_id as product_id, name, retail_price, NULL as cost_price FROM qnh_products WHERE id = $1",
                    pid_int,
                )
            except (ValueError, TypeError):
                pass

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

        # 竞品价格 - try both tables
        comp_rows = await pool.fetch(
            """SELECT price FROM competitor_products
               WHERE category = COALESCE(
                   (SELECT category FROM products WHERE product_id = $1),
                   (SELECT category FROM qnh_products WHERE spu_id = $1)
               ) AND price > 0""",
            product_id,
        )
        comp_prices = [float(r["price"]) for r in comp_rows]

        comp_avg = sum(comp_prices) / len(comp_prices) if comp_prices else price
        comp_min = min(comp_prices) if comp_prices else price
        comp_max = max(comp_prices) if comp_prices else price

        # 价格弹性估算（基于历史调价记录）
        elasticity = await self._estimate_elasticity(pool, product_id)

        # 新增: 渠道分布分析 — 高流量渠道适当降低毛利要求
        channel_dist = await self._get_channel_distribution(pool)
        # 新增: 行业客单价参考（可用于日志/未来扩展）
        _industry_avg = await self._get_industry_avg_price(pool)

        # 推荐（融合渠道和行业数据）
        if comp_prices and price > comp_avg * (1 + self.OVERPRICED_THRESHOLD):
            rec = "lower"
        elif margin < self.MARGIN_FLOOR:
            # 如果在高流量渠道占比大，可以适当降低毛利要求
            top_channel_ratio = max(channel_dist.values()) if channel_dist else 0
            adjusted_floor = (
                self.MARGIN_FLOOR * 0.8 if top_channel_ratio > 0.4 else self.MARGIN_FLOOR
            )
            if margin < adjusted_floor:
                rec = "raise"
            else:
                rec = "hold"  # 高流量渠道薄利多销可接受
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
        """批量扫描生成定价建议（优化：批量查询替代逐商品分析）"""
        pool = pg.get_pool()
        suggestions = []

        # Batch pricing analysis: join products with competitor data directly
        try:
            rows = await pool.fetch(
                """SELECT p.product_id, p.name, p.retail_price, p.cost_price, p.category,
                          COALESCE(
                              (SELECT AVG(cp.price) FROM competitor_products cp
                               WHERE cp.category = p.category AND cp.price > 0),
                              0
                          ) AS comp_avg_price,
                          COALESCE(
                              (SELECT COUNT(*) FROM competitor_products cp
                               WHERE cp.category = p.category AND cp.price > 0),
                              0
                          ) AS comp_count
                   FROM products p
                   WHERE p.status = 'active' AND p.retail_price > 0
                   ORDER BY p.retail_price DESC
                   LIMIT 50"""
            )
            for p in rows:
                current_price = float(p["retail_price"] or 0)
                cost = float(p["cost_price"] or current_price * 0.6)
                comp_avg = float(p["comp_avg_price"] or 0)
                margin = (current_price - cost) / current_price if current_price > 0 else 0

                suggested_price = current_price
                reason = "维持现价"

                if comp_avg > 0 and current_price > comp_avg * 1.2:
                    suggested_price = max(comp_avg * 1.1, cost * 1.05)
                    reason = f"高于竞品均价(¥{comp_avg:.0f})，建议降价"
                elif comp_avg > 0 and current_price < comp_avg * 0.8:
                    suggested_price = min(comp_avg * 0.9, current_price * 1.15)
                    reason = f"低于竞品均价(¥{comp_avg:.0f})，可适度提价"
                elif margin < 0.15 and current_price > 10:
                    suggested_price = cost * 1.25
                    reason = f"毛利率仅{margin:.0%}，建议提价保利润"

                if abs(suggested_price - current_price) > 0.5:
                    proj_margin = (
                        (suggested_price - cost) / suggested_price if suggested_price > 0 else 0
                    )
                    suggestions.append(
                        PricingSuggestion(
                            product_id=p["product_id"],
                            product_name=p["name"],
                            current_price=current_price,
                            suggested_price=round(suggested_price, 2),
                            reason=reason,
                            current_margin=round(margin, 4),
                            projected_margin=round(proj_margin, 4),
                            competitor_ref={
                                "avg": comp_avg or current_price,
                                "min": comp_avg * 0.8 if comp_avg > 0 else current_price * 0.8,
                                "max": comp_avg * 1.2 if comp_avg > 0 else current_price * 1.2,
                                "count": int(p["comp_count"]),
                            },
                        )
                    )
            if suggestions:
                return suggestions
        except Exception as e:
            logger.warning(f"Batch pricing analysis failed: {e}")

        # Fallback: use qnh_products directly
        if not suggestions:
            logger.info(
                "No active products in structured table, using qnh_products for pricing suggestions"
            )
            qnh_products = await pool.fetch(
                """SELECT spu_id, name, retail_price, brand, category
                   FROM qnh_products
                   WHERE status = '在售'
                     AND retail_price > 0
                     AND name != ''
                   ORDER BY retail_price DESC
                   LIMIT 30"""
            )

            # Get competitor data for reference
            competitor_avg_price = (
                await pool.fetchval("SELECT AVG(price) FROM competitor_products WHERE price > 0")
                or 0
            )
            competitor_count = (
                await pool.fetchval("SELECT COUNT(*) FROM competitor_products WHERE price > 0") or 0
            )

            # Use store metrics for better analysis
            store_data = await fetch_latest_raw(pool, "qnh_store_metrics_raw")
            if store_data:
                if isinstance(store_data, str):
                    import json

                    store_data = json.loads(store_data)
                # Extract average unit price from metrics
                unit_price_data = store_data.get("unit_price", {})
                if isinstance(unit_price_data, dict):
                    indic = unit_price_data.get("indicValue", {})
                    if isinstance(indic, dict):
                        competitor_avg_price = max(
                            competitor_avg_price, float(indic.get("originValue", 0) or 0)
                        )

            for p in qnh_products:
                current_price = float(p["retail_price"])
                estimated_cost = current_price * 0.6  # Assume 40% margin
                current_margin = 0.3

                # Generate suggestions based on price analysis
                suggested_price = current_price
                reason = "维持现价"

                # Check if price is significantly higher than average
                if competitor_avg_price > 0 and current_price > competitor_avg_price * 1.2:
                    # Don't suggest below cost (estimated_cost = 0.6 * current_price)
                    suggested_price = max(competitor_avg_price * 1.1, estimated_cost * 1.05)
                    reason = f"价格高于市场均价({competitor_avg_price:.2f})，建议适度降价"
                    current_margin = 0.25
                elif current_price < 15:  # Low price products might need adjustment
                    suggested_price = current_price * 1.1
                    reason = "低价商品建议适度提价增加毛利"
                    current_margin = 0.35
                elif current_price > 100:  # High price products could have promotions
                    suggested_price = current_price * 0.95
                    reason = "高价商品建议小幅降价促进销售"
                    current_margin = 0.28

                projected_margin = (
                    (suggested_price - estimated_cost) / suggested_price
                    if suggested_price > 0
                    else 0
                )

                # Sanity check: never suggest less than 50% of current price
                if suggested_price < current_price * 0.5:
                    suggested_price = current_price * 0.95
                    reason = "高价商品建议小幅降价促进销售"
                    projected_margin = (
                        (suggested_price - estimated_cost) / suggested_price
                        if suggested_price > 0
                        else 0
                    )

                # Only add if there's actually a suggestion (not hold)
                if abs(suggested_price - current_price) > 0.1:
                    suggestions.append(
                        PricingSuggestion(
                            product_id=p["spu_id"],
                            product_name=p["name"],
                            current_price=current_price,
                            suggested_price=round(suggested_price, 2),
                            reason=reason,
                            current_margin=round(current_margin, 4),
                            projected_margin=round(projected_margin, 4),
                            competitor_ref={
                                "avg": competitor_avg_price or current_price,
                                "min": competitor_avg_price * 0.8
                                if competitor_avg_price > 0
                                else current_price * 0.8,
                                "max": competitor_avg_price * 1.2
                                if competitor_avg_price > 0
                                else current_price * 1.2,
                                "count": competitor_count,
                            },
                        )
                    )
        else:
            # (Old per-product analyze_pricing loop removed — too slow with 1935 products)
            pass

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
