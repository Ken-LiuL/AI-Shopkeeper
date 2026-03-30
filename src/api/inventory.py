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
    data_source: str | None = None
    confidence: str | None = None
    note: str | None = None


class InventoryListItem(BaseModel):
    product_id: str
    name: str
    stock: int
    available_stock: int | None = None
    locked_stock: int | None = None
    category: str | None = None
    monthly_sales: int = 0
    retail_price: float | None = None
    stock_value: float | None = None
    coverage_days: float | None = None
    risk_level: str = "normal"
    status: str  # normal | low_stock | out_of_stock
    source: str  # qnh_inventory | qnh_products


async def _table_exists(pool, table_name: str) -> bool:
    try:
        exists = await pool.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = $1
            )
            """,
            table_name,
        )
        return bool(exists)
    except Exception:
        return False


def _to_inventory_item(row: dict, source: str) -> InventoryListItem:
    stock = int(row.get("stock") or row.get("current_stock") or 0)
    available_stock = row.get("available_stock")
    locked_stock = row.get("locked_stock")
    monthly_sales = int(row.get("monthly_sales") or 0)
    daily_sales = (monthly_sales / 30.0) if monthly_sales > 0 else 0
    coverage_days = round(stock / daily_sales, 1) if daily_sales > 0 else None

    if stock == 0 and monthly_sales > 0:
        status = "out_of_stock"
        risk_level = "stockout_but_selling"
    elif stock == 0:
        status = "out_of_stock"
        risk_level = "stockout"
    elif coverage_days is not None and coverage_days <= 7:
        status = "low_stock"
        risk_level = "high"
    elif stock < 10:
        status = "low_stock"
        risk_level = "medium"
    else:
        status = "normal"
        risk_level = "normal"
    return InventoryListItem(
        product_id=str(row.get("product_id") or row.get("sku_id") or ""),
        name=str(row.get("name") or row.get("product_name") or "未命名商品"),
        stock=stock,
        available_stock=int(available_stock) if available_stock is not None else None,
        locked_stock=int(locked_stock) if locked_stock is not None else None,
        category=str(row.get("category") or "") or None,
        monthly_sales=monthly_sales,
        retail_price=float(row.get("retail_price") or 0) if row.get("retail_price") is not None else None,
        stock_value=float(row.get("stock_value") or 0) if row.get("stock_value") is not None else None,
        coverage_days=coverage_days,
        risk_level=risk_level,
        status=status,
        source=source,
    )


async def _fetch_inventory_list(limit: int = 200, low_stock_first: bool = True) -> list[InventoryListItem]:
    pool = pg.get_pool()
    rows: list[dict] = []

    if await _table_exists(pool, "qnh_inventory"):
        try:
            rows = [
                dict(row)
                for row in await pool.fetch(
                    """
                    SELECT
                        qi.sku_id,
                        qi.product_name,
                        COALESCE(qi.stock, qi.current_stock, 0) AS stock,
                        qi.available_stock,
                        qi.locked_stock,
                        qi.stock_value,
                        COALESCE(p.category, '') AS category,
                        COALESCE(p.monthly_sales, 0) AS monthly_sales,
                        p.retail_price
                    FROM qnh_inventory qi
                    LEFT JOIN products p
                      ON COALESCE(NULLIF(p.sku_id, ''), p.product_id) = qi.sku_id
                    ORDER BY
                        CASE
                            WHEN COALESCE(qi.stock, qi.current_stock, 0) = 0 AND COALESCE(p.monthly_sales, 0) > 0 THEN 0
                            WHEN COALESCE(qi.stock, qi.current_stock, 0) = 0 THEN 1
                            WHEN COALESCE(p.monthly_sales, 0) > 0
                                 AND COALESCE(qi.stock, qi.current_stock, 0) < GREATEST(CEIL(COALESCE(p.monthly_sales, 0) / 30.0 * 7), 5) THEN 2
                            ELSE 3
                        END,
                        COALESCE(p.monthly_sales, 0) DESC,
                        COALESCE(qi.stock, qi.current_stock, 0) ASC
                    LIMIT $1
                    """,
                    limit,
                )
            ]
        except Exception:
            rows = []
        if rows:
            items = [_to_inventory_item(row, "qnh_inventory") for row in rows]
            if low_stock_first:
                items.sort(key=lambda x: (x.stock, x.name))
            return items

    if await _table_exists(pool, "qnh_products"):
        try:
            rows = [
                dict(row)
                for row in await pool.fetch(
                    """
                    SELECT
                        COALESCE(NULLIF(qp.sku_id, ''), qp.spu_id) AS sku_id,
                        qp.name AS product_name,
                        COALESCE(qp.stock, 0) AS stock,
                        COALESCE(p.category, qp.category, '') AS category,
                        COALESCE(p.monthly_sales, qp.monthly_sales, 0) AS monthly_sales,
                        COALESCE(p.retail_price, qp.retail_price) AS retail_price,
                        NULL::int AS available_stock,
                        NULL::int AS locked_stock,
                        NULL::numeric AS stock_value
                    FROM qnh_products qp
                    LEFT JOIN products p
                      ON COALESCE(NULLIF(p.sku_id, ''), p.product_id) = COALESCE(NULLIF(qp.sku_id, ''), qp.spu_id)
                    ORDER BY
                        CASE
                            WHEN COALESCE(qp.stock, 0) = 0 AND COALESCE(p.monthly_sales, qp.monthly_sales, 0) > 0 THEN 0
                            WHEN COALESCE(qp.stock, 0) = 0 THEN 1
                            ELSE 2
                        END,
                        COALESCE(p.monthly_sales, qp.monthly_sales, 0) DESC,
                        COALESCE(qp.stock, 0) ASC
                    LIMIT $1
                    """,
                    limit,
                )
            ]
        except Exception:
            rows = []
    if not rows:
        return []

    items = [_to_inventory_item(row, "qnh_products") for row in rows]
    if low_stock_first:
        items.sort(key=lambda x: (x.stock, x.name))
    return items


async def _get_current_inventory(limit: int = 50):
    """从 products 表获取当前库存数据，保持人工导入后的真实库存口径。"""
    pool = pg.get_pool()

    inventory = await pool.fetch(
        """
        SELECT
            product_id,
            name,
            retail_price,
            cost_price,
            category,
            status,
            COALESCE(stock, 0) AS stock,
            COALESCE(monthly_sales, 0) AS monthly_sales
        FROM products
        WHERE retail_price > 0
        ORDER BY
            CASE
                WHEN COALESCE(stock, 0) = 0 AND COALESCE(monthly_sales, 0) > 0 THEN 0
                WHEN COALESCE(stock, 0) < 10 THEN 1
                ELSE 2
            END,
            COALESCE(monthly_sales, 0) DESC,
            updated_at DESC NULLS LAST
        LIMIT $1
    """,
        limit,
    )

    return [dict(row) for row in inventory]


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
        if not await _table_exists(pool, "product_suppliers"):
            return {}, default_suppliers
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
        logger.debug(f"Failed to fetch supplier info: {e}")
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
        suggestions = await _build_restock_suggestions(
            safety_days=int(safety_days),
            min_urgency=str(min_urgency),
            limit=int(limit),
        )
        return APIResponse(data=suggestions)
    except Exception as e:
        logger.error(f"Failed to generate restock suggestions: {e}")
        return APIResponse(
            success=False, message=f"Failed to generate suggestions: {str(e)}", data=[]
        )


async def _build_restock_suggestions(
    *,
    safety_days: int,
    min_urgency: str,
    limit: int,
) -> list[RestockSuggestion]:
    inventory = await _get_current_inventory(limit=limit)
    sales_velocity = await _calculate_sales_velocity()
    supplier_info, default_suppliers = await _get_supplier_info()

    suggestions: list[RestockSuggestion] = []

    for item in inventory:
        product_id = item["product_id"]
        name = item["name"]
        current_stock = int(item["stock"]) if item["stock"] else 0
        category = item["category"] or "其他"

        velocity = sales_velocity.get(product_id, {"avg_daily": 0, "total_30days": 0})
        avg_daily_sales = velocity["avg_daily"]
        sales_source = "hotsale_goods" if avg_daily_sales > 0 else ""

        if avg_daily_sales == 0:
            monthly_sales = float(item.get("monthly_sales") or 0)
            if monthly_sales > 0:
                avg_daily_sales = round(monthly_sales / 30.0, 2)
                sales_source = "monthly_sales"

        if avg_daily_sales <= 0:
            continue

        days_remaining = int(current_stock / avg_daily_sales) if avg_daily_sales > 0 else 999

        supplier = supplier_info.get(product_id)
        if not supplier:
            supplier = default_suppliers.get(category, {"name": "默认供应商", "lead_time": 7})

        lead_time = supplier["lead_time"]
        suggested_qty = 0
        urgency = "low"

        if days_remaining <= lead_time:
            urgency = "high"
            suggested_qty = int((safety_days + lead_time * 2) * avg_daily_sales - current_stock)
        elif days_remaining <= safety_days:
            urgency = "medium"
            suggested_qty = int((safety_days + lead_time) * avg_daily_sales - current_stock)
        elif days_remaining <= safety_days * 2 and avg_daily_sales > 1:
            urgency = "low"
            suggested_qty = int(safety_days * avg_daily_sales)

        if suggested_qty <= 0:
            continue

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
                data_source=sales_source or "verified_sales",
                confidence="high" if velocity["avg_daily"] > 0 else "medium",
                note="基于真实销量与当前库存生成",
            )
        )

    for suggestion in suggestions:
        days_remaining = suggestion.days_remaining
        if days_remaining <= 3:
            suggestion.urgency = "high"
        elif days_remaining <= 7:
            suggestion.urgency = "medium"
        else:
            suggestion.urgency = "low"

    urgency_order = {"high": 3, "medium": 2, "low": 1}
    suggestions.sort(key=lambda x: (urgency_order[x.urgency], -x.avg_daily_sales), reverse=True)

    if min_urgency != "low":
        urgency_filter = {"high": ["high"], "medium": ["high", "medium"]}
        suggestions = [s for s in suggestions if s.urgency in urgency_filter.get(min_urgency, [])]

    return suggestions


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

        category_inventory = await pool.fetch("""
            SELECT
                category,
                COUNT(*) as product_count,
                COUNT(*) FILTER (WHERE status = 'active') as active_count,
                COUNT(*) FILTER (WHERE COALESCE(stock, 0) = 0) as out_of_stock_count,
                SUM(COALESCE(stock, 0)) as total_stock,
                AVG(retail_price) as avg_price,
                SUM(COALESCE(monthly_sales, 0)) as total_monthly_sales
            FROM products
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category
            ORDER BY total_stock DESC NULLS LAST
        """)

        total_stock = sum(int(row["total_stock"] or 0) for row in category_inventory)
        total_monthly_sales = sum(int(row["total_monthly_sales"] or 0) for row in category_inventory)
        stock_coverage_days = round(total_stock / max(total_monthly_sales / 30.0, 1), 1) if total_stock > 0 and total_monthly_sales > 0 else 0
        turnover_rate = round((total_monthly_sales * 12) / max(total_stock, 1), 2) if total_stock > 0 and total_monthly_sales > 0 else 0

        low_stock_estimate = (
            await pool.fetchval("""
            SELECT COUNT(*)
            FROM products
            WHERE status = 'active'
              AND (
                    (COALESCE(monthly_sales, 0) >= 100 AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.5)
                 OR (COALESCE(monthly_sales, 0) >= 30 AND COALESCE(monthly_sales, 0) < 100 AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.3)
                 OR (COALESCE(monthly_sales, 0) < 30 AND COALESCE(stock, 0) < 5)
                  )
        """)
            or 0
        )

        # 计算补货建议
        try:
            restock_suggestions = await _build_restock_suggestions(
                safety_days=7,
                min_urgency="low",
                limit=20,
            )
            high_priority = len([s for s in restock_suggestions if s.urgency == "high"])
            medium_priority = len([s for s in restock_suggestions if s.urgency == "medium"])
            total_suggestions = len(restock_suggestions)
        except Exception:
            high_priority = medium_priority = total_suggestions = 0

        result = {
            "total_products": int(overview["total_products"] or 0),
            "active_products": int(overview["active_products"] or 0),
            "total_stock": total_stock,
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
                    "out_of_stock": int(row["out_of_stock_count"] or 0),
                }
                for row in category_inventory
            ],
            "inventory_health": {
                "stock_coverage_days": stock_coverage_days,
                "turnover_rate": turnover_rate,
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
                       COALESCE(monthly_sales, 0) AS monthly_sales,
                       CASE
                           WHEN COALESCE(monthly_sales, 0) >= 100 THEN CEIL(COALESCE(monthly_sales, 0) * 0.5)
                           WHEN COALESCE(monthly_sales, 0) >= 30  THEN CEIL(COALESCE(monthly_sales, 0) * 0.3)
                           ELSE 5
                       END AS threshold
                FROM products
                WHERE status = 'active'
            """)

        if rows:
            normal, low_stock, out_of_stock = [], [], []
            for r in rows:
                stock = int(r["stock"] or 0)
                threshold = int(r["threshold"] or 5)
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

        return APIResponse(
            data={
                "summary": {
                    "normal": 0,
                    "low_stock": 0,
                    "out_of_stock": 0,
                },
                "low_stock_products": [],
                "out_of_stock_products": [],
                "data_source": "products",
                "note": "暂无可验证库存状态数据，请先导入商品和库存表。",
            }
        )

    except Exception as e:
        logger.error("Failed to get inventory status: %s", e)
        return APIResponse(success=False, message=f"获取库存状态失败: {str(e)}", data={})


@router.get("/list", response_model=APIResponse[list[InventoryListItem]])
async def get_inventory_list(
    limit: int = Query(200, ge=1, le=1000, description="返回库存商品数量"),
    low_stock_first: bool = Query(True, description="是否按低库存优先排序"),
) -> APIResponse[list[InventoryListItem]]:
    """库存列表（优先 qnh_inventory，无则回退 qnh_products）。"""
    try:
        items = await _fetch_inventory_list(limit=limit, low_stock_first=low_stock_first)
        return APIResponse(data=items)
    except Exception as e:
        logger.error("Failed to fetch inventory list: %s", e)
        return APIResponse(success=False, message=f"获取库存列表失败: {str(e)}", data=[])


@router.get("/low-stock", response_model=APIResponse[list[InventoryListItem]])
async def get_low_stock_inventory(
    limit: int = Query(200, ge=1, le=1000, description="返回低库存商品数量"),
) -> APIResponse[list[InventoryListItem]]:
    """低库存预警列表（stock < 10）。"""
    try:
        items = await _fetch_inventory_list(limit=limit, low_stock_first=True)
        return APIResponse(data=[item for item in items if item.stock < 10])
    except Exception as e:
        logger.error("Failed to fetch low-stock inventory: %s", e)
        return APIResponse(success=False, message=f"获取低库存列表失败: {str(e)}", data=[])


@router.get("/out-of-stock", response_model=APIResponse[list[InventoryListItem]])
async def get_out_of_stock_inventory(
    limit: int = Query(200, ge=1, le=1000, description="返回断货商品数量"),
) -> APIResponse[list[InventoryListItem]]:
    """断货列表（stock = 0）。"""
    try:
        items = await _fetch_inventory_list(limit=limit, low_stock_first=True)
        return APIResponse(data=[item for item in items if item.stock == 0])
    except Exception as e:
        logger.error("Failed to fetch out-of-stock inventory: %s", e)
        return APIResponse(success=False, message=f"获取断货列表失败: {str(e)}", data=[])
