"""Selection Agent 各节点实现

融合数据:
  - 退款明细 (qnh_refunds) — 退款率高的 SKU 标记风险
  - 评价NLP (qnh_review_analysis) — 差评关键词作为选品负面信号
  - 热销商品排行 (qnh_products_raw) — 识别增长趋势商品，推荐加大库存
  - 消费排行 (qnh_customers_raw) — 高复购客户偏好商品洞察
  - 渠道分布 (qnh_traffic_channels_raw) — 不同渠道热销品差异分析
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from src.services.raw_data import fetch_latest_raw

from ..llm import MODEL_OPUS, MODEL_PRO, MODEL_SONNET, call_tool, call_tool_with_reflection
from ..prompts.selection import (
    competitor_analysis_prompt,
    gap_identification_prompt,
    inventory_analysis_prompt,
    market_analysis_prompt,
    scorer_prompt,
    scorer_reflection_prompt,
    seasonal_factors_prompt,
    supplier_evaluation_prompt,
)
from ..tools import (
    COMPETITOR_ANALYSIS_TOOL,
    GAP_OPPORTUNITIES_TOOL,
    INVENTORY_ANALYSIS_TOOL,
    MARKET_ANALYSIS_TOOL,
    RECOMMENDATIONS_TOOL,
    SEASONAL_FACTORS_TOOL,
    SUPPLIER_EVALUATION_TOOL,
)
from .state import SelectionState

logger = logging.getLogger(__name__)


async def _get_sku_refund_risk(pool) -> list[dict]:
    """获取高退款率SKU列表作为选品负面信号。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT sku_id, sku_name, refund_reason,
                   COUNT(*) as refund_count,
                   SUM(refund_amount) as total_refund
            FROM qnh_refunds
            WHERE refund_time >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY sku_id, sku_name, refund_reason
            HAVING COUNT(*) >= 2
            ORDER BY refund_count DESC
            LIMIT 30
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to get refund risk data: {e}")
        return []


async def _get_negative_review_signals(pool) -> list[dict]:
    """获取差评关键词和问题类别作为选品负面信号。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT r.extra::json->>'skuId' as sku_id,
                   array_agg(DISTINCT a.summary) as issues,
                   array_agg(DISTINCT kw) as keywords,
                   COUNT(*) as negative_count
            FROM qnh_review_analysis a
            JOIN qnh_reviews r ON a.review_id = r.review_id,
                 jsonb_array_elements_text(a.keywords::jsonb) AS kw
            WHERE a.sentiment = 'negative'
              AND r.review_time >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY r.extra::json->>'skuId'
            HAVING COUNT(*) >= 2
            ORDER BY negative_count DESC
            LIMIT 20
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to get negative review signals: {e}")
        return []


# =============================================================================
# Phase 1: 数据采集（并行）
# =============================================================================


async def fetch_data(state: SelectionState) -> dict:
    """采集所有原始数据（通过 Skills 层）

    融合: 退款风险SKU + 差评关键词 作为选品负面信号。
    """
    # NOTE: 实际实现中通过 ActionBook / Database Skills 获取数据
    # 这里预留接口，数据已由上层注入到 state 中
    now = datetime.now()
    month = now.month
    if month in (3, 4, 5):
        season = "春季"
    elif month in (6, 7, 8):
        season = "夏季"
    elif month in (9, 10, 11):
        season = "秋季"
    else:
        season = "冬季"

    # 获取退款和差评风险数据
    pool = state.get("db_pool")
    refund_risks = await _get_sku_refund_risk(pool)
    negative_signals = await _get_negative_review_signals(pool)

    risk_context = ""
    if refund_risks:
        risk_context += "\n高退款率SKU（选品应避免类似商品或标记风险）:\n" + json.dumps(
            refund_risks, ensure_ascii=False, default=str
        )
    if negative_signals:
        risk_context += "\n差评高频关键词（选品负面信号）:\n" + json.dumps(
            negative_signals, ensure_ascii=False, default=str
        )

    # 新增: 从 raw 表读取热销商品、消费排行、渠道分布
    hotsale_data = await fetch_latest_raw(pool, "qnh_products_raw")
    customer_rank_data = await fetch_latest_raw(pool, "qnh_customers_raw")
    channel_data = await fetch_latest_raw(pool, "qnh_traffic_channels_raw")

    hotsale_context = ""
    if hotsale_data:
        hotsale_context = (
            "\n热销商品排行（来自 qnh_products_raw，识别增长趋势商品）:\n"
            + json.dumps(
                hotsale_data if isinstance(hotsale_data, list) else [hotsale_data],
                ensure_ascii=False,
                default=str,
            )[:3000]
        )  # 截断防止 prompt 过长

    customer_context = ""
    if customer_rank_data:
        customer_context = (
            "\n消费排行（来自 qnh_customers_raw，高复购客户偏好）:\n"
            + json.dumps(
                customer_rank_data
                if isinstance(customer_rank_data, list)
                else [customer_rank_data],
                ensure_ascii=False,
                default=str,
            )[:3000]
        )

    channel_context = ""
    if channel_data:
        channel_context = (
            "\n渠道分布（来自 qnh_traffic_channels_raw，不同渠道热销品差异）:\n"
            + json.dumps(
                channel_data if isinstance(channel_data, list) else [channel_data],
                ensure_ascii=False,
                default=str,
            )[:2000]
        )

    return {
        "current_date": now.strftime("%Y-%m-%d"),
        "current_season": season,
        "refund_risk_data": risk_context,
        "hotsale_context": hotsale_context,
        "customer_rank_context": customer_context,
        "channel_context": channel_context,
        "errors": [],
    }


async def market_analysis_node(state: SelectionState) -> dict:
    """Market Sub-Agent: 市场热点分析"""
    try:
        # 融合热销排行和渠道数据到市场分析
        extra_market_data = (
            state.get("hotsale_context", "")
            + state.get("customer_rank_context", "")
            + state.get("channel_context", "")
        )
        prompt = market_analysis_prompt(
            keywords_data=state.get("raw_keywords_data", "暂无数据"),
            products_data=state.get("raw_products_data", "暂无数据") + extra_market_data,
            categories=", ".join(state.get("categories", ["医疗器械"])),
        )
        result = await call_tool(prompt, MARKET_ANALYSIS_TOOL, model=MODEL_PRO)
        return {"market_analysis": result}
    except Exception as e:
        logger.error(f"Market analysis failed: {e}")
        return {"errors": state.get("errors", []) + [f"market_analysis: {e}"]}


async def competitor_analysis_node(state: SelectionState) -> dict:
    """Competitor Sub-Agent: 竞品分析"""
    try:
        prompt = competitor_analysis_prompt(
            competitor_stores=state.get("raw_competitor_stores", "暂无数据"),
            competitor_products=state.get("raw_competitor_products", "暂无数据"),
            stockouts=state.get("raw_stockouts", "暂无数据"),
            our_products=state.get("raw_our_products", "暂无数据"),
        )
        result = await call_tool(prompt, COMPETITOR_ANALYSIS_TOOL, model=MODEL_PRO)
        return {"competitor_analysis": result}
    except Exception as e:
        logger.error(f"Competitor analysis failed: {e}")
        return {"errors": state.get("errors", []) + [f"competitor_analysis: {e}"]}


async def inventory_analysis_node(state: SelectionState) -> dict:
    """Inventory Sub-Agent: 库存分析（融合退款+差评风险信号）"""
    try:
        risk_data = state.get("refund_risk_data", "")
        prompt = inventory_analysis_prompt(
            products=state.get("raw_our_products", "暂无数据") + risk_data,
            sales_data=state.get("raw_sales_data", "暂无数据"),
        )
        result = await call_tool(prompt, INVENTORY_ANALYSIS_TOOL, model=MODEL_PRO)
        return {"inventory_analysis": result}
    except Exception as e:
        logger.error(f"Inventory analysis failed: {e}")
        return {"errors": state.get("errors", []) + [f"inventory_analysis: {e}"]}


async def seasonal_analysis_node(state: SelectionState) -> dict:
    """Seasonal Sub-Agent: 季节性因素分析"""
    try:
        prompt = seasonal_factors_prompt(
            current_date=state.get("current_date", datetime.now().strftime("%Y-%m-%d")),
            current_season=state.get("current_season", "未知"),
            upcoming_events=state.get("raw_upcoming_events", "暂无数据"),
            weather_forecast=state.get("raw_weather_forecast", "暂无数据"),
            trending_events=state.get("raw_trending_events", "无"),
        )
        result = await call_tool(prompt, SEASONAL_FACTORS_TOOL, model=MODEL_PRO)
        return {"seasonal_factors": result}
    except Exception as e:
        logger.error(f"Seasonal analysis failed: {e}")
        return {"errors": state.get("errors", []) + [f"seasonal_analysis: {e}"]}


# =============================================================================
# Phase 2: 缺品识别
# =============================================================================


async def gap_identification_node(state: SelectionState) -> dict:
    """Gap Identification: 缺品机会识别"""
    try:
        prompt = gap_identification_prompt(
            market_data=json.dumps(state.get("market_analysis", {}), ensure_ascii=False),
            competitor_data=json.dumps(state.get("competitor_analysis", {}), ensure_ascii=False),
            inventory_data=json.dumps(state.get("inventory_analysis", {}), ensure_ascii=False),
            seasonal_data=json.dumps(state.get("seasonal_factors", {}), ensure_ascii=False),
        )
        result = await call_tool(prompt, GAP_OPPORTUNITIES_TOOL, model=MODEL_PRO)
        return {"gap_opportunities": result}
    except Exception as e:
        logger.error(f"Gap identification failed: {e}")
        return {"errors": state.get("errors", []) + [f"gap_identification: {e}"]}


# =============================================================================
# Phase 3: 供应链评估
# =============================================================================


async def supplier_evaluation_node(state: SelectionState) -> dict:
    """Supplier Sub-Agent: 双渠道供应链评估（并发执行）"""
    import asyncio

    gap = state.get("gap_opportunities", {})
    opportunities = gap.get("opportunities", [])
    errors = list(state.get("errors", []))

    valid_opps = [opp for opp in opportunities if opp.get("keyword", "")]

    async def _eval_one(opp: dict) -> dict | Exception:
        keyword = opp.get("keyword", "")
        try:
            alibaba_data = state.get("raw_alibaba_results", {}).get(keyword, "暂无数据")
            pdd_data = state.get("raw_pdd_results", {}).get(keyword, "暂无数据")
            prompt = supplier_evaluation_prompt(
                keyword=keyword,
                market_price=opp.get("market_heat_score", 0) * 3,  # 估算
                monthly_demand=100,
                alibaba_results=alibaba_data,
                pdd_results=pdd_data,
            )
            return await call_tool(prompt, SUPPLIER_EVALUATION_TOOL, model=MODEL_PRO)
        except Exception as e:
            logger.error(f"Supplier eval failed for {keyword}: {e}")
            errors.append(f"supplier_{keyword}: {e}")
            return e

    tasks = [_eval_one(opp) for opp in valid_opps]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    evaluations = [r for r in results if not isinstance(r, Exception)]

    return {"supplier_evaluations": evaluations, "errors": errors}


# =============================================================================
# Phase 4: 综合评分 + Self-Reflection
# =============================================================================


async def scorer_node(state: SelectionState) -> dict:
    """Scorer Sub-Agent: 6维度评分 + 自我反思（使用 Opus）"""
    try:
        initial_prompt = scorer_prompt(
            gap_opportunities=json.dumps(state.get("gap_opportunities", {}), ensure_ascii=False),
            supplier_evaluations=json.dumps(
                state.get("supplier_evaluations", []), ensure_ascii=False
            ),
            seasonal_factors=json.dumps(state.get("seasonal_factors", {}), ensure_ascii=False),
            market_data=json.dumps(state.get("market_analysis", {}), ensure_ascii=False),
            competitor_data=json.dumps(state.get("competitor_analysis", {}), ensure_ascii=False),
            inventory_summary=json.dumps(
                state.get("inventory_analysis", {}).get("inventory_summary", {}),
                ensure_ascii=False,
            ),
        )

        result = await call_tool_with_reflection(
            initial_prompt=initial_prompt,
            reflection_prompt_fn=scorer_reflection_prompt,
            tool=RECOMMENDATIONS_TOOL,
            model=MODEL_OPUS,
        )
        return {"recommendations": result}
    except Exception as e:
        logger.error(f"Scorer failed: {e}")
        return {"errors": state.get("errors", []) + [f"scorer: {e}"]}
