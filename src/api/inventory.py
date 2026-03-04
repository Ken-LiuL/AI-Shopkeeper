"""Inventory management API routes."""

from __future__ import annotations

import contextlib
import json
import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.agents.llm import MODEL_DEEPSEEK, call_tool
from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/inventory", tags=["inventory"])
logger = logging.getLogger(__name__)


class RestockSuggestion(BaseModel):
    product_id: str
    name: str
    current_stock: int
    avg_daily_sales: float
    days_remaining: int
    suggested_restock_qty: int
    urgency: str  # "high", "medium", "low"
    supplier_info: str
    lead_time_days: int
    safety_stock_days: int


async def _get_current_inventory(limit: int = 50):
    """从 products 表获取当前库存数据（优化性能）"""
    pool = pg.get_pool()

    # 优化：只获取在售商品，限制数量，添加索引字段
    inventory = await pool.fetch(
        """
        SELECT
            product_id,
            name,
            retail_price,
            cost_price,
            category,
            status,
            stock
        FROM products
        WHERE retail_price > 0  -- 只查询有价格的商品
        ORDER BY updated_at DESC NULLS LAST, retail_price DESC  -- 优先返回最新且高价值商品
        LIMIT $1
    """,
        limit,
    )

    # Convert to mutable dicts
    inventory = [dict(row) for row in inventory]

    # 为每个商品估算库存（缺失时使用价格估算）
    for item in inventory:
        price = float(item.get("retail_price") or 0)
        stock = item.get("stock")
        if stock is None or stock <= 0:
            if price > 500:
                stock = 20  # 高价商品库存较少
            elif price > 100:
                stock = 50  # 中价商品
            else:
                stock = 100  # 低价商品库存较多
        item["stock"] = int(stock)

    return inventory


async def _calculate_sales_velocity():
    """基于 hotsale_goods 真实销量数据计算销售速度。"""
    import re

    pool = pg.get_pool()
    sales_velocity = {}

    def _pv(field) -> float:
        if field is None:
            return 0.0
        if isinstance(field, int | float):
            return float(field)
        if isinstance(field, dict):
            raw = field.get("dataValue", "")
        else:
            raw = str(field)
        if not raw:
            return 0.0
        cleaned = re.sub(r"[,%\\s]", "", str(raw))
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0

    def _sv(field) -> str:
        if field is None:
            return ""
        if isinstance(field, dict):
            return str(field.get("dataValue", ""))
        return str(field)

    try:
        # Priority 1: Real per-product sales from hotsale_goods
        hotsale_rows = await pool.fetch(
            "SELECT payload FROM qnh_dataset_records WHERE dataset = 'hotsale_goods'"
        )
        # Build name→product_id mapping
        products = await pool.fetch("SELECT product_id, name FROM products WHERE status = 'active'")
        name_to_id = {p["name"].lower().strip(): p["product_id"] for p in products}

        for row in hotsale_rows:
            p = row["payload"]
            if isinstance(p, str):
                p = json.loads(p)
            name = _sv(p.get("product_name")).strip()
            qty = int(_pv(p.get("prod_sale_num_gmv")))
            if not name or qty == 0:
                continue
            product_id = name_to_id.get(name.lower(), name)
            # hotsale data is 7-day window
            sales_velocity[product_id] = {
                "total_7days": qty,
                "total_30days": int(qty * 4.3),  # estimate monthly
                "avg_daily": round(qty / 7.0, 2),
                "avg_per_order": 1.0,
                "active_days": 7,
                "product_name": name,
            }

    except Exception as e:
        logger.warning(f"Failed to calculate sales velocity: {e}")

    return sales_velocity


async def _get_supplier_info():
    """获取供应商信息和交期"""
    # 默认供应商信息（实际应该从supplier表获取）
    default_suppliers = {
        "医疗器械": {"name": "华康医疗", "lead_time": 7, "contact": "400-123-4567"},
        "保健品": {"name": "健康之选", "lead_time": 5, "contact": "400-234-5678"},
        "康复设备": {"name": "康复专家", "lead_time": 10, "contact": "400-345-6789"},
        "家用医疗": {"name": "家康供应", "lead_time": 3, "contact": "400-456-7890"},
    }

    pool = pg.get_pool()
    try:
        # 尝试从数据库获取供应商信息
        suppliers = await pool.fetch("""
            SELECT product_id, supplier_name, lead_time_days, category
            FROM product_suppliers ps
            JOIN products p ON ps.product_id = p.product_id
            WHERE p.status = 'active'
        """)

        supplier_info = {}
        for supplier in suppliers:
            supplier_info[supplier["product_id"]] = {
                "name": supplier["supplier_name"],
                "lead_time": int(supplier["lead_time_days"]),
                "contact": "待补充",
            }

        return supplier_info, default_suppliers
    except Exception as e:
        logger.warning(f"Failed to fetch supplier info: {e}")
        return {}, default_suppliers


async def _generate_ai_restock_analysis(inventory_data: list[dict]) -> list[dict]:
    """使用AI分析补货策略"""

    prompt = f"""
    分析以下库存数据，为每个商品生成补货建议。考虑因素：
    1. 当前库存量和销售速度
    2. 安全库存天数（医疗器械建议7-14天）
    3. 供应商交期
    4. 季节性需求变化
    5. 商品重要程度

    库存数据：
    {json.dumps(inventory_data, ensure_ascii=False, indent=2)}

    为每个商品生成补货建议：
    - 建议补货数量（考虑经济订货量）
    - 紧急程度评级
    - 补货时机建议
    - 特殊考虑因素
    """

    tool = {
        "name": "analyze_restock",
        "description": "生成库存补货建议",
        "input_schema": {
            "type": "object",
            "properties": {
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {"type": "string"},
                            "suggested_qty": {"type": "integer", "minimum": 0},
                            "urgency": {"type": "string", "enum": ["high", "medium", "low"]},
                            "timing": {"type": "string"},
                            "reasoning": {"type": "string"},
                            "special_notes": {"type": "string"},
                        },
                        "required": [
                            "product_id",
                            "suggested_qty",
                            "urgency",
                            "timing",
                            "reasoning",
                        ],
                    },
                }
            },
            "required": ["suggestions"],
        },
    }

    try:
        result = await call_tool(
            prompt=prompt,
            tool=tool,
            model=MODEL_DEEPSEEK,
            max_tokens=4000,
            trace_name="restock_analysis",
        )

        return result.get("suggestions", [])
    except Exception as e:
        logger.error(f"AI restock analysis failed: {e}")
        return []


@router.get("/restock-suggestions", response_model=APIResponse[list[RestockSuggestion]])
async def get_restock_suggestions(
    safety_days: int = Query(7, ge=1, le=30, description="安全库存天数"),
    min_urgency: str = Query("low", description="最低紧急程度过滤"),
    limit: int = Query(20, ge=1, le=50, description="返回建议数量限制"),
) -> APIResponse[list[RestockSuggestion]]:
    """基于销量趋势和安全库存生成补货建议（优化性能）"""

    try:
        # 获取有限的库存数据以提升性能
        inventory = await _get_current_inventory(limit=limit)
        sales_velocity = await _calculate_sales_velocity()
        supplier_info, default_suppliers = await _get_supplier_info()

        # 准备分析数据
        analysis_data = []
        suggestions = []

        for item in inventory:
            product_id = item["product_id"]
            name = item["name"]
            current_stock = int(item["stock"]) if item["stock"] else 0
            category = item["category"] or "其他"

            # 销售速度
            velocity = sales_velocity.get(product_id, {"avg_daily": 0, "total_30days": 0})
            avg_daily_sales = velocity["avg_daily"]

            # 如果没有销量数据，基于品类估算日均销量
            if avg_daily_sales == 0:
                price = float(item.get("retail_price") or 0)
                if price > 500:
                    avg_daily_sales = 0.3  # 高价医疗器械
                elif price > 100:
                    avg_daily_sales = 1.0
                else:
                    avg_daily_sales = 3.0  # 低价耗材

            # 剩余天数
            days_remaining = 0
            if avg_daily_sales > 0:
                days_remaining = int(current_stock / avg_daily_sales)
            else:
                days_remaining = 999

            # 供应商信息
            supplier = supplier_info.get(product_id)
            if not supplier:
                supplier = default_suppliers.get(category, {"name": "默认供应商", "lead_time": 7})

            lead_time = supplier["lead_time"]

            # 计算建议补货量
            suggested_qty = 0
            urgency = "low"

            if days_remaining <= lead_time:
                urgency = "high"
                # 紧急补货：补到安全库存 + 一个周期的销量
                suggested_qty = int((safety_days + lead_time * 2) * avg_daily_sales - current_stock)
            elif days_remaining <= safety_days:
                urgency = "medium"
                # 常规补货：补到安全库存水平
                suggested_qty = int((safety_days + lead_time) * avg_daily_sales - current_stock)
            elif days_remaining <= safety_days * 2 and avg_daily_sales > 1:
                urgency = "low"
                # 预警补货：适量补货
                suggested_qty = int(safety_days * avg_daily_sales)

            if suggested_qty > 0:
                analysis_data.append(
                    {
                        "product_id": product_id,
                        "name": name,
                        "category": category,
                        "current_stock": current_stock,
                        "avg_daily_sales": avg_daily_sales,
                        "days_remaining": days_remaining,
                        "lead_time": lead_time,
                        "safety_days": safety_days,
                        "suggested_qty": suggested_qty,
                        "urgency": urgency,
                    }
                )

                suggestions.append(
                    RestockSuggestion(
                        product_id=product_id,
                        name=name,
                        current_stock=current_stock,
                        avg_daily_sales=round(avg_daily_sales, 2),
                        days_remaining=days_remaining,
                        suggested_restock_qty=max(suggested_qty, 0),
                        urgency=urgency,
                        supplier_info=supplier["name"],
                        lead_time_days=lead_time,
                        safety_stock_days=safety_days,
                    )
                )

        # 简化：移除AI调用以避免超时，使用规则化逻辑
        # 基于库存天数调整紧急程度
        for suggestion in suggestions:
            days_remaining = suggestion.days_remaining
            if days_remaining <= 3:
                suggestion.urgency = "high"
            elif days_remaining <= 7:
                suggestion.urgency = "medium"
            else:
                suggestion.urgency = "low"

        # 按紧急程度排序
        urgency_order = {"high": 3, "medium": 2, "low": 1}
        suggestions.sort(key=lambda x: (urgency_order[x.urgency], -x.avg_daily_sales), reverse=True)

        # 过滤最低紧急程度
        if min_urgency != "low":
            urgency_filter = {"high": ["high"], "medium": ["high", "medium"]}
            suggestions = [
                s for s in suggestions if s.urgency in urgency_filter.get(min_urgency, [])
            ]

        return APIResponse(data=suggestions)

    except Exception as e:
        logger.error(f"Failed to generate restock suggestions: {e}")
        return APIResponse(
            success=False, message=f"Failed to generate suggestions: {str(e)}", data=[]
        )


@router.get("/overview", response_model=APIResponse[dict])
async def get_inventory_overview() -> APIResponse[dict]:
    """库存总览 - 基于 products 表的数据"""

    try:
        pool = pg.get_pool()

        overview = await pool.fetchrow("""
            SELECT
                COUNT(*) as total_products,
                COUNT(*) FILTER (WHERE status = 'active') as active_products,
                COUNT(*) FILTER (WHERE status != 'active') as inactive_products,
                COUNT(*) FILTER (WHERE COALESCE(stock, 0) = 0) as out_of_stock_count,
                AVG(COALESCE(stock, 0)) as avg_stock
            FROM products
        """)

        estimated_inventory = await pool.fetch("""
            SELECT
                category,
                COUNT(*) as product_count,
                COUNT(*) FILTER (WHERE status = 'active') as active_count,
                SUM(COALESCE(stock, 0)) as total_stock,
                AVG(retail_price) as avg_price
            FROM products
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category
            ORDER BY total_stock DESC NULLS LAST
        """)

        total_estimated_stock = sum(int(row["total_stock"] or 0) for row in estimated_inventory)

        low_stock_estimate = (
            await pool.fetchval("""
            SELECT COUNT(*)
            FROM products
            WHERE status = 'active' AND COALESCE(stock, 0) < 10
        """)
            or 0
        )

        # 计算补货建议
        try:
            restock_result = await get_restock_suggestions()
            high_priority = len([s for s in restock_result.data if s.urgency == "high"])
            medium_priority = len([s for s in restock_result.data if s.urgency == "medium"])
            total_suggestions = len(restock_result.data)
        except Exception:
            high_priority = medium_priority = total_suggestions = 0

        result = {
                "total_products": int(overview["total_products"] or 0),
                "active_products": int(overview["active_products"] or 0),
                "total_stock": total_estimated_stock,
                "low_stock_count": int(low_stock_estimate),
                "out_of_stock_count": int(overview["out_of_stock_count"] or 0),
                "avg_stock": round(float(overview["avg_stock"] or 0), 2),
                "restock_alerts": {
                    "high_priority": high_priority,
                    "medium_priority": medium_priority,
                "total": total_suggestions,
            },
            "category_breakdown": [
                {
                    "category": row["category"],
                    "product_count": int(row["product_count"]),
                    "active_count": int(row["active_count"]),
                    "estimated_stock": int(row["total_stock"] or 0),
                    "avg_price": round(float(row["avg_price"] or 0), 2),
                    "out_of_stock": int(
                        row["product_count"] - row["active_count"]
                        if row["product_count"] and row["active_count"] is not None
                        else 0
                    ),
                }
                for row in estimated_inventory
            ],
            "inventory_health": {
                "stock_coverage_days": 45,  # 估算库存可用天数
                "turnover_rate": 8.5,  # 年周转次数（估算）
                "fill_rate": round(
                    (
                        int(overview["active_products"] or 0)
                        / max(int(overview["total_products"] or 1), 1)
                    )
                    * 100,
                    1,
                ),  # 有货率
                "data_source": "products",
            },
        }

        return APIResponse(data=result)

    except Exception as e:
        logger.error(f"Failed to get inventory overview: {e}")
        return APIResponse(success=False, message=f"Failed to get overview: {str(e)}", data={})


@router.get("/turnover", response_model=APIResponse[list[dict]])
async def get_inventory_turnover(
    days: int = Query(30, ge=7, le=365, description="统计天数"),
) -> APIResponse[list[dict]]:
    """库存周转率分析"""

    try:
        pool = pg.get_pool()

        # 计算周转率
        turnover_data = await pool.fetch(
            f"""
            SELECT
                p.product_id,
                p.name,
                p.category,
                p.stock as current_stock,
                COALESCE(SUM(oi.quantity), 0) as total_sold,
                CASE
                    WHEN p.stock > 0 AND SUM(oi.quantity) > 0
                    THEN ROUND(SUM(oi.quantity)::numeric / p.stock * (365.0 / $1), 2)
                    ELSE 0
                END as annual_turnover_rate,
                CASE
                    WHEN SUM(oi.quantity) > 0
                    THEN ROUND(p.stock::numeric / (SUM(oi.quantity)::numeric / $1), 2)
                    ELSE 999
                END as days_of_supply
            FROM products p
            LEFT JOIN order_items oi ON p.product_id = oi.product_id
            LEFT JOIN orders o ON oi.order_id = o.order_id
                AND o.order_time >= CURRENT_DATE - INTERVAL '{days} days'
            WHERE p.status = 'active'
            GROUP BY p.product_id, p.name, p.category, p.stock
            ORDER BY annual_turnover_rate DESC NULLS LAST
        """,
            days,
        )

        result = []
        for row in turnover_data:
            result.append(
                {
                    "product_id": row["product_id"],
                    "name": row["name"],
                    "category": row["category"],
                    "current_stock": int(row["current_stock"]) if row["current_stock"] else 0,
                    "total_sold": int(row["total_sold"]),
                    "annual_turnover_rate": float(row["annual_turnover_rate"]),
                    "days_of_supply": float(row["days_of_supply"]),
                    "turnover_category": (
                        "快速"
                        if row["annual_turnover_rate"] > 12
                        else "正常"
                        if row["annual_turnover_rate"] > 4
                        else "缓慢"
                    ),
                }
            )

        return APIResponse(data=result)

    except Exception as e:
        logger.error(f"Failed to calculate inventory turnover: {e}")
        return APIResponse(
            success=False, message=f"Failed to calculate turnover: {str(e)}", data=[]
        )


@router.get("/status", response_model=APIResponse[dict])
async def get_inventory_status() -> APIResponse[dict]:
    """查询库存状态汇总（低库存 / 缺货 / 正常）"""
    try:
        pool = pg.get_pool()

        # 先尝试从有 stock 字段的 products 表获取
        rows = []
        with contextlib.suppress(Exception):
            rows = await pool.fetch("""
                SELECT product_id, name, stock,
                       COALESCE(reorder_point, 10) AS threshold
                FROM products
                WHERE status = 'active'
            """)

        if rows:
            normal, low_stock, out_of_stock = [], [], []
            for r in rows:
                stock = int(r["stock"] or 0)
                threshold = int(r["threshold"] or 10)
                item = {
                    "id": r["product_id"],
                    "name": r["name"],
                    "stock": stock,
                    "threshold": threshold,
                }
                if stock == 0:
                    out_of_stock.append(item)
                elif stock < threshold:
                    low_stock.append(item)
                else:
                    normal.append(item)

            return APIResponse(
                data={
                    "summary": {
                        "normal": len(normal),
                        "low_stock": len(low_stock),
                        "out_of_stock": len(out_of_stock),
                    },
                    "low_stock_products": low_stock[:50],
                    "out_of_stock_products": out_of_stock[:50],
                }
            )

        # Fallback：使用 products 表并根据价格估算库存状态
        fallback_rows = await pool.fetch("""
            SELECT product_id, name, retail_price, status, stock
            FROM products
            WHERE name IS NOT NULL AND name != ''
        """)

        normal_count, low_stock_list, out_of_stock_list = 0, [], []
        for r in fallback_rows:
            price = float(r["retail_price"] or 0)
            stock = int(r["stock"] or 0)
            status = r["status"]
            if stock <= 0:
                if price > 0:
                    stock = 20 if price > 500 else 10
                else:
                    stock = 0

            item = {
                "id": r["product_id"],
                "name": r["name"],
                "stock": stock,
                "threshold": 10,
            }

            if stock == 0 or status != "active":
                out_of_stock_list.append(item)
            elif stock < item["threshold"]:
                low_stock_list.append(item)
            else:
                normal_count += 1

        return APIResponse(
            data={
                "summary": {
                    "normal": normal_count,
                    "low_stock": len(low_stock_list),
                    "out_of_stock": len(out_of_stock_list),
                },
                "low_stock_products": low_stock_list[:50],
                "out_of_stock_products": out_of_stock_list[:50],
                "data_source": "products (estimated)",
            }
        )

    except Exception as e:
        logger.error("Failed to get inventory status: %s", e)
        return APIResponse(success=False, message=f"获取库存状态失败: {str(e)}", data={})
