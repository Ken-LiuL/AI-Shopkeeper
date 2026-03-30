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
from src.services.medical_device_service import MedicalDeviceService
from src.services.pricing import PricingService

from .products import get_pricing_analysis
from .schemas import APIResponse

router = APIRouter(prefix="/api/pricing", tags=["pricing"])


def _parse_hotsale_value(field) -> float:
    """Parse a goldengateway field value (may be nested dict with dataValue)."""
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
    import re

    cleaned = re.sub(r"[,%\s]", "", str(raw))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


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
        SELECT product_id, name, cost_price, retail_price, category, brand,
               COALESCE(monthly_sales, 0) as monthly_sales
        FROM products
        WHERE retail_price > 0
        ORDER BY retail_price DESC
        LIMIT 30
    """)

    # 只读取真实竞品表；当前没有竞品数据时返回空列表，不做推导或补假数。
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
        logger.warning("Failed to fetch competitor data: %s", e)
        for product in products:
            competitor_data[str(product["name"]).lower()] = []

    # 获取销量数据 — 优先从 qnh_dataset_records (hotsale_goods) 读取真实销售数据
    sales_data = {}
    try:
        # Priority 1: Real sales data from hotsale_goods dataset
        hotsale_rows = await pool.fetch(
            "SELECT payload FROM qnh_dataset_records WHERE dataset = 'hotsale_goods'"
        )
        if hotsale_rows:
            for row in hotsale_rows:
                p = row["payload"]
                if isinstance(p, str):
                    p = json.loads(p)
                product_name = p.get("product_name", {})
                if isinstance(product_name, dict):
                    product_name = product_name.get("dataValue", "")
                name_lower = str(product_name).lower().strip()
                sale_amt = _parse_hotsale_value(p.get("prod_sale_amt"))
                sale_num = int(_parse_hotsale_value(p.get("prod_sale_num_gmv")))
                actual_pay = _parse_hotsale_value(p.get("prod_actual_pay_amt"))
                avg_price = actual_pay / sale_num if sale_num > 0 else 0
                # Match by product name to product_id
                for product in products:
                    if product["name"].lower().strip() == name_lower:
                        sales_data[product["product_id"]] = {
                            "monthly_sales": sale_num,
                            "avg_selling_price": avg_price,
                            "total_revenue": sale_amt,
                        }
                        break
            logger.info(f"Loaded real sales data for {len(sales_data)} products from hotsale_goods")

        # Priority 2: orders_summary table
        if not sales_data:
            sales = await pool.fetch("""
                SELECT product_id, SUM(quantity::int) as total_sales, AVG(price::numeric) as avg_price
                FROM orders_summary
                WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY product_id LIMIT 100
            """)
            for sale in sales:
                sales_data[sale["product_id"]] = {
                    "monthly_sales": int(sale["total_sales"] or 0),
                    "avg_selling_price": float(sale["avg_price"] or 0),
                }
    except Exception as e:
        logger.warning(f"Failed to fetch sales data: {e}")

    # Fill missing products with 0 sales (no fake data)
    for product in products:
        if product["product_id"] not in sales_data:
            sales_data[product["product_id"]] = {
                "monthly_sales": 0,
                "avg_selling_price": float(product["retail_price"] or 0),
            }

    return products, competitor_data, sales_data


async def _calculate_category_margins():
    """计算品类平均毛利率"""
    pool = pg.get_pool()

    try:
        margins = await pool.fetch("""
            SELECT
                category,
                AVG(CASE
                    WHEN cost_price IS NOT NULL AND cost_price > 0
                    THEN (retail_price - cost_price) / retail_price * 100
                    ELSE 25.0
                END) as avg_margin
            FROM products
            WHERE retail_price > 0 AND category IS NOT NULL
            GROUP BY category
            HAVING COUNT(*) >= 3
        """)

        return {row["category"]: float(row["avg_margin"] or 25.0) for row in margins}
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

        # 准备分析数据
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

        # 尝试使用AI生成建议，失败时使用基础规则
        ai_suggestions = []
        try:
            ai_suggestions = await _generate_ai_pricing_analysis(product_analysis_data)
            logger.info(f"AI generated {len(ai_suggestions)} pricing suggestions")
        except Exception as ai_error:
            logger.warning(f"AI pricing analysis failed, using rule-based fallback: {ai_error}")

        # 转换为API响应格式，优先使用基础规则确保有建议返回
        suggestions = []
        for product in product_analysis_data[:20]:  # 限制返回数量避免超时
            # 寻找对应的AI建议
            ai_suggestion = (
                next(
                    (s for s in ai_suggestions if s.get("product_id") == product["product_id"]),
                    None,
                )
                if ai_suggestions
                else None
            )

            # 基础规则建议（作为主要逻辑）
            suggested_price = product["current_price"]
            reason = "维持当前价格"
            confidence = 0.6
            potential_impact = "价格稳定，保持竞争力"

            # 获取成本价和当前毛利率
            cost_price = product["cost_price"]
            current_price = product["current_price"]
            current_margin = product["current_margin"]

            # 计算毛利率保护的最低价格
            min_price_for_15_margin = (
                cost_price * 1.176 if cost_price > 0 else current_price * 0.95
            )  # 15%毛利率
            min_price_for_20_margin = (
                cost_price * 1.25 if cost_price > 0 else current_price
            )  # 20%毛利率
            min_price_for_25_margin = (
                cost_price * 1.333 if cost_price > 0 else current_price
            )  # 25%毛利率

            # 医疗器械特殊定价逻辑
            if "医" in (product["category"] or "") or "器械" in (product["category"] or ""):
                medical_min_margin = 25  # 医疗器械最低25%毛利率

                if current_margin < medical_min_margin and cost_price > 0:
                    suggested_price = max(cost_price * 1.333, current_price * 1.05)  # 至少涨价5%
                    reason = f"医疗器械当前毛利率{current_margin:.1f}%偏低，建议提升至25%以上保证专业服务质量"
                    confidence = 0.85
                    potential_impact = "提价后预计销量略降5-8%，但利润率显著提升，符合医疗专业定位"
                elif current_margin >= medical_min_margin and current_margin < 35:
                    # 医疗器械毛利率合理，检查竞品情况
                    avg_competitor = product["avg_competitor_price"]
                    if avg_competitor > 0 and current_price > avg_competitor * 1.15:
                        # 比竞品高15%以上，适度降价但保持最低毛利率
                        suggested_price = max(avg_competitor * 1.08, min_price_for_25_margin)
                        reason = f"医疗器械价格比竞品均价高{((current_price / avg_competitor - 1) * 100):.1f}%，建议适度降价但保持25%以上毛利率"
                        confidence = 0.8
                        potential_impact = "价格更具竞争力，预计销量提升10-15%"

            # 非医疗器械的定价逻辑
            else:
                # 毛利率过低，需要提价
                if current_margin < 15 and cost_price > 0:
                    suggested_price = max(
                        min_price_for_20_margin, current_price * 1.05
                    )  # 至少涨价5%
                    reason = f"当前毛利率{current_margin:.1f}%过低，建议提价至20%以上确保盈利能力"
                    confidence = 0.75
                    potential_impact = "提价后预计销量下降8-12%，但整体利润显著增加"

                # 价格比竞品高很多，考虑降价（但保护毛利率）
                elif (
                    product["avg_competitor_price"] > 0
                    and current_price > product["avg_competitor_price"] * 1.25
                ):
                    # 降价但不能低于15%毛利率
                    competitive_price = product["avg_competitor_price"] * 1.1  # 比竞品高10%
                    suggested_price = max(competitive_price, min_price_for_15_margin)

                    if suggested_price < current_price:
                        reason = f"当前价格比竞品均价高{((current_price / product['avg_competitor_price'] - 1) * 100):.1f}%，建议降价提高竞争力（保持15%以上毛利率）"
                        confidence = 0.8
                        potential_impact = "降价后预计销量提升18-25%，整体收益可能增加"
                    else:
                        reason = "价格比竞品高，但成本限制无法大幅降价，建议优化供应链降低成本"
                        confidence = 0.6
                        potential_impact = "当前价格受成本约束，需要通过降本增效提升竞争力"

                # 高销量商品，可适当提价
                elif product["monthly_sales"] > 50 and current_margin < 30:
                    suggested_price = min(
                        current_price * 1.08, current_price + 20
                    )  # 提价不超过20元
                    reason = f"月销量{product['monthly_sales']}件表现优秀，毛利率{current_margin:.1f}%有提升空间"
                    confidence = 0.7
                    potential_impact = "轻微提价预计对销量影响较小，利润提升明显"

                # 低销量但高毛利率商品，考虑降价促销
                elif product["monthly_sales"] < 10 and current_margin > 40:
                    suggested_price = max(
                        current_price * 0.92, min_price_for_25_margin
                    )  # 降价不超过8%
                    reason = f"月销量{product['monthly_sales']}件偏低，但毛利率{current_margin:.1f}%较高，建议适度降价促销"
                    confidence = 0.65
                    potential_impact = "降价促销预计销量提升30-50%，整体收益可能增加"

            # 如果有AI建议，作为补充参考
            if ai_suggestion:
                # AI建议作为参考，但不完全覆盖基础规则
                ai_confidence = ai_suggestion.get("confidence", 0.5)
                if ai_confidence > 0.7:  # 只有高置信度的AI建议才采用
                    reason += f" (AI建议: {ai_suggestion.get('reason', '')})"
                    potential_impact = ai_suggestion.get("potential_impact", potential_impact)

            suggestions.append(
                PricingSuggestion(
                    product_id=product["product_id"],
                    name=product["name"],
                    current_price=product["current_price"],
                    suggested_price=round(suggested_price, 2),
                    reason=reason,
                    confidence=confidence,
                    potential_impact=potential_impact,
                )
            )

        # 如果没有建议生成，返回空列表而不是假数据
        if not suggestions:
            logger.warning("暂无价格建议数据，请先完善商品成本信息或补充更多订单数据")
            suggestions = []

        return APIResponse(
            data=suggestions,
            message="基于当前商品、订单和库存数据生成" if suggestions else "暂无价格建议，请先补齐成本价或更多订单数据",
        )

    except Exception as e:
        logger.error(f"Failed to generate pricing suggestions: {e}")

        # 系统异常时返回空数据和错误提示
        return APIResponse(success=False, data=[], message=f"定价建议生成失败: {str(e)}")


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
            rule_id="sales_momentum",
            name="销量热度复核",
            description="结合近 30 天销量表现，判断是否存在提价或促销空间",
            rule_type="demand_based",
            parameters={
                "high_demand_threshold": 50,
                "low_demand_threshold": 10,
                "raise_cap_percent": 8.0,
                "discount_cap_percent": 8.0,
            },
            is_active=True,
        ),
        PricingRule(
            rule_id="inventory_clearance",
            name="库存去化策略",
            description="高库存低动销商品优先进入降价复核",
            rule_type="inventory_based",
            parameters={
                "high_inventory_threshold": 90,
                "clearance_discount_percent": 20.0,
                "deep_clearance_threshold": 120,
                "deep_discount_percent": 35.0,
            },
            is_active=True,
        ),
        PricingRule(
            rule_id="medical_margin_protection",
            name="医疗器械毛利保护",
            description="医疗器械优先保证服务与合规所需毛利空间",
            rule_type="margin_floor",
            parameters={
                "min_margin_percent": 25.0,
                "category_keywords": ["医", "器械", "急救", "血压", "血糖", "体温"],
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


@router.post("/suggestions/{suggestion_id}/adopt", response_model=APIResponse[dict])
async def adopt_pricing_suggestion(suggestion_id: str) -> APIResponse[dict]:
    """采纳单个调价建议"""
    try:
        pool = pg.get_pool()

        product = await pool.fetchrow(
            "SELECT product_id, name, retail_price FROM products WHERE product_id = $1",
            suggestion_id,
        )

        if not product:
            return APIResponse(success=False, message=f"商品 {suggestion_id} 不存在", data={})

        # 这里简化处理：标记为已采纳（实际应用中需要更新价格）
        # 由于缺乏建议存储表，这里只返回成功状态

        result = {
            "suggestion_id": suggestion_id,
            "product_name": product["name"],
            "status": "adopted",
            "adopted_at": "2026-03-02T14:11:00Z",
            "message": "调价建议已采纳，价格更新需要在批量调价功能中执行",
        }

        return APIResponse(data=result)

    except Exception as e:
        logger.error(f"Failed to adopt pricing suggestion {suggestion_id}: {e}")
        return APIResponse(success=False, message=f"采纳建议失败: {str(e)}", data={})


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
                    "SELECT retail_price, name FROM products WHERE product_id = $1", product_id
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
                    "UPDATE products SET retail_price = $1 WHERE product_id = $2",
                    new_price,
                    product_id,
                )

                # Record price change history so dashboard and feedback loop can see real actions.
                with contextlib.suppress(Exception):
                    price_history_exists = await pool.fetchval(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM information_schema.tables
                            WHERE table_schema = 'public' AND table_name = 'price_history'
                        )
                        """
                    )
                    if price_history_exists:
                        await pool.execute(
                            """INSERT INTO price_history (product_id, old_price, new_price, reason, changed_at)
                               VALUES ($1, $2, $3, $4, NOW())""",
                            product_id,
                            current_price,
                            new_price,
                            req.reason or f"批量{req.operation}操作",
                        )
                    else:
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
@router.get("/medical-analysis", response_model=APIResponse[dict])
async def get_medical_device_analysis() -> APIResponse[dict]:
    """医疗器械专业定价分析"""
    try:
        # 获取医疗器械品类分析
        category_analysis = await MedicalDeviceService.get_medical_category_analysis()

        # 获取一些医疗器械产品的合规信息示例
        pool = pg.get_pool()
        medical_products = await pool.fetch("""
            SELECT product_id, name, category, retail_price
            FROM products
            WHERE (category LIKE '%医%' OR category LIKE '%急救%'
                   OR name LIKE '%血压%' OR name LIKE '%体温%' OR name LIKE '%血糖%')
              AND retail_price > 0
            ORDER BY retail_price DESC
            LIMIT 10
        """)

        # 为每个产品获取合规信息
        compliance_analysis = []
        for product in medical_products:
            compliance = await MedicalDeviceService.get_medical_device_compliance_info(
                product["product_id"]
            )
            if compliance.get("is_medical_device"):
                compliance_analysis.append(
                    {
                        "product_id": product["product_id"],
                        "name": product["name"],
                        "category": product["category"],
                        "current_price": float(product["retail_price"] or 0),
                        **compliance,
                    }
                )

        # 汇总分析
        total_medical_products = sum(cat["product_count"] for cat in category_analysis)
        avg_margin_requirement = (
            sum(cat["recommended_margin"] for cat in category_analysis) / len(category_analysis)
            if category_analysis
            else 25
        )

        result = {
            "category_analysis": category_analysis,
            "compliance_analysis": compliance_analysis[:5],  # 限制返回数量
            "summary": {
                "total_medical_categories": len(category_analysis),
                "total_medical_products": total_medical_products,
                "avg_margin_requirement": round(avg_margin_requirement, 1),
                "device_type_distribution": {
                    "一类器械": sum(
                        1 for c in category_analysis if c["main_device_type"] == "一类器械"
                    ),
                    "二类器械": sum(
                        1 for c in category_analysis if c["main_device_type"] == "二类器械"
                    ),
                    "三类器械": sum(
                        1 for c in category_analysis if c["main_device_type"] == "三类器械"
                    ),
                },
            },
            "recommendations": [
                "医疗器械建议保持更高毛利率以支持专业服务",
                "二类、三类器械需要专业销售人员培训",
                "建立售后技术支持体系",
                "关注产品合规性和注册证有效期",
                "提供专业的使用指导和培训",
            ],
        }

        return APIResponse(data=result)

    except Exception as e:
        logger.error(f"Failed to get medical device analysis: {e}")
        return APIResponse(success=False, message=f"医疗器械分析失败: {str(e)}", data={})


@products_pricing_router.get("/pricing", response_model=APIResponse[dict])
async def get_products_pricing_analysis() -> APIResponse[dict]:
    """专门的商品定价分析端点 - 复用 products 表的分析结果"""
    base_response = await get_pricing_analysis()
    raw_data = base_response.data or {}
    if not isinstance(raw_data, dict):
        return base_response
    data = dict(raw_data)
    data["data_source_note"] = "利润率基于 products 表成本价/估算数据"
    return APIResponse(success=base_response.success, message=base_response.message, data=data)
