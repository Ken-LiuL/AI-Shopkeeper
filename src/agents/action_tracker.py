"""
决策追踪器 - 记录 Agent 决策，定时评估效果。
实现 Agent 的学习闭环。
"""

from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger(__name__)


async def record_action(
    pool,
    agent_type: str,
    action_type: str,
    product_id: str | None,
    product_name: str | None,
    decision: dict,
    confidence: float | None = None,
    context_summary: str | None = None,
    baseline_metrics: dict | None = None,
) -> str:
    """记录一个 Agent 决策。返回 action_id。"""
    action_id = f"{agent_type}_{uuid.uuid4().hex[:8]}"
    if not pool:
        return action_id
    try:
        await pool.execute(
            """
            INSERT INTO action_tracking
            (action_id, agent_type, action_type, product_id, product_name,
             decision_json, confidence, context_summary, baseline_metrics)
            VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9::jsonb)
            ON CONFLICT (action_id) DO NOTHING
            """,
            action_id,
            agent_type,
            action_type,
            product_id,
            product_name,
            json.dumps(decision, ensure_ascii=False, default=str),
            confidence,
            context_summary,
            json.dumps(baseline_metrics, ensure_ascii=False, default=str)
            if baseline_metrics
            else None,
        )
    except Exception as e:
        logger.warning("Failed to record action %s: %s", action_id, e)
    return action_id


async def get_similar_decisions(
    pool,
    agent_type: str,
    action_type: str,
    product_name: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """检索历史类似决策及其效果（记忆检索）。"""
    if not pool:
        return []
    try:
        if product_name:
            rows = await pool.fetch(
                """
                SELECT action_id, product_name, decision_json,
                       effect_score, effect_metrics, confidence,
                       context_summary, created_at
                FROM action_tracking
                WHERE agent_type = $1 AND action_type = $2
                  AND effect_score IS NOT NULL
                  AND product_name ILIKE '%' || $3 || '%'
                ORDER BY effect_score DESC, created_at DESC
                LIMIT $4
                """,
                agent_type,
                action_type,
                product_name,
                limit,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT action_id, product_name, decision_json,
                       effect_score, effect_metrics, confidence,
                       context_summary, created_at
                FROM action_tracking
                WHERE agent_type = $1 AND action_type = $2
                  AND effect_score IS NOT NULL
                ORDER BY effect_score DESC, created_at DESC
                LIMIT $3
                """,
                agent_type,
                action_type,
                limit,
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(
            "Failed to get similar decisions for %s/%s: %s",
            agent_type,
            action_type,
            e,
        )
        return []


async def format_memory_context(
    pool,
    agent_type: str,
    action_type: str,
    product_name: str | None = None,
) -> str:
    """格式化历史决策为 LLM context。"""
    decisions = await get_similar_decisions(pool, agent_type, action_type, product_name)
    if not decisions:
        return ""

    context = "\n\n# 历史决策参考（基于实际效果排序）\n"
    for d in decisions:
        score = d.get("effect_score")
        score_label = (
            f"效果{'优秀' if score > 0.7 else '一般' if score > 0.4 else '差'}({score:.1f})"
            if score is not None
            else "未评估"
        )
        context += f"- [{d.get('product_name') or '未知商品'}] {d.get('context_summary', '')} -> {score_label}\n"
        try:
            decision_value = d.get("decision_json")
            decision = (
                json.loads(decision_value)
                if isinstance(decision_value, str)
                else decision_value
            )
            context += f"  决策: {json.dumps(decision, ensure_ascii=False)[:200]}\n"
        except Exception:
            continue
    return context
