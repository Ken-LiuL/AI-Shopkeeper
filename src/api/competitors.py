"""Competitors API — 竞品监控和对比分析。

更新说明：
- 替换 mock 数据生成逻辑，使用真实数据源优先
- 新增明确的演示数据标识
- 基于库存数据生成合理的竞品对比
- 支持历史价格趋势分析
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from src.db import postgres as pg
from src.services.competitor_data_service import CompetitorDataService

from .schemas import APIResponse

router = APIRouter(prefix="/api/competitors", tags=["competitors"])
logger = logging.getLogger(__name__)


class CompetitorPrice(BaseModel):
    competitor_name: str
    price: float
    last_updated: str
    price_change: float = 0.0  # 与上次价格的变化
    availability: str = "有货"
    data_source: str = ""  # 数据源标识
    confidence: float = 0.0  # 数据可信度
    is_demo_data: bool = False  # 是否为演示数据


class ProductCompetitorAnalysis(BaseModel):
    product_id: str
    product_name: str
    our_price: float
    competitor_prices: list[CompetitorPrice]
    price_position: str  # "lowest", "competitive", "premium", "highest"
    avg_competitor_price: float
    price_advantage: float  # 正数表示比竞品便宜，负数表示比竞品贵
    recommendation: str


class CompetitorMonitorResult(BaseModel):
    total_monitored: int
    price_alerts: int
    competitive_products: int
    overpriced_products: int
    underpriced_products: int
    products: list[ProductCompetitorAnalysis]


@router.get("/", response_model=APIResponse[CompetitorMonitorResult])
async def get_competitors_root(limit: int = 20) -> APIResponse[CompetitorMonitorResult]:
    """竞品监控根端点 - 默认返回监控结果，支持 limit 参数"""
    try:
        # 复用 monitor 端点的逻辑
        result = await get_competitor_monitor()
        if result.success and result.data and limit < len(result.data.products):
            # 应用 limit 参数
            limited_result = CompetitorMonitorResult(
                total_monitored=result.data.total_monitored,
                price_alerts=result.data.price_alerts,
                competitive_products=result.data.competitive_products,
                overpriced_products=result.data.overpriced_products,
                underpriced_products=result.data.underpriced_products,
                products=result.data.products[:limit],
            )
            return APIResponse(data=limited_result)
        return result
    except Exception as e:
        logger.error(f"Failed to get competitors root: {e}")
        return APIResponse(
            success=False,
            message=f"竞品数据获取失败: {str(e)}",
            data=CompetitorMonitorResult(
                total_monitored=0,
                price_alerts=0,
                competitive_products=0,
                overpriced_products=0,
                underpriced_products=0,
                products=[],
            ),
        )


@router.get("/monitor", response_model=APIResponse[CompetitorMonitorResult])
async def get_competitor_monitor() -> APIResponse[CompetitorMonitorResult]:
    """获取竞品监控概览 - 使用真实数据源优先"""
    try:
        pool = pg.get_pool()
        competitor_service = CompetitorDataService()

        # 获取主要商品信息
        products = await pool.fetch("""
            SELECT spu_id, name, retail_price, category, brand
            FROM qnh_products
            WHERE retail_price > 0
            ORDER BY retail_price DESC
            LIMIT 20
        """)

        analysis_results = []
        price_alerts = 0
        competitive_count = 0
        overpriced_count = 0
        underpriced_count = 0
        demo_data_count = 0

        for product in products:
            product_id = product["spu_id"]
            product_name = product["name"]
            our_price = float(product["retail_price"])
            category = product["category"] or ""

            # 使用增强版竞品数据服务
            enhanced_prices = await competitor_service.get_enhanced_competitor_prices(
                product_name, our_price, category, product_id
            )

            # 转换为API模型格式
            competitor_prices = []
            for ep in enhanced_prices:
                competitor_prices.append(
                    CompetitorPrice(
                        competitor_name=ep.competitor_name,
                        price=ep.price,
                        last_updated=ep.last_updated,
                        price_change=ep.price_change_7d,
                        availability=ep.availability,
                        data_source=f"{ep.data_source.source_type} (置信度: {ep.data_source.confidence:.1f})",
                        confidence=ep.data_source.confidence,
                        is_demo_data=ep.is_demo_data,
                    )
                )

            # 统计演示数据数量
            if any(cp.is_demo_data for cp in competitor_prices):
                demo_data_count += 1

            # 计算竞品分析
            if competitor_prices:
                avg_price = sum(cp.price for cp in competitor_prices) / len(competitor_prices)
                price_advantage = avg_price - our_price

                # 价格定位判断
                if our_price <= avg_price * 0.95:
                    position = "lowest"
                    underpriced_count += 1
                elif our_price <= avg_price * 1.05:
                    position = "competitive"
                    competitive_count += 1
                elif our_price <= avg_price * 1.20:
                    position = "premium"
                    overpriced_count += 1
                else:
                    position = "highest"
                    overpriced_count += 1
                    price_alerts += 1

                # 生成建议（考虑数据质量）
                avg_confidence = sum(cp.confidence for cp in competitor_prices) / len(
                    competitor_prices
                )
                recommendation = _generate_pricing_recommendation(
                    our_price, avg_price, position, category, avg_confidence
                )

                analysis_results.append(
                    ProductCompetitorAnalysis(
                        product_id=product_id,
                        product_name=product_name,
                        our_price=our_price,
                        competitor_prices=competitor_prices,
                        price_position=position,
                        avg_competitor_price=round(avg_price, 2),
                        price_advantage=round(price_advantage, 2),
                        recommendation=recommendation,
                    )
                )

        result = CompetitorMonitorResult(
            total_monitored=len(analysis_results),
            price_alerts=price_alerts,
            competitive_products=competitive_count,
            overpriced_products=overpriced_count,
            underpriced_products=underpriced_count,
            products=analysis_results,
        )

        # 添加数据质量提示
        if demo_data_count > 0:
            logger.warning(f"有 {demo_data_count} 个商品使用演示数据，建议配置真实竞品数据源")

        return APIResponse(data=result)

    except Exception as e:
        logger.error(f"Failed to get competitor monitor: {e}")
        return APIResponse(
            success=False,
            message=f"竞品监控获取失败: {str(e)}",
            data=CompetitorMonitorResult(
                total_monitored=0,
                price_alerts=0,
                competitive_products=0,
                overpriced_products=0,
                underpriced_products=0,
                products=[],
            ),
        )


# 已移除旧的 mock 数据生成函数，改用 CompetitorDataService


def _generate_pricing_recommendation(
    our_price: float,
    avg_competitor: float,
    position: str,
    category: str,
    data_confidence: float = 1.0,
) -> str:
    """生成定价建议（考虑数据质量）"""

    price_diff_percent = (our_price - avg_competitor) / avg_competitor * 100

    # 数据质量标识
    confidence_note = ""
    if data_confidence < 0.3:
        confidence_note = " ⚠️ 基于演示数据，建议谨慎参考"
    elif data_confidence < 0.7:
        confidence_note = " ℹ️ 基于推算数据，建议结合市场调研"
    elif data_confidence >= 0.9:
        confidence_note = " ✅ 基于真实竞品数据"

    base_recommendation = ""

    if position == "highest":
        if "医" in category or "器械" in category:
            base_recommendation = (
                f"价格比竞品高{price_diff_percent:.1f}%，医疗器械可维持专业定价，建议强化服务差异化"
            )
        else:
            base_recommendation = f"价格比竞品高{price_diff_percent:.1f}%，建议降价至竞品均价附近，预计可提升销量20-30%"

    elif position == "premium":
        base_recommendation = (
            f"价格比竞品高{price_diff_percent:.1f}%，处于合理范围，建议保持价格并强化产品价值宣传"
        )

    elif position == "competitive":
        base_recommendation = "价格与竞品接近，处于理想竞争位置，建议保持当前定价策略"

    else:  # lowest
        if price_diff_percent < -15:
            base_recommendation = (
                f"价格比竞品低{abs(price_diff_percent):.1f}%，可考虑适当提价增加利润空间"
            )
        else:
            base_recommendation = "价格优势明显，有助于快速占领市场份额，建议保持价格优势"

    return base_recommendation + confidence_note


@router.get("/analysis/{product_id}", response_model=APIResponse[ProductCompetitorAnalysis])
async def get_product_competitor_analysis(
    product_id: str,
) -> APIResponse[ProductCompetitorAnalysis]:
    """获取单个商品的竞品分析 - 使用真实数据源优先"""
    try:
        pool = pg.get_pool()
        competitor_service = CompetitorDataService()

        product = await pool.fetchrow(
            """
            SELECT spu_id, name, retail_price, category, brand
            FROM qnh_products
            WHERE spu_id = $1
        """,
            product_id,
        )

        if not product:
            return APIResponse(success=False, message="商品不存在", data=None)

        product_name = product["name"]
        our_price = float(product["retail_price"] or 0)
        category = product["category"] or ""

        if our_price <= 0:
            return APIResponse(success=False, message="商品价格信息不完整", data=None)

        # 使用增强版竞品数据服务
        enhanced_prices = await competitor_service.get_enhanced_competitor_prices(
            product_name, our_price, category, product_id
        )

        if enhanced_prices:
            # 转换为API模型格式
            competitor_prices = []
            for ep in enhanced_prices:
                competitor_prices.append(
                    CompetitorPrice(
                        competitor_name=ep.competitor_name,
                        price=ep.price,
                        last_updated=ep.last_updated,
                        price_change=ep.price_change_7d,
                        availability=ep.availability,
                        data_source=f"{ep.data_source.source_type} (置信度: {ep.data_source.confidence:.1f})",
                        confidence=ep.data_source.confidence,
                        is_demo_data=ep.is_demo_data,
                    )
                )

            avg_price = sum(cp.price for cp in competitor_prices) / len(competitor_prices)
            price_advantage = avg_price - our_price

            # 价格定位
            if our_price <= avg_price * 0.95:
                position = "lowest"
            elif our_price <= avg_price * 1.05:
                position = "competitive"
            elif our_price <= avg_price * 1.20:
                position = "premium"
            else:
                position = "highest"

            avg_confidence = sum(cp.confidence for cp in competitor_prices) / len(competitor_prices)
            recommendation = _generate_pricing_recommendation(
                our_price, avg_price, position, category, avg_confidence
            )

            analysis = ProductCompetitorAnalysis(
                product_id=product_id,
                product_name=product_name,
                our_price=our_price,
                competitor_prices=competitor_prices,
                price_position=position,
                avg_competitor_price=round(avg_price, 2),
                price_advantage=round(price_advantage, 2),
                recommendation=recommendation,
            )

            return APIResponse(data=analysis)
        else:
            return APIResponse(success=False, message="暂无竞品价格数据", data=None)

    except Exception as e:
        logger.error(f"Failed to analyze competitor for {product_id}: {e}")
        return APIResponse(success=False, message=f"竞品分析失败: {str(e)}", data=None)


@router.get("/alerts", response_model=APIResponse[list[dict]])
async def get_competitor_alerts() -> APIResponse[list[dict]]:
    """获取竞品价格预警"""
    try:
        # 获取价格异常的产品
        monitor_result = await get_competitor_monitor()

        if not monitor_result.success:
            return APIResponse(success=False, message="获取监控数据失败", data=[])

        alerts = []

        for product in monitor_result.data.products:
            # 价格过高预警
            if product.price_position == "highest":
                alerts.append(
                    {
                        "alert_id": f"price_high_{product.product_id}",
                        "type": "competitor_pricing",
                        "severity": "high",
                        "product_id": product.product_id,
                        "product_name": product.product_name,
                        "title": "价格过高预警",
                        "description": f"商品价格¥{product.our_price}比竞品均价¥{product.avg_competitor_price}高{abs(product.price_advantage):.2f}元",
                        "recommendation": product.recommendation,
                        "created_at": datetime.now().isoformat(),
                        "competitor_details": [
                            {
                                "competitor": cp.competitor_name,
                                "price": cp.price,
                                "availability": cp.availability,
                            }
                            for cp in product.competitor_prices
                        ],
                    }
                )

            # 价格过低预警（可能影响利润）
            elif product.price_position == "lowest" and product.price_advantage > 10:
                alerts.append(
                    {
                        "alert_id": f"price_low_{product.product_id}",
                        "type": "competitor_pricing",
                        "severity": "medium",
                        "product_id": product.product_id,
                        "product_name": product.product_name,
                        "title": "价格偏低提醒",
                        "description": f"商品价格¥{product.our_price}比竞品均价¥{product.avg_competitor_price}低{product.price_advantage:.2f}元，可考虑提价",
                        "recommendation": product.recommendation,
                        "created_at": datetime.now().isoformat(),
                    }
                )

        return APIResponse(data=alerts)

    except Exception as e:
        logger.error(f"Failed to get competitor alerts: {e}")
        return APIResponse(success=False, message=f"获取竞品预警失败: {str(e)}", data=[])


@router.get("/analysis", response_model=APIResponse[dict])
async def get_competitors_analysis() -> APIResponse[dict]:
    """竞品分析汇总 - 聚合竞品监控数据，返回竞争态势总览"""
    try:
        monitor_result = await get_competitor_monitor()

        if not monitor_result.success or not monitor_result.data:
            return APIResponse(
                data={
                    "summary": {
                        "total_monitored": 0,
                        "price_alerts": 0,
                        "competitive_products": 0,
                        "overpriced_products": 0,
                        "underpriced_products": 0,
                    },
                    "price_position_breakdown": {},
                    "top_price_alerts": [],
                    "competitive_advantages": [],
                    "message": "暂无竞品数据，请先配置竞品监控",
                }
            )

        data = monitor_result.data

        # 价格定位分布
        position_breakdown: dict[str, int] = {}
        top_alerts = []
        competitive_advantages = []

        for product in data.products:
            pos = product.price_position
            position_breakdown[pos] = position_breakdown.get(pos, 0) + 1

            if pos == "highest":
                top_alerts.append(
                    {
                        "product_id": product.product_id,
                        "name": product.product_name,
                        "our_price": product.our_price,
                        "avg_competitor_price": product.avg_competitor_price,
                        "price_gap": round(product.our_price - product.avg_competitor_price, 2),
                        "recommendation": product.recommendation,
                    }
                )
            elif pos == "lowest":
                competitive_advantages.append(
                    {
                        "product_id": product.product_id,
                        "name": product.product_name,
                        "our_price": product.our_price,
                        "avg_competitor_price": product.avg_competitor_price,
                        "price_advantage": round(
                            product.avg_competitor_price - product.our_price, 2
                        ),
                    }
                )

        top_alerts.sort(key=lambda x: x["price_gap"], reverse=True)
        competitive_advantages.sort(key=lambda x: x["price_advantage"], reverse=True)

        return APIResponse(
            data={
                "summary": {
                    "total_monitored": data.total_monitored,
                    "price_alerts": data.price_alerts,
                    "competitive_products": data.competitive_products,
                    "overpriced_products": data.overpriced_products,
                    "underpriced_products": data.underpriced_products,
                },
                "price_position_breakdown": position_breakdown,
                "top_price_alerts": top_alerts[:10],
                "competitive_advantages": competitive_advantages[:10],
                "message": f"共监控 {data.total_monitored} 个商品，发现 {data.price_alerts} 个价格预警",
            }
        )
    except Exception as e:
        logger.error("Failed to get competitors analysis: %s", e)
        return APIResponse(
            success=False,
            message=f"竞品分析失败: {str(e)}",
            data={
                "summary": {},
                "top_price_alerts": [],
                "competitive_advantages": [],
                "message": "数据获取失败，请稍后重试",
            },
        )
