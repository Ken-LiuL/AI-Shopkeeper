"""Boss Assistant — 店主经营顾问核心逻辑。"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


async def _get_business_context(pool) -> dict[str, Any]:
    """从数据库获取店铺经营数据。"""
    ctx: dict[str, Any] = {}
    if pool is None:
        return ctx

    try:
        today_orders = await pool.fetchval(
            "SELECT COUNT(*) FROM orders WHERE order_time::date = CURRENT_DATE"
        ) or 0
        ctx["today_orders"] = today_orders
    except Exception as e:
        logger.debug("Failed to fetch orders: %s", e)

    try:
        total_products = await pool.fetchval("SELECT COUNT(*) FROM qnh_products") or 0
        ctx["total_products"] = total_products
    except Exception as e:
        logger.debug("Failed to fetch products: %s", e)

    try:
        low_stock = await pool.fetchval(
            "SELECT COUNT(*) FROM qnh_products WHERE stock IS NOT NULL AND stock > 0 AND stock <= 10"
        ) or 0
        out_of_stock = await pool.fetchval(
            "SELECT COUNT(*) FROM qnh_products WHERE stock IS NOT NULL AND stock = 0"
        ) or 0
        ctx["low_stock"] = low_stock
        ctx["out_of_stock"] = out_of_stock
    except Exception as e:
        logger.debug("Failed to fetch inventory: %s", e)

    try:
        pending_alerts = await pool.fetchval(
            "SELECT COUNT(*) FROM alerts WHERE status = 'pending'"
        ) or 0
        ctx["pending_alerts"] = pending_alerts
    except Exception as e:
        logger.debug("Failed to fetch alerts: %s", e)

    try:
        cs_sessions_today = await pool.fetchval(
            "SELECT COUNT(*) FROM cs_sessions WHERE created_at::date = CURRENT_DATE"
        ) or 0
        ctx["cs_sessions_today"] = cs_sessions_today
    except Exception as e:
        logger.debug("Failed to fetch cs_sessions: %s", e)

    try:
        top_rows = await pool.fetch(
            """
            SELECT p.name, SUM(oi.quantity) AS sales
            FROM order_items oi
            JOIN qnh_products p ON p.product_id = oi.product_id
            WHERE oi.created_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY p.name
            ORDER BY sales DESC
            LIMIT 5
            """
        )
        ctx["top_products"] = [{"name": r["name"], "sales": r["sales"]} for r in top_rows]
    except Exception as e:
        logger.debug("Failed to fetch top products: %s", e)

    return ctx


def _format_context_for_llm(ctx: dict[str, Any]) -> str:
    """把经营上下文格式化成 prompt 可用的文字。"""
    if not ctx:
        return "（暂无实时经营数据）"

    lines = []
    if "today_orders" in ctx:
        lines.append(f"- 今日订单数：{ctx['today_orders']} 单")
    if "total_products" in ctx:
        lines.append(f"- 在售商品数：{ctx['total_products']} 款")
    if "low_stock" in ctx:
        lines.append(f"- 低库存商品：{ctx['low_stock']} 款（库存 ≤10）")
    if "out_of_stock" in ctx:
        lines.append(f"- 缺货商品：{ctx['out_of_stock']} 款")
    if "pending_alerts" in ctx:
        lines.append(f"- 待处理预警：{ctx['pending_alerts']} 条")
    if "cs_sessions_today" in ctx:
        lines.append(f"- 今日客服对话：{ctx['cs_sessions_today']} 次")
    if ctx.get("top_products"):
        top_str = "、".join(f"{p['name']}({p['sales']}件)" for p in ctx["top_products"])
        lines.append(f"- 近30天热销TOP5：{top_str}")
    return "\n".join(lines) if lines else "（暂无实时经营数据）"


async def _call_llm_chat(
    system: str,
    messages: list[dict],
    model: str,
    max_tokens: int = 600,
) -> str:
    """通过 OpenRouter (OpenAI SDK) 做简单对话补全，不使用 tool calling。"""
    from openai import AsyncOpenAI

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )

    full_messages = [{"role": "system", "content": system}] + messages

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=full_messages,
            ),
            timeout=30.0,
        )
        return response.choices[0].message.content or ""
    except TimeoutError:
        raise ValueError("Boss assistant LLM timeout after 30s") from None


async def boss_chat(
    session_id: str,
    message: str,
    pool=None,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    店主助手对话入口。

    1. 意图识别（经营分析/库存/竞品/定价/选品/告警/客服/通用）
    2. 拉取对应数据
    3. 用 DeepSeek LLM 生成专业经营建议
    4. 返回结构化结果
    """
    from src.agents.llm import MODEL_DEEPSEEK
    from src.agents.prompts.boss_assistant import BOSS_SYSTEM_PROMPT, classify_intent

    intent = classify_intent(message)
    logger.info("[BossAssistant] session=%s intent=%s msg=%s", session_id, intent, message[:60])

    # 拉取经营上下文
    ctx = await _get_business_context(pool)
    ctx_text = _format_context_for_llm(ctx)

    # 构建对话历史
    llm_messages: list[dict] = []
    if conversation_history:
        for h in conversation_history[-10:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                llm_messages.append({"role": role, "content": content})

    # 注入当前经营数据到用户消息
    user_content = f"""## 店铺当前经营快照
{ctx_text}

## 老板提问
{message}"""

    llm_messages.append({"role": "user", "content": user_content})

    # 调用 LLM
    try:
        reply = await _call_llm_chat(
            system=BOSS_SYSTEM_PROMPT,
            messages=llm_messages,
            model=MODEL_DEEPSEEK,
            max_tokens=600,
        )
    except Exception as e:
        logger.error("[BossAssistant] LLM call failed: %s", e)
        reply = "抱歉，经营分析系统暂时不可用，请稍后重试。"

    return {
        "reply": reply,
        "intent": intent,
        "sources": [],
        "needs_human": False,
        "context": ctx,
    }
