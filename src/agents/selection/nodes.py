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


async def _get_sales_history_monthly(pool) -> list[dict]:
    """获取按月聚合的商品销量趋势。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT DATE_TRUNC('month', date)::date AS month,
                   spu_id,
                   COALESCE(NULLIF(product_name, ''), spu_id) AS product_name,
                   SUM(COALESCE(quantity_sold, 0))::INT AS monthly_quantity,
                   SUM(COALESCE(revenue, 0))::NUMERIC(12, 2) AS monthly_revenue
            FROM qnh_sales_history
            WHERE date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '11 months'
            GROUP BY 1, 2, 3
            ORDER BY month DESC, monthly_quantity DESC
            LIMIT 1000
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to get sales history data: {e}")
        return []


async def _get_customer_ranking(pool) -> list[dict]:
    """获取消费排行（高价值客户）。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT customer_id,
                   nickname,
                   total_amount,
                   order_count,
                   avg_order_amount,
                   repurchase_rate,
                   last_order_time
            FROM qnh_customers
            ORDER BY total_amount DESC NULLS LAST
            LIMIT 50
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to get customer ranking data: {e}")
        return []


async def _get_competitor_products(pool) -> list[dict]:
    """获取竞品商品真实数据（价格/品类）。"""
    if not pool:
        return []

    queries = [
        """
        SELECT COALESCE(product_name, name) AS product_name,
               COALESCE(competitor_name, store_id, '未知竞品') AS competitor_name,
               price,
               category,
               COALESCE(monthly_sales, 0) AS monthly_sales
        FROM competitor_products
        WHERE COALESCE(price, 0) > 0
        ORDER BY COALESCE(monthly_sales, 0) DESC, price ASC
        LIMIT 200
        """,
        """
        SELECT name AS product_name,
               COALESCE(store_id, '未知竞品') AS competitor_name,
               price,
               category,
               COALESCE(monthly_sales, 0) AS monthly_sales
        FROM competitor_products
        WHERE COALESCE(price, 0) > 0
        ORDER BY COALESCE(monthly_sales, 0) DESC, price ASC
        LIMIT 200
        """,
        """
        SELECT product_name,
               competitor_name,
               price,
               category,
               0 AS monthly_sales
        FROM competitor_products
        WHERE COALESCE(price, 0) > 0
        ORDER BY price ASC
        LIMIT 200
        """,
    ]

    for query in queries:
        try:
            rows = await pool.fetch(query)
            if rows:
                return [dict(r) for r in rows]
        except Exception:
            continue
    return []


async def _get_product_seasonality(pool) -> list[dict]:
    """获取季节性标签数据。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT product_name,
                   seasonal_tag,
                   peak_months,
                   avg_monthly_sales,
                   peak_ratio,
                   updated_at
            FROM product_seasonality
            ORDER BY peak_ratio DESC NULLS LAST, avg_monthly_sales DESC NULLS LAST
            LIMIT 120
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to get product seasonality data: {e}")
        return []


async def _get_qnh_products(pool) -> list[dict]:
    """获取自家商品完整信息（含 cost_price）。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT to_jsonb(p) AS product
            FROM qnh_products p
            ORDER BY synced_at DESC
            LIMIT 500
            """
        )
        return [dict(r["product"]) for r in rows if r.get("product")]
    except Exception as e:
        logger.warning(f"Failed to get qnh_products data: {e}")
        return []


def _build_sales_history_context(sales_history_data: list[dict]) -> str:
    """将月销量记录压缩为可供 LLM 理解的趋势摘要。"""
    if not sales_history_data:
        return ""

    by_product: dict[str, list[dict[str, Any]]] = {}
    for row in sales_history_data:
        product_key = str(row.get("spu_id") or row.get("product_name") or "unknown")
        by_product.setdefault(product_key, []).append(
            {
                "month": str(row.get("month")),
                "quantity": int(row.get("monthly_quantity") or 0),
                "revenue": float(row.get("monthly_revenue") or 0),
                "product_name": row.get("product_name") or product_key,
            }
        )

    trend_items: list[dict[str, Any]] = []
    for product_rows in by_product.values():
        ordered = sorted(product_rows, key=lambda x: x["month"])
        total_qty = sum(item["quantity"] for item in ordered)
        if total_qty <= 0:
            continue
        first_qty = ordered[0]["quantity"]
        last_qty = ordered[-1]["quantity"]
        direction = "stable"
        if last_qty > first_qty:
            direction = "rising"
        elif last_qty < first_qty:
            direction = "declining"

        trend_items.append(
            {
                "spu_or_product": product_rows[0]["product_name"],
                "total_quantity_12m": total_qty,
                "trend_direction": direction,
                "monthly_series": ordered[-6:],
            }
        )

    trend_items.sort(key=lambda x: x["total_quantity_12m"], reverse=True)
    return "\n月销量趋势（来自 qnh_sales_history 聚合）:\n" + json.dumps(
        trend_items[:40], ensure_ascii=False, default=str
    )[:4000]


def _build_margin_context(products_full_data: list[dict]) -> str:
    """根据 qnh_products 计算毛利率画像。"""
    if not products_full_data:
        return ""

    margins: list[dict[str, Any]] = []
    for product in products_full_data:
        retail = float(product.get("retail_price") or 0)
        cost = float(product.get("cost_price") or 0)
        if retail <= 0:
            continue
        margin = (retail - cost) / retail
        margins.append(
            {
                "spu_id": product.get("spu_id"),
                "name": product.get("name"),
                "retail_price": retail,
                "cost_price": cost,
                "margin_rate": round(margin, 4),
            }
        )

    if not margins:
        return ""

    margins.sort(key=lambda x: x["margin_rate"])
    avg_margin = sum(item["margin_rate"] for item in margins) / len(margins)
    low_margin = [m for m in margins if m["margin_rate"] < 0.25]
    high_margin = sorted(margins, key=lambda x: x["margin_rate"], reverse=True)[:20]
    return "\n毛利率画像（来自 qnh_products，毛利率=(retail-cost)/retail）:\n" + json.dumps(
        {
            "product_count_with_margin": len(margins),
            "avg_margin_rate": round(avg_margin, 4),
            "low_margin_count_lt_25pct": len(low_margin),
            "lowest_margin_products": margins[:20],
            "highest_margin_products": high_margin,
        },
        ensure_ascii=False,
        default=str,
    )[:4000]


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

    # 新增: 结构化业务数据（全部真实表）
    sales_history_data = await _get_sales_history_monthly(pool)
    customer_ranking_data = await _get_customer_ranking(pool)
    competitor_products_data = await _get_competitor_products(pool)
    seasonality_data = await _get_product_seasonality(pool)
    products_full_data = await _get_qnh_products(pool)
    sales_history_context = _build_sales_history_context(sales_history_data)
    margin_context = _build_margin_context(products_full_data)

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
    elif customer_ranking_data:
        customer_context = (
            "\n消费排行（来自 qnh_customers 真实排行）:\n"
            + json.dumps(customer_ranking_data, ensure_ascii=False, default=str)[:3000]
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
        "sales_history_context": sales_history_context,
        "customer_rank_context": customer_context,
        "channel_context": channel_context,
        "sales_history_data": sales_history_data,
        "customer_ranking_data": customer_ranking_data,
        "competitor_products_data": competitor_products_data,
        "seasonality_data": seasonality_data,
        "products_full_data": products_full_data,
        "margin_context": margin_context,
        "errors": [],
    }


async def market_analysis_node(state: SelectionState) -> dict:
    """Market Sub-Agent: 市场热点分析"""
    try:
        # 融合热销排行和渠道数据到市场分析
        extra_market_data = (
            state.get("hotsale_context", "")
            + state.get("sales_history_context", "")
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
        real_competitor_products = state.get("competitor_products_data", [])
        competitor_products_input = state.get("raw_competitor_products", "暂无数据")
        if real_competitor_products:
            competitor_products_input = "真实竞品数据（来自 competitor_products）:\n" + json.dumps(
                real_competitor_products, ensure_ascii=False, default=str
            )[:4000]

        prompt = competitor_analysis_prompt(
            competitor_stores=state.get("raw_competitor_stores", "暂无数据"),
            competitor_products=competitor_products_input,
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
        seasonality_data = state.get("seasonality_data", [])
        seasonality_context = ""
        if seasonality_data:
            seasonality_context = "\n商品季节性标签（来自 product_seasonality）:\n" + json.dumps(
                seasonality_data, ensure_ascii=False, default=str
            )[:4000]

        prompt = seasonal_factors_prompt(
            current_date=state.get("current_date", datetime.now().strftime("%Y-%m-%d")),
            current_season=state.get("current_season", "未知"),
            upcoming_events=state.get("raw_upcoming_events", "暂无数据"),
            weather_forecast=state.get("raw_weather_forecast", "暂无数据"),
            trending_events=(state.get("raw_trending_events", "无") or "无") + seasonality_context,
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
        # === GraphRAG 增强 ===
        graph_context = ""
        try:
            from src.db import neo4j as neo4j_db
            from src.skills.neo4j_skill import Neo4jSkill

            driver = neo4j_db.get_driver()
            skill = Neo4jSkill(driver=driver)
            category_gaps = await skill.find_category_gaps()
            scenario_gaps = await skill.find_scenario_gaps()
            if category_gaps or scenario_gaps:
                graph_context = (
                    "\n\n# 图谱缺口发现\n"
                    f"竞品品类缺口：{json.dumps(category_gaps[:20], ensure_ascii=False)}\n"
                    f"场景缺口：{json.dumps(scenario_gaps[:20], ensure_ascii=False)}"
                )
        except Exception:
            graph_context = ""

        competitor_data = json.dumps(state.get("competitor_analysis", {}), ensure_ascii=False)
        if graph_context:
            competitor_data = f"{competitor_data}{graph_context}"

        prompt = gap_identification_prompt(
            market_data=json.dumps(state.get("market_analysis", {}), ensure_ascii=False),
            competitor_data=competitor_data,
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
        inventory_summary = json.dumps(
            state.get("inventory_analysis", {}).get("inventory_summary", {}),
            ensure_ascii=False,
        ) + state.get("margin_context", "")

        initial_prompt = scorer_prompt(
            gap_opportunities=json.dumps(state.get("gap_opportunities", {}), ensure_ascii=False),
            supplier_evaluations=json.dumps(
                state.get("supplier_evaluations", []), ensure_ascii=False
            ),
            seasonal_factors=json.dumps(state.get("seasonal_factors", {}), ensure_ascii=False),
            market_data=json.dumps(state.get("market_analysis", {}), ensure_ascii=False),
            competitor_data=json.dumps(state.get("competitor_analysis", {}), ensure_ascii=False),
            inventory_summary=inventory_summary,
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
