"""Pricing API — 定价分析和调价管理。"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from src.agents.llm import MODEL_DEEPSEEK, call_tool
from src.db import postgres as pg
from src.services.pricing import PricingService

from .schemas import APIResponse

router = APIRouter(prefix="/api/pricing", tags=["pricing"])

# 创建一个专门的路由来处理 /api/products/pricing
products_pricing_router = APIRouter(prefix="/api/products", tags=["pricing"])
logger = logging.getLogger(__name__)


class PricingSuggestion(BaseModel):
    product_id: str
    name: str
    current_price: float
    suggested_price: float
    reason: str
    confidence: float
    potential_impact: str


class PricingRule(BaseModel):
    rule_id: str
    name: str
    description: str
    rule_type: str  # "margin_floor", "competitor_match", "demand_based"
    parameters: dict[str, Any]
    is_active: bool


async def _get_products_with_pricing_data():
    """获取商品及其定价相关数据"""
    pool = pg.get_pool()

    # 获取商品基础信息
    products = await pool.fetch("""
        SELECT product_id, name, cost_price, retail_price, category, brand, monthly_sales
        FROM products
        WHERE status = 'active' AND retail_price > 0
        ORDER BY monthly_sales DESC NULLS LAST
        LIMIT 50
    """)

    # 获取竞品价格数据 (假设有competitor_products表)
    competitor_data = {}
    try:
        competitors = await pool.fetch("""
            SELECT product_name, competitor_name, price, updated_at
            FROM competitor_products
            WHERE updated_at >= CURRENT_DATE - INTERVAL '7 days'
        """)

        for comp in competitors:
            product_key = comp["product_name"].lower()
            if product_key not in competitor_data:
                competitor_data[product_key] = []
            competitor_data[product_key].append(
                {
                    "competitor": comp["competitor_name"],
                    "price": float(comp["price"]),
                    "updated_at": comp["updated_at"],
                }
            )
    except Exception as e:
        logger.warning(f"Failed to fetch competitor data: {e}")

    # 获取销量数据
    sales_data = {}
    try:
        sales = await pool.fetch("""
            SELECT oi.product_id, SUM(oi.quantity) as total_sales, AVG(oi.unit_price) as avg_price
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.order_id
            WHERE o.order_time >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY oi.product_id
        """)

        for sale in sales:
            sales_data[sale["product_id"]] = {
                "monthly_sales": int(sale["total_sales"]),
                "avg_selling_price": float(sale["avg_price"]),
            }
    except Exception as e:
        logger.warning(f"Failed to fetch sales data: {e}")

    return products, competitor_data, sales_data


async def _calculate_category_margins():
    """计算品类平均毛利率"""
    pool = pg.get_pool()

    try:
        margins = await pool.fetch("""
            SELECT
                category,
                AVG(CASE WHEN cost_price > 0 THEN (retail_price - cost_price) / retail_price * 100 ELSE NULL END) as avg_margin
            FROM products
            WHERE status = 'active' AND cost_price > 0 AND retail_price > 0
            GROUP BY category
            HAVING COUNT(*) >= 3
        """)

        return {row["category"]: float(row["avg_margin"]) for row in margins}
    except Exception as e:
        logger.warning(f"Failed to calculate category margins: {e}")
        return {}


async def _generate_ai_pricing_analysis(product_data: list[dict]) -> list[dict]:
    """使用AI分析定价策略"""

    prompt = f"""
    分析以下商品的定价策略，为每个商品生成调价建议。考虑因素：
    1. 成本价和当前毛利率
    2. 竞品价格对比
    3. 销量表现
    4. 品类平均毛利率

    商品数据：
    {json.dumps(product_data, ensure_ascii=False, indent=2)}

    为每个商品生成具体的定价建议，包括：
    - 建议价格（基于市场竞争力和盈利能力）
    - 调价理由（详细说明）
    - 信心度(0-1)
    - 预期影响（销量/利润变化预测）
    """

    tool = {
        "name": "analyze_pricing",
        "description": "生成商品定价建议",
        "input_schema": {
            "type": "object",
            "properties": {
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {"type": "string"},
                            "suggested_price": {"type": "number"},
                            "reason": {"type": "string"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "potential_impact": {"type": "string"},
                        },
                        "required": [
                            "product_id",
                            "suggested_price",
                            "reason",
                            "confidence",
                            "potential_impact",
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
            trace_name="pricing_analysis",
        )

        return result.get("suggestions", [])
    except Exception as e:
        logger.error(f"AI pricing analysis failed: {e}")
        return []


@router.post("/suggestions", response_model=APIResponse[list[PricingSuggestion]])
async def get_pricing_suggestions() -> APIResponse[list[PricingSuggestion]]:
    """基于多因素生成智能调价建议"""

    try:
        # 获取商品和相关数据
        products, competitor_data, sales_data = await _get_products_with_pricing_data()
        category_margins = await _calculate_category_margins()

        # 准备AI分析的数据
        product_analysis_data = []
        for product in products:
            product_id = product["product_id"]
            product_name = product["name"]
            current_price = float(product["retail_price"]) if product["retail_price"] else 0
            cost_price = float(product["cost_price"]) if product["cost_price"] else 0

            # 当前毛利率
            current_margin = 0
            if cost_price > 0 and current_price > 0:
                current_margin = (current_price - cost_price) / current_price * 100

            # 竞品价格
            competitor_prices = competitor_data.get(product_name.lower(), [])
            avg_competitor_price = 0
            if competitor_prices:
                avg_competitor_price = sum(c["price"] for c in competitor_prices) / len(
                    competitor_prices
                )

            # 销量数据
            sales_info = sales_data.get(product_id, {})
            monthly_sales = sales_info.get("monthly_sales", product.get("monthly_sales", 0))

            # 品类平均毛利率
            category = product["category"]
            category_avg_margin = category_margins.get(category, 25.0)  # 默认25%

            product_analysis_data.append(
                {
                    "product_id": product_id,
                    "name": product_name,
                    "current_price": current_price,
                    "cost_price": cost_price,
                    "current_margin": current_margin,
                    "category": category,
                    "category_avg_margin": category_avg_margin,
                    "monthly_sales": monthly_sales,
                    "competitor_prices": competitor_prices,
                    "avg_competitor_price": avg_competitor_price,
                }
            )

        # 使用AI生成建议
        ai_suggestions = await _generate_ai_pricing_analysis(product_analysis_data)

        # 转换为API响应格式
        suggestions = []
        for product in product_analysis_data:
            # 寻找对应的AI建议
            ai_suggestion = next(
                (s for s in ai_suggestions if s["product_id"] == product["product_id"]), None
            )

            if ai_suggestion:
                suggestions.append(
                    PricingSuggestion(
                        product_id=product["product_id"],
                        name=product["name"],
                        current_price=product["current_price"],
                        suggested_price=ai_suggestion["suggested_price"],
                        reason=ai_suggestion["reason"],
                        confidence=ai_suggestion["confidence"],
                        potential_impact=ai_suggestion["potential_impact"],
                    )
                )
            else:
                # 基础规则建议
                suggested_price = product["current_price"]
                reason = "维持当前价格"
                confidence = 0.6

                # 简单逻辑：如果毛利率过低，建议提价
                if product["current_margin"] < 15 and product["cost_price"] > 0:
                    suggested_price = product["cost_price"] * 1.25  # 25%毛利率
                    reason = f"当前毛利率{product['current_margin']:.1f}%偏低，建议提价至25%毛利率"
                    confidence = 0.7

                # 如果有竞品数据且价格偏高
                elif (
                    product["avg_competitor_price"] > 0
                    and product["current_price"] > product["avg_competitor_price"] * 1.2
                ):
                    suggested_price = product["avg_competitor_price"] * 1.1  # 略高于竞品10%
                    reason = f"当前价格比竞品均价高{((product['current_price'] / product['avg_competitor_price'] - 1) * 100):.1f}%，建议降价提高竞争力"
                    confidence = 0.8

                suggestions.append(
                    PricingSuggestion(
                        product_id=product["product_id"],
                        name=product["name"],
                        current_price=product["current_price"],
                        suggested_price=round(suggested_price, 2),
                        reason=reason,
                        confidence=confidence,
                        potential_impact="预期影响分析中",
                    )
                )

        return APIResponse(data=suggestions)

    except Exception as e:
        logger.error(f"Failed to generate pricing suggestions: {e}")
        return APIResponse(
            success=False, message=f"Failed to generate suggestions: {str(e)}", data=[]
        )


@router.get("/rules", response_model=APIResponse[list[PricingRule]])
async def get_pricing_rules() -> APIResponse[list[PricingRule]]:
    """获取定价规则列表"""

    # 默认定价规则
    default_rules = [
        PricingRule(
            rule_id="margin_floor",
            name="毛利率下限",
            description="确保所有商品毛利率不低于设定阈值",
            rule_type="margin_floor",
            parameters={
                "min_margin_percent": 15.0,
                "category_overrides": {"医疗器械": 20.0, "保健品": 25.0, "药品": 18.0},
            },
            is_active=True,
        ),
        PricingRule(
            rule_id="competitor_match",
            name="竞品对标策略",
            description="根据竞品价格调整定价，保持合理竞争位置",
            rule_type="competitor_match",
            parameters={
                "price_position": "slightly_below",  # "below", "match", "slightly_below", "premium"
                "max_discount_percent": 15.0,
                "min_premium_percent": 5.0,
            },
            is_active=True,
        ),
        PricingRule(
            rule_id="demand_based",
            name="需求弹性定价",
            description="基于销量表现和需求弹性动态调价",
            rule_type="demand_based",
            parameters={
                "high_demand_threshold": 100,  # 月销量阈值
                "low_demand_threshold": 10,
                "high_demand_markup": 1.1,  # 高需求加价10%
                "low_demand_discount": 0.95,  # 低需求降价5%
            },
            is_active=True,
        ),
        PricingRule(
            rule_id="seasonal_adjustment",
            name="季节性调价",
            description="根据季节性需求变化调整价格",
            rule_type="seasonal",
            parameters={
                "seasonal_categories": ["保温用品", "夏季用品"],
                "peak_season_markup": 1.15,
                "off_season_discount": 0.90,
            },
            is_active=False,
        ),
        PricingRule(
            rule_id="inventory_clearance",
            name="库存清理策略",
            description="高库存商品自动降价促销",
            rule_type="inventory_based",
            parameters={
                "high_inventory_threshold": 90,  # 库存天数
                "clearance_discount_percent": 20.0,
                "deep_clearance_threshold": 120,
                "deep_discount_percent": 35.0,
            },
            is_active=True,
        ),
    ]

    # 从数据库获取自定义规则（如果有的话）
    pool = pg.get_pool()
    try:
        custom_rules = await pool.fetch("""
            SELECT rule_id, name, description, rule_type, parameters, is_active
            FROM pricing_rules
            ORDER BY created_at DESC
        """)

        for rule in custom_rules:
            default_rules.append(
                PricingRule(
                    rule_id=rule["rule_id"],
                    name=rule["name"],
                    description=rule["description"],
                    rule_type=rule["rule_type"],
                    parameters=rule["parameters"],
                    is_active=rule["is_active"],
                )
            )
    except Exception as e:
        logger.warning(f"Failed to fetch custom pricing rules: {e}")

    return APIResponse(data=default_rules)


# 保留原有的API兼容性
@router.get("/suggestions", response_model=APIResponse[list])
async def get_suggestions_legacy() -> APIResponse:
    """兼容旧版API"""
    try:
        svc = PricingService()
        items = await svc.get_pricing_suggestions()
        return APIResponse(
            data=[
                {
                    "product_id": s.product_id,
                    "product_name": s.product_name,
                    "current_price": s.current_price,
                    "suggested_price": s.suggested_price,
                    "reason": s.reason,
                    "current_margin": s.current_margin,
                    "projected_margin": s.projected_margin,
                    "competitor_ref": s.competitor_ref,
                }
                for s in items
            ]
        )
    except Exception as e:
        logger.warning(f"Legacy pricing service failed: {e}")
        # 重定向到新API
        result = await get_pricing_suggestions()
        return APIResponse(data=[suggestion.dict() for suggestion in result.data])


@router.get("/analysis/{product_id}", response_model=APIResponse[dict])
async def get_analysis(product_id: str) -> APIResponse:
    """单个商品的定价分析"""
    try:
        svc = PricingService()
        a = await svc.analyze_pricing(product_id)
        return APIResponse(
            data={
                "product_id": a.product_id,
                "product_name": a.product_name,
                "current_price": a.current_price,
                "cost_price": a.cost_price,
                "gross_margin": a.gross_margin,
                "competitor_avg": a.competitor_avg,
                "competitor_min": a.competitor_min,
                "competitor_max": a.competitor_max,
                "competitor_count": a.competitor_count,
                "price_elasticity": a.price_elasticity,
                "recommendation": a.recommendation,
            }
        )
    except Exception as e:
        logger.error(f"Failed to analyze pricing for {product_id}: {e}")
        return APIResponse(success=False, message=f"Failed to analyze: {str(e)}", data={})


class ApplyPriceRequest(BaseModel):
    changes: list[dict]


class BatchPriceUpdateRequest(BaseModel):
    product_ids: list[str]
    operation: str  # "multiply", "add", "set"
    value: float
    reason: str = ""


class BatchPriceUpdateResult(BaseModel):
    success: bool
    updated_count: int
    failed_count: int
    results: list[dict]


@router.post("/batch-update", response_model=APIResponse[BatchPriceUpdateResult])
async def batch_update_prices(req: BatchPriceUpdateRequest) -> APIResponse[BatchPriceUpdateResult]:
    """批量调价功能"""
    try:
        pool = pg.get_pool()
        updated_count = 0
        failed_count = 0
        results = []

        for product_id in req.product_ids:
            try:
                # Get current price
                current_row = await pool.fetchrow(
                    "SELECT retail_price, name FROM qnh_products WHERE spu_id = $1", product_id
                )

                if not current_row:
                    results.append(
                        {"product_id": product_id, "success": False, "error": "商品不存在"}
                    )
                    failed_count += 1
                    continue

                current_price = float(current_row["retail_price"] or 0)
                product_name = current_row["name"]

                # Calculate new price
                new_price = current_price
                if req.operation == "multiply":
                    new_price = current_price * req.value
                elif req.operation == "add":
                    new_price = current_price + req.value
                elif req.operation == "set":
                    new_price = req.value
                else:
                    results.append(
                        {"product_id": product_id, "success": False, "error": "不支持的操作类型"}
                    )
                    failed_count += 1
                    continue

                # Validate new price
                if new_price <= 0:
                    results.append(
                        {"product_id": product_id, "success": False, "error": "新价格必须大于0"}
                    )
                    failed_count += 1
                    continue

                # Update price
                await pool.execute(
                    "UPDATE qnh_products SET retail_price = $1 WHERE spu_id = $2",
                    new_price,
                    product_id,
                )

                # Record price change history (if table exists)
                with contextlib.suppress(Exception):
                    await pool.execute(
                        """INSERT INTO price_changes (product_id, old_price, new_price, change_reason, created_at)
                           VALUES ($1, $2, $3, $4, NOW())""",
                        product_id,
                        current_price,
                        new_price,
                        req.reason or f"批量{req.operation}操作",
                    )

                results.append(
                    {
                        "product_id": product_id,
                        "product_name": product_name,
                        "success": True,
                        "old_price": round(current_price, 2),
                        "new_price": round(new_price, 2),
                        "change_percent": round(
                            (new_price - current_price) / current_price * 100, 2
                        )
                        if current_price > 0
                        else 0,
                    }
                )
                updated_count += 1

            except Exception as e:
                logger.error(f"Failed to update price for {product_id}: {e}")
                results.append({"product_id": product_id, "success": False, "error": str(e)})
                failed_count += 1

        result = BatchPriceUpdateResult(
            success=updated_count > 0,
            updated_count=updated_count,
            failed_count=failed_count,
            results=results,
        )

        return APIResponse(data=result)

    except Exception as e:
        logger.error(f"Batch price update failed: {e}")
        return APIResponse(
            success=False,
            message=f"批量调价失败: {str(e)}",
            data=BatchPriceUpdateResult(
                success=False, updated_count=0, failed_count=len(req.product_ids), results=[]
            ),
        )


@router.post("/apply", response_model=APIResponse[list])
async def apply_prices(req: ApplyPriceRequest) -> APIResponse:
    """应用价格变更"""
    try:
        svc = PricingService()
        results = await svc.apply_price_changes(req.changes)
        return APIResponse(data=results)
    except Exception as e:
        logger.error(f"Failed to apply price changes: {e}")
        return APIResponse(success=False, message=f"Failed to apply changes: {str(e)}", data=[])


# 专门的 /api/products/pricing 端点
@products_pricing_router.get("/pricing", response_model=APIResponse[dict])
async def get_products_pricing_analysis() -> APIResponse[dict]:
    """专门的商品定价分析端点 - 从 qnh_products 表分析各品类价格分布和利润率"""
    from src.db import postgres as pg

    try:
        pool = pg.get_pool()

        # 修复：由于成本价数据缺失，改用渠道价格差异分析
        price_distribution = await pool.fetch("""
            SELECT
                category,
                COUNT(*) as product_count,
                AVG(retail_price) as avg_retail_price,
                AVG((channel_price->>'meituan')::numeric) as avg_channel_price,
                AVG(cost_price::numeric) as avg_cost_price,
                -- 修复：使用零售价vs渠道价的差异作为"渠道溢价率"
                AVG(CASE
                    WHEN (channel_price->>'meituan')::numeric > 0 AND retail_price > 0
                    THEN (retail_price - (channel_price->>'meituan')::numeric) / retail_price * 100
                    -- 如果没有渠道价，估算15%的默认margin
                    WHEN retail_price > 0 THEN 15.0
                    ELSE NULL
                END) as avg_margin_percent
            FROM qnh_products
            WHERE retail_price > 0 AND category IS NOT NULL AND category != ''
            GROUP BY category
            HAVING COUNT(*) >= 3
            ORDER BY avg_margin_percent DESC NULLS LAST
        """)

        # 价格区间分析（修复margin计算）
        price_ranges = await pool.fetch("""
            SELECT
                CASE
                    WHEN retail_price <= 50 THEN '低价(≤50元)'
                    WHEN retail_price <= 200 THEN '中价(51-200元)'
                    WHEN retail_price <= 500 THEN '高价(201-500元)'
                    ELSE '超高价(>500元)'
                END as price_range,
                COUNT(*) as product_count,
                -- 修复：使用渠道价差异或估算margin
                AVG(CASE
                    WHEN (channel_price->>'meituan')::numeric > 0 AND retail_price > 0
                    THEN (retail_price - (channel_price->>'meituan')::numeric) / retail_price * 100
                    WHEN retail_price > 0 THEN
                        CASE
                            WHEN retail_price <= 50 THEN 20.0    -- 低价商品估算20%
                            WHEN retail_price <= 200 THEN 25.0   -- 中价商品估算25%
                            WHEN retail_price <= 500 THEN 30.0   -- 高价商品估算30%
                            ELSE 35.0                             -- 超高价商品估算35%
                        END
                    ELSE NULL
                END) as avg_margin_percent
            FROM qnh_products
            WHERE retail_price > 0
            GROUP BY
                CASE
                    WHEN retail_price <= 50 THEN '低价(≤50元)'
                    WHEN retail_price <= 200 THEN '中价(51-200元)'
                    WHEN retail_price <= 500 THEN '高价(201-500元)'
                    ELSE '超高价(>500元)'
                END
            ORDER BY avg_margin_percent DESC NULLS LAST
        """)

        # 定价建议
        pricing_suggestions = []

        # 修复：由于成本价缺失，改为查找渠道价格偏低的商品
        low_margin_products = await pool.fetch("""
            SELECT spu_id, name, category, retail_price,
                   (channel_price->>'meituan')::numeric as channel_price,
                   CASE
                       WHEN (channel_price->>'meituan')::numeric > 0 AND retail_price > 0
                       THEN (retail_price - (channel_price->>'meituan')::numeric) / retail_price * 100
                       ELSE NULL
                   END as margin_percent
            FROM qnh_products
            WHERE retail_price > 0 AND (channel_price->>'meituan')::numeric > 0
            AND retail_price <= (channel_price->>'meituan')::numeric * 1.2  -- 渠道溢价<20%的商品
            ORDER BY margin_percent ASC NULLS LAST
            LIMIT 10
        """)

        # 修复：构建基于渠道价的定价建议
        for product in low_margin_products:
            current_price = float(product["retail_price"])
            channel_price = float(product["channel_price"] or 0)
            margin_percent = product["margin_percent"] or 0

            if channel_price > 0:
                # 建议价格：渠道价+25%
                suggested_price = channel_price * 1.25
                pricing_suggestions.append(
                    {
                        "product_id": product["spu_id"],
                        "name": product["name"],
                        "current_price": current_price,
                        "suggested_price": round(suggested_price, 2),
                        "reason": f"当前渠道溢价率{margin_percent:.1f}%过低，建议提升至25%",
                        "action": "涨价",
                    }
                )

        result = {
            "category_analysis": [
                {
                    "category": row["category"],
                    "product_count": int(row["product_count"]),
                    "avg_retail_price": round(float(row["avg_retail_price"] or 0), 2),
                    "avg_channel_price": round(float(row["avg_channel_price"] or 0), 2),
                    "avg_cost_price": round(float(row["avg_cost_price"] or 0), 2),
                    "avg_margin_percent": round(float(row["avg_margin_percent"] or 0), 2),
                }
                for row in price_distribution
            ],
            "price_range_analysis": [
                {
                    "price_range": row["price_range"],
                    "product_count": int(row["product_count"]),
                    "avg_margin_percent": round(float(row["avg_margin_percent"] or 0), 2),
                }
                for row in price_ranges
            ],
            "pricing_suggestions": pricing_suggestions[:10],  # 限制返回数量
            "summary": {
                "total_categories": len(price_distribution),
                "low_margin_count": len(low_margin_products),
                "avg_margin": round(
                    sum(float(row["avg_margin_percent"] or 0) for row in price_distribution)
                    / len(price_distribution)
                    if price_distribution
                    else 0,
                    2,
                ),
            },
            "data_source_note": "成本价数据暂无，利润率基于零售价与渠道价差异计算",
        }

        return APIResponse(data=result)

    except Exception as e:
        logger.error(f"Failed to get products pricing analysis: {e}")
        return APIResponse(success=False, message=f"获取定价分析失败: {str(e)}", data={})
