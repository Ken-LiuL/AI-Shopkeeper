"""Inventory management API routes."""

from __future__ import annotations

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
    """从qnh_products表获取当前库存数据（优化性能）"""
    pool = pg.get_pool()

    # 优化：只获取在售商品，限制数量，添加索引字段
    inventory = await pool.fetch(
        """
        SELECT
            spu_id as product_id,
            name,
            retail_price,
            channel_price,
            cost_price,
            category,
            channel_status
        FROM qnh_products
        WHERE retail_price > 0  -- 只查询有价格的商品
        ORDER BY retail_price DESC  -- 优先返回高价值商品
        LIMIT $1
    """,
        limit,
    )

    # Convert to mutable dicts
    inventory = [dict(row) for row in inventory]

    # 为每个商品估算库存（修复JSONB状态判断）
    for item in inventory:
        # 基于商品状态估算库存
        channel_status = item["channel_status"]
        price = item["retail_price"] or 0

        # 判断是否在售（任一平台为"on"）
        is_active = False
        if channel_status and isinstance(channel_status, dict):
            is_active = (
                channel_status.get("meituan") == "on"
                or channel_status.get("eleme") == "on"
                or channel_status.get("jddj") == "on"
            )
        elif channel_status is None and price > 0:
            # 如果没有渠道状态但有价格，认为是在售
            is_active = True

        if is_active:
            # 在售商品假设有库存，根据价格估算
            if price > 500:
                estimated_stock = 20  # 高价商品库存较少
            elif price > 100:
                estimated_stock = 50  # 中价商品
            else:
                estimated_stock = 100  # 低价商品库存较多
        else:
            # 非在售商品
            estimated_stock = 5  # 少量库存

        item["stock"] = estimated_stock

    return inventory


async def _calculate_sales_velocity():
    """基于qnh_store_metrics_raw和商品价格估算销售速度"""
    pool = pg.get_pool()

    # 从metrics获取总体销量数据
    sales_velocity = {}
    try:
        # 获取最新的metrics数据
        metrics_row = await pool.fetchrow("""
            SELECT raw_data FROM qnh_store_metrics_raw
            ORDER BY created_at DESC LIMIT 1
        """)

        if not metrics_row:
            return {}

        metrics = metrics_row["raw_data"]
        if metrics is None:
            return {}
        if isinstance(metrics, str):
            try:
                metrics = json.loads(metrics)
            except (json.JSONDecodeError, TypeError):
                return {}
        if not isinstance(metrics, dict):
            return {}

        # 使用和dashboard一样的_extract_metric函数
        def _extract_metric_local(raw_data: dict, key: str) -> float:
            field = raw_data.get(key, {})
            if not isinstance(field, dict):
                try:
                    return float(field)
                except (TypeError, ValueError):
                    return 0.0

            indic = field.get("indicValue", {})
            if isinstance(indic, dict):
                return float(indic.get("originValue", 0) or 0)
            return 0.0

        # 提取总体销售指标
        total_orders = _extract_metric_local(metrics, "eff_ord_cnt")
        total_gmv = _extract_metric_local(metrics, "sale_amt_gmv")
        avg_order_value = _extract_metric_local(metrics, "unit_price")

        if avg_order_value == 0 and total_orders > 0 and total_gmv > 0:
            avg_order_value = total_gmv / total_orders

        # 获取所有商品进行销量分配
        products = await pool.fetch("""
            SELECT spu_id, name, retail_price, channel_status, category
            FROM qnh_products
            WHERE 1=1
        """)

        # 为每个商品估算销售速度
        total_products = len(products)
        if total_products > 0 and total_orders > 0:
            # 基于价格和状态分配权重
            total_weight = 0
            product_weights = {}

            for product in products:
                price = product["retail_price"] or 50  # 默认价格
                status = product["channel_status"]

                # 计算权重（价格越高，在售状态权重越大）
                if status == "在售":
                    weight = max(1.0, price / avg_order_value) if avg_order_value > 0 else 1.0
                else:  # 缺货
                    weight = 0.1

                product_weights[product["spu_id"]] = weight
                total_weight += weight

            # 分配销量
            for product in products:
                product_id = product["spu_id"]
                weight = product_weights[product_id]

                # 按权重分配订单
                allocated_orders = (weight / total_weight) * total_orders if total_weight > 0 else 0
                avg_daily_sales = allocated_orders / 30.0  # 30天平均

                sales_velocity[product_id] = {
                    "total_30days": int(allocated_orders),
                    "avg_daily": avg_daily_sales,
                    "avg_per_order": 1.2,  # 平均每单商品数
                    "active_days": 30,
                }

    except Exception as e:
        logger.warning(f"Failed to calculate sales velocity from metrics: {e}")

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
    """库存总览 - 从 qnh_products 表获取数据并估算库存"""

    try:
        pool = pg.get_pool()

        # 从qnh_products表获取基本统计（修复JSONB查询）
        overview = await pool.fetchrow("""
            SELECT
                COUNT(*) as total_products,
                -- 修复：正确查询JSONB字段，检查任一平台为"on"状态
                COUNT(CASE
                    WHEN channel_status IS NOT NULL AND (
                        channel_status->>'meituan' = 'on' OR
                        channel_status->>'eleme' = 'on' OR
                        channel_status->>'jddj' = 'on'
                    ) THEN 1
                    -- 如果channel_status为null，用retail_price>0作为在售判断
                    WHEN channel_status IS NULL AND retail_price > 0 THEN 1
                END) as active_products,
                -- 缺货商品：任一平台标记为"off"且没有任何平台"on"
                COUNT(CASE
                    WHEN channel_status IS NOT NULL AND (
                        channel_status->>'meituan' = 'off' OR
                        channel_status->>'eleme' = 'off' OR
                        channel_status->>'jddj' = 'off'
                    ) AND NOT (
                        channel_status->>'meituan' = 'on' OR
                        channel_status->>'eleme' = 'on' OR
                        channel_status->>'jddj' = 'on'
                    ) THEN 1
                END) as out_of_stock_count,
                -- 非活跃：没有任何平台为"on"状态
                COUNT(CASE
                    WHEN channel_status IS NOT NULL AND NOT (
                        channel_status->>'meituan' = 'on' OR
                        channel_status->>'eleme' = 'on' OR
                        channel_status->>'jddj' = 'on'
                    ) THEN 1
                    WHEN channel_status IS NULL AND (retail_price IS NULL OR retail_price <= 0) THEN 1
                END) as inactive_products
            FROM qnh_products
            WHERE category IS NOT NULL AND category != ''
        """)

        # 模拟库存数据：基于商品状态和价格估算库存
        estimated_inventory = await pool.fetch("""
            SELECT
                category,
                COUNT(*) as product_count,
                COUNT(CASE WHEN channel_status::text LIKE '%在售%' THEN 1 END) as active_count,
                COUNT(CASE WHEN channel_status::text LIKE '%缺货%' THEN 1 END) as out_of_stock_count,
                AVG(retail_price) as avg_price,
                -- 基于状态和价格估算库存
                SUM(CASE
                    WHEN channel_status::text LIKE '%在售%' THEN
                        CASE
                            WHEN retail_price > 500 THEN 20  -- 高价商品库存少
                            WHEN retail_price > 100 THEN 50  -- 中价商品
                            ELSE 100  -- 低价商品库存多
                        END
                    WHEN channel_status::text LIKE '%缺货%' THEN 0
                    ELSE 5  -- 其他状态少量库存
                END) as estimated_total_stock
            FROM qnh_products
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category
            ORDER BY estimated_total_stock DESC
        """)

        # 计算总库存
        total_estimated_stock = sum(
            int(row["estimated_total_stock"] or 0) for row in estimated_inventory
        )

        # 估算低库存商品数量（在售商品中价格>200的，假设库存紧张）
        low_stock_estimate = (
            await pool.fetchval("""
            SELECT COUNT(*)
            FROM qnh_products
            WHERE channel_status::text LIKE '%在售%' AND retail_price > 200
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
            "total_products": int(overview["total_products"]) if overview["total_products"] else 0,
            "active_products": int(overview["active_products"])
            if overview["active_products"]
            else 0,
            "total_stock": total_estimated_stock,
            "low_stock_count": int(low_stock_estimate),
            "out_of_stock_count": int(overview["out_of_stock_count"])
            if overview["out_of_stock_count"]
            else 0,
            "avg_stock": round(
                total_estimated_stock / max(int(overview["active_products"] or 1), 1), 2
            ),
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
                    "estimated_stock": int(row["estimated_total_stock"] or 0),
                    "avg_price": round(float(row["avg_price"] or 0), 2),
                    "out_of_stock": int(row["out_of_stock_count"]),
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
                "data_source": "qnh_products (estimated)",
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
