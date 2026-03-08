"""Business Advisor Agent - transforms shop data into actionable business insights."""

import asyncio
import json
import logging
from typing import Any

from ..llm import MODEL_DEEPSEEK, call_tool_with_reflection

logger = logging.getLogger(__name__)

ANALYSIS_TOOL = {
    "name": "business_advice",
    "description": "提供业务建议",
    "input_schema": {
        "type": "object",
        "properties": {
            "analysis": {"type": "string", "maxLength": 300, "description": "数据分析要点"},
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
                "description": "具体可执行建议",
            },
            "priority_action": {
                "type": "string",
                "maxLength": 100,
                "description": "最重要的一个行动项",
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["analysis", "recommendations", "priority_action", "confidence"],
    },
}


async def _get_dashboard_data(pool) -> dict[str, Any]:
    """Get current dashboard metrics for business analysis."""
    try:
        from src.api.dashboard import _extract_metric, _get_latest_metrics

        total_products = await pool.fetchval("SELECT COUNT(*) FROM qnh_products") or 0
        today_orders = (
            await pool.fetchval("SELECT COUNT(*) FROM orders WHERE order_time::date = CURRENT_DATE")
            or 0
        )

        metrics = await _get_latest_metrics(pool)
        today_gmv = _extract_metric(metrics, "sale_amt_gmv") if metrics else 0
        avg_order_value = _extract_metric(metrics, "unit_price") if metrics else 0
        conversion_rate = 0.0

        if metrics:
            expose_cnt = _extract_metric(metrics, "expose_cnt")
            if expose_cnt > 0 and today_orders > 0:
                conversion_rate = today_orders / expose_cnt * 100

        return {
            "total_products": total_products,
            "today_orders": today_orders,
            "today_gmv": today_gmv,
            "avg_order_value": avg_order_value,
            "conversion_rate": conversion_rate,
            "raw_metrics": metrics or {},
        }
    except Exception as e:
        logger.error(f"Failed to get dashboard data: {e}")
        return {}


async def _get_sales_trend_data(pool) -> list[dict]:
    """Get sales trend data for analysis."""
    try:
        rows = await pool.fetch(
            """SELECT sale_date AS date, SUM(quantity)::int AS quantity, SUM(revenue) AS revenue
               FROM sales_history
               WHERE sale_date >= CURRENT_DATE - INTERVAL '7 days'
               GROUP BY sale_date ORDER BY sale_date"""
        )

        if not rows:
            raw_rows = await pool.fetch("""
                SELECT DISTINCT ON (created_at::date)
                       created_at::date AS date,
                       raw_data
                FROM qnh_store_metrics_raw
                WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
                ORDER BY created_at::date, created_at DESC
            """)

            from src.api.dashboard import _extract_metric

            rows = []
            for r in raw_rows:
                data = r["raw_data"]
                if isinstance(data, str):
                    data = json.loads(data)
                orders = int(_extract_metric(data, "eff_ord_cnt"))
                revenue = _extract_metric(data, "sale_amt_gmv")
                rows.append({"date": str(r["date"]), "quantity": orders, "revenue": revenue})

        return [
            {"date": str(r["date"]), "quantity": r["quantity"], "revenue": float(r["revenue"])}
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Failed to get sales trend data: {e}")
        return []


async def _get_competitor_overview(pool) -> list[dict]:
    try:
        rows = await pool.fetch(
            """
            SELECT name, price, source_shop, category, updated_at::text AS last_updated
            FROM competitor_products ORDER BY updated_at DESC LIMIT 20
            """
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


async def _get_recent_price_changes(pool) -> list[dict]:
    try:
        rows = await pool.fetch(
            """
            SELECT cp.product_name, cpc.old_price, cpc.new_price, cpc.change_pct, cpc.detected_at::text
            FROM competitor_price_changes cpc
            JOIN competitor_products cp ON cp.id = cpc.competitor_product_id
            WHERE cpc.detected_at >= NOW() - INTERVAL '7 days'
            ORDER BY ABS(cpc.change_pct) DESC LIMIT 10
            """
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


async def _get_inventory_alerts(pool) -> list[dict]:
    try:
        rows = await pool.fetch(
            """
            SELECT name, stock, cost_price, sale_price FROM qnh_products
            WHERE stock IS NOT NULL AND stock < 10 AND status = 1
            ORDER BY stock ASC LIMIT 15
            """
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


async def _get_category_performance(pool) -> list[dict]:
    try:
        rows = await pool.fetch(
            """
            SELECT cm.standard_category AS category, COUNT(DISTINCT p.id) AS product_count,
                   AVG(p.sale_price) AS avg_price
            FROM category_mapping cm
            JOIN qnh_products p ON p.name = cm.product_name
            GROUP BY cm.standard_category ORDER BY product_count DESC
            """
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


async def _get_seasonal_insights(pool) -> list[dict]:
    try:
        import datetime

        m = datetime.datetime.now().month
        rows = await pool.fetch(
            """
            SELECT product_name, peak_months, seasonal_tag, peak_ratio
            FROM product_seasonality WHERE $1 = ANY(peak_months)
            ORDER BY peak_ratio DESC NULLS LAST LIMIT 10
            """,
            m,
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


async def _get_penalty_summary(pool) -> list[dict]:
    try:
        rows = await pool.fetch(
            """
            SELECT penalty_type, severity, description, detected_at::text
            FROM platform_penalties WHERE detected_at >= NOW() - INTERVAL '30 days'
            ORDER BY detected_at DESC LIMIT 5
            """
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


async def _classify_intent(message: str) -> str:
    """Classify user intent to determine what data to fetch."""
    message_lower = message.lower()

    if any(word in message_lower for word in ["销售", "卖得", "营业额", "订单", "gmv"]):
        return "经营分析"
    if any(word in message_lower for word in ["竞品", "对手", "价格对比", "同行"]):
        return "竞品分析"
    if any(word in message_lower for word in ["定价", "价格", "多少钱", "调价"]):
        return "定价建议"
    if any(word in message_lower for word in ["库存", "缺货", "补货", "进货"]):
        return "库存管理"
    if any(word in message_lower for word in ["客单价", "提高", "增长", "优化"]):
        return "经营建议"
    return "综合咨询"


def _build_business_advisor_system_prompt() -> str:
    """Build system prompt for business advisor."""
    return """你是一位资深的电商店长助手，专门帮助店长分析经营数据、做出业务决策。

你的能力包括：
1. **经营分析**: 解读销售数据，识别趋势和问题
2. **竞品分析**: 对比竞争对手，找出定价和策略差异
3. **定价建议**: 基于市场和成本数据给出定价建议
4. **库存管理**: 分析库存状况，预警缺货风险
5. **经营建议**: 提供具体可执行的经营优化方案

回答要求：
- 数据驱动：基于真实数据分析，不猜测
- 可执行：给出具体行动建议，不只是分析
- 简洁明了：重点突出，避免长篇大论
- 商业视角：从盈利和增长角度思考问题

当前时间：2026年3月"""


def _reflect_business_advice(initial_result_str: str) -> str:
    return f"""请审查以下经营分析建议：
1. 数据引用是否准确
2. 建议是否有充分数据支撑
3. 优先级排序是否合理
4. 是否遗漏重要经营风险
5. 建议是否具体可执行

初始分析：{initial_result_str}

请给出修订版本。"""


async def analysis_node(message: str, pool=None, intent: str | None = None) -> dict[str, Any]:
    """核心分析节点：全景数据 + GraphRAG + Self-Reflection + 记忆。"""
    dashboard = await _get_dashboard_data(pool) if pool else {}
    sales_trend = await _get_sales_trend_data(pool) if pool else []
    competitor_overview = await _get_competitor_overview(pool) if pool else []
    price_changes = await _get_recent_price_changes(pool) if pool else []
    inventory_alerts = await _get_inventory_alerts(pool) if pool else []
    category_perf = await _get_category_performance(pool) if pool else []
    seasonal = await _get_seasonal_insights(pool) if pool else []
    penalties = await _get_penalty_summary(pool) if pool else []

    full_context = json.dumps(
        {
            "dashboard": dashboard,
            "sales_trend": sales_trend,
            "competitor": competitor_overview,
            "price_changes": price_changes,
            "inventory_alerts": inventory_alerts,
            "category_performance": category_perf,
            "seasonal_insights": seasonal,
            "penalties": penalties,
        },
        ensure_ascii=False,
        default=str,
    )

    graph_context = ""
    try:
        from src.skills.neo4j_skill import Neo4jSkill

        neo4j_skill = Neo4jSkill()
        graph_stats = await neo4j_skill.get_graph_stats()
        category_gaps = await neo4j_skill.find_category_gaps()
        if graph_stats:
            graph_context += f"\n知识图谱规模：{json.dumps(graph_stats, ensure_ascii=False)}"
        if category_gaps:
            graph_context += f"\n类目缺口分析：{json.dumps(category_gaps[:5], ensure_ascii=False)}"
    except Exception:
        pass

    prompt = f"""用户问题：{message}
咨询意图：{intent or '综合咨询'}

请基于以下全景业务数据给出经营分析和行动建议：
{full_context}
{graph_context}

输出要求：
1. 先给出核心经营结论（1段）
2. 给出3条最重要且可执行的建议
3. 明确1条最高优先级动作
4. 标注你对建议的置信度（0-1）"""

    memory_ctx = ""
    try:
        from src.agents.action_tracker import format_memory_context

        memory_ctx = await format_memory_context(
            pool=pool,
            agent_type="business_advisor",
            action_type="business_analysis",
        )
    except Exception:
        pass
    if memory_ctx:
        prompt = f"{prompt}\n{memory_ctx}"

    system_prompt = _build_business_advisor_system_prompt()
    result = await call_tool_with_reflection(
        initial_prompt=prompt,
        reflection_prompt_fn=_reflect_business_advice,
        tool=ANALYSIS_TOOL,
        model=MODEL_DEEPSEEK,
        system=system_prompt,
        trace_name="business_advisor_analysis",
    )

    async def _record(record_pool, record_result):
        try:
            from src.agents.action_tracker import record_action

            await record_action(
                pool=record_pool,
                agent_type="business_advisor",
                action_type="business_analysis",
                product_id=None,
                product_name=None,
                decision=record_result if isinstance(record_result, dict) else {"result": record_result},
                confidence=float(record_result.get("confidence", 0.8) or 0.8)
                if isinstance(record_result, dict)
                else 0.8,
                context_summary=json.dumps(record_result, ensure_ascii=False, default=str)[:500],
                baseline_metrics={},
            )
        except Exception:
            pass

    if pool:
        asyncio.create_task(_record(pool, result))

    return result if isinstance(result, dict) else {}


async def chat(
    session_id: str,
    message: str,
    pool=None,
    conversation_history: list[dict] | None = None,
    images: list[str] | None = None,
) -> dict:
    """Business advisor chat function."""

    try:
        intent = await _classify_intent(message)
        result = await analysis_node(message=message, pool=pool, intent=intent)

        analysis = result.get("analysis", "")
        recommendations = result.get("recommendations", [])
        priority_action = result.get("priority_action", "")
        confidence = result.get("confidence", 0.8)

        reply = f"{analysis}\n\n"
        if recommendations:
            reply += "🎯 **建议行动**:\n"
            for i, rec in enumerate(recommendations, 1):
                reply += f"{i}. {rec}\n"

        if priority_action:
            reply += f"\n⚡ **优先处理**: {priority_action}"

        return {
            "session_id": session_id,
            "reply": reply,
            "intent": intent,
            "sources": [],
            "needs_human": confidence < 0.7,
        }

    except Exception as e:
        logger.error(f"Business advisor chat failed: {e}")
        return {
            "session_id": session_id,
            "reply": "抱歉，数据分析暂时不可用，建议联系技术支持或稍后重试。",
            "intent": "error",
            "sources": [],
            "needs_human": True,
        }
