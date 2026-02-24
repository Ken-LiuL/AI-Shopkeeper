"""Selection Agent 各节点实现"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from ..llm import MODEL_PRO, MODEL_SONNET, call_tool, call_tool_with_reflection
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


# =============================================================================
# Phase 1: 数据采集（并行）
# =============================================================================


async def fetch_data(state: SelectionState) -> dict:
    """采集所有原始数据（通过 Skills 层）"""
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

    return {
        "current_date": now.strftime("%Y-%m-%d"),
        "current_season": season,
        "errors": [],
    }


async def market_analysis_node(state: SelectionState) -> dict:
    """Market Sub-Agent: 市场热点分析"""
    try:
        prompt = market_analysis_prompt(
            keywords_data=state.get("raw_keywords_data", "暂无数据"),
            products_data=state.get("raw_products_data", "暂无数据"),
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
    """Inventory Sub-Agent: 库存分析"""
    try:
        prompt = inventory_analysis_prompt(
            products=state.get("raw_our_products", "暂无数据"),
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
    """Supplier Sub-Agent: 双渠道供应链评估（逐个关键词）"""
    gap = state.get("gap_opportunities", {})
    opportunities = gap.get("opportunities", [])

    evaluations: list[dict[str, Any]] = []
    errors = list(state.get("errors", []))

    for opp in opportunities:
        keyword = opp.get("keyword", "")
        if not keyword:
            continue

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
            result = await call_tool(prompt, SUPPLIER_EVALUATION_TOOL, model=MODEL_PRO)
            evaluations.append(result)
        except Exception as e:
            logger.error(f"Supplier eval failed for {keyword}: {e}")
            errors.append(f"supplier_{keyword}: {e}")

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
            model=MODEL_SONNET,
        )
        return {"recommendations": result}
    except Exception as e:
        logger.error(f"Scorer failed: {e}")
        return {"errors": state.get("errors", []) + [f"scorer: {e}"]}
