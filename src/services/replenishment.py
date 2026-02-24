"""智能补货建议服务 — 基于安全库存模型生成补货建议和采购单。"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.db import postgres as pg

logger = logging.getLogger(__name__)


@dataclass
class SafetyStock:
    product_id: str
    product_name: str
    avg_daily_sales: float
    std_daily_sales: float
    lead_time_days: int
    safety_stock: int
    reorder_point: int
    current_stock: int


@dataclass
class ReplenishmentItem:
    product_id: str
    product_name: str
    current_stock: int
    safety_stock: int
    suggested_qty: int
    cost_price: float
    estimated_cost: float
    supplier_link: str = ""


@dataclass
class PurchaseOrder:
    order_id: str
    items: list[dict[str, Any]]
    total_cost: float
    status: str = "draft"
    supplier: str = ""
    created_at: str = ""


class ReplenishmentService:
    """智能补货服务"""

    Z_SCORE = 1.65  # 95% 服务水平

    async def calculate_safety_stock(self, product_id: str, lead_time_days: int = 3) -> SafetyStock:
        """计算单品安全库存

        安全库存 = 日均销量 × 补货周期 + Z × 标准差 × √补货周期
        """
        pool = pg.get_pool()

        # 近30天日销量
        rows = await pool.fetch(
            """SELECT COALESCE(SUM(oi.quantity), 0)::int AS qty
               FROM order_items oi
               JOIN orders o ON oi.order_id = o.order_id
               WHERE oi.product_id = $1
                 AND o.order_time >= CURRENT_DATE - INTERVAL '30 days'
               GROUP BY o.order_time::date
               ORDER BY o.order_time::date""",
            product_id,
        )

        daily_sales = [r["qty"] for r in rows]
        # 补齐无销量的天数
        while len(daily_sales) < 30:
            daily_sales.append(0)

        avg = sum(daily_sales) / len(daily_sales)
        variance = sum((x - avg) ** 2 for x in daily_sales) / len(daily_sales)
        std = math.sqrt(variance)

        safety = avg * lead_time_days + self.Z_SCORE * std * math.sqrt(lead_time_days)
        safety_int = math.ceil(safety)
        reorder_point = math.ceil(avg * lead_time_days + safety_int)

        # 当前库存
        product = await pool.fetchrow(
            "SELECT name, stock FROM products WHERE product_id = $1", product_id
        )
        name = product["name"] if product else ""
        current = product["stock"] if product else 0

        return SafetyStock(
            product_id=product_id,
            product_name=name,
            avg_daily_sales=round(avg, 2),
            std_daily_sales=round(std, 2),
            lead_time_days=lead_time_days,
            safety_stock=safety_int,
            reorder_point=reorder_point,
            current_stock=current,
        )

    async def get_replenishment_suggestions(self) -> list[ReplenishmentItem]:
        """扫描所有活跃商品，找出需要补货的"""
        pool = pg.get_pool()
        products = await pool.fetch(
            "SELECT product_id, name, stock, cost_price FROM products WHERE status = 'active'"
        )

        suggestions = []
        for p in products:
            try:
                ss = await self.calculate_safety_stock(p["product_id"])
                if ss.current_stock < ss.safety_stock:
                    gap = ss.safety_stock - ss.current_stock
                    # 建议补到安全库存的1.5倍
                    suggested = math.ceil(gap * 1.5)
                    cost = float(p["cost_price"] or 0)
                    suggestions.append(
                        ReplenishmentItem(
                            product_id=p["product_id"],
                            product_name=p["name"],
                            current_stock=p["stock"],
                            safety_stock=ss.safety_stock,
                            suggested_qty=suggested,
                            cost_price=cost,
                            estimated_cost=round(cost * suggested, 2),
                            supplier_link=f"https://s.1688.com/selloffer/offer_search.htm?keywords={p['name']}",
                        )
                    )
            except Exception as e:
                logger.warning(f"Failed to calculate safety stock for {p['product_id']}: {e}")

        # 按紧急程度排序（库存/安全库存比例）
        suggestions.sort(key=lambda x: x.current_stock / max(x.safety_stock, 1))
        return suggestions

    async def generate_purchase_order(self, items: list[dict]) -> PurchaseOrder:
        """汇总补货建议生成采购单"""
        pool = pg.get_pool()
        order_id = f"po_{uuid.uuid4().hex[:12]}"

        order_items = []
        total = 0.0
        for item in items:
            cost = float(item.get("estimated_cost", 0))
            total += cost
            order_items.append(
                {
                    "product_id": item["product_id"],
                    "product_name": item.get("product_name", ""),
                    "quantity": item.get("suggested_qty", 0),
                    "unit_cost": item.get("cost_price", 0),
                    "estimated_cost": cost,
                }
            )

        import json

        await pool.execute(
            """INSERT INTO purchase_orders (order_id, items, total_cost, status, created_at, updated_at)
               VALUES ($1, $2, $3, 'draft', NOW(), NOW())""",
            order_id,
            json.dumps(order_items),
            total,
        )

        return PurchaseOrder(
            order_id=order_id,
            items=order_items,
            total_cost=round(total, 2),
            status="draft",
            created_at=datetime.now().isoformat(),
        )

    async def get_safety_stock_list(self) -> list[dict]:
        """获取所有活跃商品的安全库存列表"""
        pool = pg.get_pool()
        products = await pool.fetch(
            "SELECT product_id FROM products WHERE status = 'active' LIMIT 100"
        )
        results = []
        for p in products:
            try:
                ss = await self.calculate_safety_stock(p["product_id"])
                results.append(
                    {
                        "product_id": ss.product_id,
                        "product_name": ss.product_name,
                        "current_stock": ss.current_stock,
                        "safety_stock": ss.safety_stock,
                        "reorder_point": ss.reorder_point,
                        "avg_daily_sales": ss.avg_daily_sales,
                        "status": "ok" if ss.current_stock >= ss.safety_stock else "low",
                    }
                )
            except Exception:
                pass
        return results
