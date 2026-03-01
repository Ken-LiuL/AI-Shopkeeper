"""Business Advisor Agent - transforms shop data into actionable business insights."""

import contextlib
import json
import logging
from typing import Any

from ..llm import MODEL_DEEPSEEK, call_tool

logger = logging.getLogger(__name__)


async def _get_dashboard_data(pool) -> dict[str, Any]:
    """Get current dashboard metrics for business analysis."""
    try:
        from src.api.dashboard import _extract_metric, _get_latest_metrics

        # Get basic stats
        total_products = await pool.fetchval("SELECT COUNT(*) FROM qnh_products") or 0
        today_orders = (
            await pool.fetchval("SELECT COUNT(*) FROM orders WHERE order_time::date = CURRENT_DATE")
            or 0
        )

        # Get raw metrics
        metrics = await _get_latest_metrics(pool)
        today_gmv = _extract_metric(metrics, "sale_amt_gmv") if metrics else 0
        avg_order_value = _extract_metric(metrics, "unit_price") if metrics else 0
        conversion_rate = 0.0

        # Calculate conversion rate
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
        # Try structured sales_history first
        rows = await pool.fetch(
            """SELECT sale_date AS date, SUM(quantity)::int AS quantity, SUM(revenue) AS revenue
               FROM sales_history
               WHERE sale_date >= CURRENT_DATE - INTERVAL '7 days'
               GROUP BY sale_date ORDER BY sale_date"""
        )

        if not rows:
            # Fallback to raw metrics
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


async def _get_inventory_data(pool) -> list[dict]:
    """Get inventory data for stock analysis."""
    try:
        rows = await pool.fetch("""
            SELECT spu_id, name, stock_num, retail_price, status
            FROM qnh_products
            WHERE status = '在售' AND stock_num IS NOT NULL
            ORDER BY stock_num ASC
            LIMIT 10
        """)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get inventory data: {e}")
        return []


async def _get_competitors_data(pool) -> list[dict]:
    """Get competitor analysis data."""
    try:
        # Get competitor pricing data if available
        rows = await pool.fetch("""
            SELECT product_name, our_price, competitor_avg_price, price_difference
            FROM competitor_analysis
            ORDER BY ABS(price_difference) DESC
            LIMIT 5
        """)
        return [dict(r) for r in rows]
    except Exception:
        # If no competitor table, return sample structure
        logger.info("No competitor data available")
        return []


async def _classify_intent(message: str) -> str:
    """Classify user intent to determine what data to fetch."""
    message_lower = message.lower()

    if any(word in message_lower for word in ["销售", "卖得", "营业额", "订单", "gmv"]):
        return "经营分析"
    elif any(word in message_lower for word in ["竞品", "对手", "价格对比", "同行"]):
        return "竞品分析"
    elif any(word in message_lower for word in ["定价", "价格", "多少钱", "调价"]):
        return "定价建议"
    elif any(word in message_lower for word in ["库存", "缺货", "补货", "进货"]):
        return "库存管理"
    elif any(word in message_lower for word in ["客单价", "提高", "增长", "优化"]):
        return "经营建议"
    else:
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


async def chat(
    session_id: str,
    message: str,
    pool=None,
    conversation_history: list[dict] | None = None,
    images: list[str] | None = None,
) -> dict:
    """Business advisor chat function."""

    try:
        # 1. Classify intent to determine data needs
        intent = await _classify_intent(message)

        # 2. Gather relevant data based on intent
        context_data = {}

        if intent in ["经营分析", "经营建议", "综合咨询"]:
            context_data["dashboard"] = await _get_dashboard_data(pool)
            context_data["sales_trend"] = await _get_sales_trend_data(pool)

        if intent in ["库存管理", "综合咨询"]:
            context_data["inventory"] = await _get_inventory_data(pool)

        if intent in ["竞品分析", "定价建议"]:
            context_data["competitors"] = await _get_competitors_data(pool)

        if intent in ["定价建议"]:
            # Get product pricing data
            with contextlib.suppress(Exception):
                pricing_data = await pool.fetch("""
                    SELECT spu_id, name, cost_price, retail_price,
                           CASE WHEN cost_price > 0 THEN (retail_price - cost_price) / cost_price * 100 ELSE 0 END as margin
                    FROM qnh_products
                    WHERE status = '在售' AND retail_price > 0
                    ORDER BY margin DESC LIMIT 10
                """)
                context_data["pricing"] = [dict(r) for r in pricing_data]

        # 3. Build context-aware user message
        user_message_with_context = f"""用户问题：{message}

当前业务数据：
"""

        if "dashboard" in context_data and context_data["dashboard"]:
            dash = context_data["dashboard"]
            user_message_with_context += f"""
【经营概况】
- 商品总数：{dash.get("total_products", 0)} 个
- 今日订单：{dash.get("today_orders", 0)} 单
- 今日GMV：¥{dash.get("today_gmv", 0):.2f}
- 客单价：¥{dash.get("avg_order_value", 0):.2f}
- 转化率：{dash.get("conversion_rate", 0):.2f}%
"""

        if "sales_trend" in context_data and context_data["sales_trend"]:
            trend_data = context_data["sales_trend"][-7:]  # Last 7 days
            user_message_with_context += """
【近7日销售趋势】
"""
            for day in trend_data:
                user_message_with_context += (
                    f"- {day['date']}: {day['quantity']}单, ¥{day['revenue']:.2f}\n"
                )

        if "inventory" in context_data and context_data["inventory"]:
            low_stock = [
                item for item in context_data["inventory"] if item.get("stock_num", 0) < 10
            ]
            if low_stock:
                user_message_with_context += """
【库存预警】(库存<10)
"""
                for item in low_stock[:5]:
                    user_message_with_context += f"- {item['name']}: {item.get('stock_num', 0)}件\n"

        if "pricing" in context_data and context_data["pricing"]:
            user_message_with_context += """
【定价分析】(毛利率前5)
"""
            for item in context_data["pricing"][:5]:
                user_message_with_context += f"- {item['name']}: 成本¥{item.get('cost_price', 0):.2f} 售价¥{item.get('retail_price', 0):.2f} 毛利{item.get('margin', 0):.1f}%\n"

        if "competitors" in context_data and context_data["competitors"]:
            user_message_with_context += """
【竞品对比】
"""
            for comp in context_data["competitors"]:
                user_message_with_context += f"- {comp['product_name']}: 我方¥{comp['our_price']} vs 竞品均价¥{comp['competitor_avg_price']}\n"

        # 4. Call LLM for business advice
        tool_schema = {
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

        system_prompt = _build_business_advisor_system_prompt()

        result = await call_tool(
            prompt=user_message_with_context,
            tool=tool_schema,
            model=MODEL_DEEPSEEK,
            system=system_prompt,
            trace_name="business_advisor_chat",
        )

        # 5. Format response
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
