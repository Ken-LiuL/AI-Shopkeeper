"""
Customer Service Learning System
自动从对话日志和反馈中学习，优化客服回复质量
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def extract_learning_insights(pool) -> dict:
    """从对话日志中提取学习洞察"""
    try:
        # 1. 统计高频问题（按 intent 分组）
        high_freq_intents = await pool.fetch(
            """
            SELECT intent, COUNT(*) as count, AVG(confidence) as avg_confidence
            FROM cs_conversation_log
            WHERE created_at >= NOW() - INTERVAL '30 days'
            AND intent IS NOT NULL
            GROUP BY intent
            ORDER BY count DESC
            LIMIT 10
            """
        )

        # 2. 找出差评回复（rating='bad'）
        bad_feedback = await pool.fetch(
            """
            SELECT f.session_id, f.comment, l.intent, l.user_message, l.ai_response, l.confidence
            FROM cs_feedback f
            JOIN cs_conversation_log l ON f.session_id = l.session_id
            WHERE f.rating = 'bad'
            AND f.created_at >= NOW() - INTERVAL '7 days'
            ORDER BY f.created_at DESC
            LIMIT 20
            """
        )

        # 3. 找出低置信度问题（confidence < 0.5）
        low_confidence = await pool.fetch(
            """
            SELECT session_id, intent, user_message, ai_response, confidence
            FROM cs_conversation_log
            WHERE confidence < 0.5
            AND created_at >= NOW() - INTERVAL '7 days'
            ORDER BY confidence ASC
            LIMIT 20
            """
        )

        # 4. 计算总体统计
        stats = await pool.fetchrow(
            """
            SELECT
                COUNT(DISTINCT session_id) as total_sessions,
                COUNT(*) as total_messages,
                AVG(confidence) as avg_confidence,
                COUNT(CASE WHEN confidence < 0.5 THEN 1 END) as low_confidence_count
            FROM cs_conversation_log
            WHERE created_at >= NOW() - INTERVAL '7 days'
            """
        )

        return {
            "high_frequency_intents": [dict(row) for row in high_freq_intents],
            "bad_feedback_cases": [dict(row) for row in bad_feedback],
            "low_confidence_cases": [dict(row) for row in low_confidence],
            "overall_stats": dict(stats) if stats else {},
            "generated_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to extract learning insights: {e}")
        return {}


async def update_few_shot_examples(pool) -> None:
    """根据好评回复和高评分回复更新 few-shot 示例"""
    try:
        # 1. 查询 rating='good' 的对话，按 intent 分组
        good_examples = await pool.fetch(
            """
            SELECT l.intent, l.user_message, l.ai_response, l.confidence, f.created_at,
                   'feedback' as source, NULL as overall_score
            FROM cs_feedback f
            JOIN cs_conversation_log l ON f.session_id = l.session_id
            WHERE f.rating = 'good'
            AND l.intent IS NOT NULL
            AND f.created_at >= NOW() - INTERVAL '30 days'
            """
        )

        # 2. 查询高评分回复（overall >= 0.85）从 cs_reply_scores 表
        high_score_examples = []
        try:
            high_score_examples = await pool.fetch(
                """
                SELECT s.session_id, l.intent, s.user_message, s.ai_reply as ai_response,
                       l.confidence, s.created_at, 'scoring' as source, s.overall as overall_score
                FROM cs_reply_scores s
                LEFT JOIN cs_conversation_log l ON s.session_id = l.session_id
                WHERE s.overall >= 0.85
                AND s.created_at >= NOW() - INTERVAL '30 days'
                AND l.intent IS NOT NULL
                ORDER BY s.overall DESC, s.created_at DESC
                """
            )
            logger.info(f"Found {len(high_score_examples)} high-scoring examples")
        except Exception as e:
            logger.warning(f"Could not query cs_reply_scores table: {e}")
            high_score_examples = []

        # 3. 合并两个数据源
        all_examples = list(good_examples) + list(high_score_examples)

        # 4. 按 intent 分组，选出最佳回复
        intent_examples = {}
        for row in all_examples:
            intent = row.get("intent")
            if not intent:
                continue

            if intent not in intent_examples:
                intent_examples[intent] = []

            if len(intent_examples[intent]) < 3:  # 每个意图最多保留3个例子
                example = {
                    "user_message": row.get("user_message", ""),
                    "ai_response": row.get("ai_response", ""),
                    "confidence": float(row.get("confidence") or 0),
                    "timestamp": row["created_at"].isoformat() if row.get("created_at") else "",
                    "source": row.get("source", "unknown"),
                    "overall_score": float(row.get("overall_score") or 0)
                    if row.get("overall_score")
                    else None,
                }
                intent_examples[intent].append(example)

        # 5. 按分数排序，优先选择高分示例
        for intent in intent_examples:
            intent_examples[intent].sort(
                key=lambda x: (x.get("overall_score") or x.get("confidence", 0)), reverse=True
            )
            # 只保留前3个最佳示例
            intent_examples[intent] = intent_examples[intent][:3]

        # 6. 更新配置文件或数据库
        try:
            # 创建系统配置表（如果不存在）
            await pool.execute(
                """
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )

            await pool.execute(
                """
                INSERT INTO system_config (key, value, updated_at)
                VALUES ('cs_few_shot_examples', $1, NOW())
                ON CONFLICT (key)
                DO UPDATE SET value = $1, updated_at = NOW()
                """,
                json.dumps(intent_examples, ensure_ascii=False),
            )
            logger.info(f"Updated few-shot examples for {len(intent_examples)} intents")

            # 记录更新统计
            total_examples = sum(len(examples) for examples in intent_examples.values())
            logger.info(f"Total {total_examples} few-shot examples updated")

        except Exception as e:
            # 如果数据库操作失败，尝试写入文件
            logger.warning(f"Could not update few-shot examples in database: {e}")
            try:
                import os

                config_path = os.path.join(os.getcwd(), "data", "cs_knowledge_structured.json")

                # 读取现有配置
                existing_config = {}
                if os.path.exists(config_path):
                    with open(config_path, encoding="utf-8") as f:
                        existing_config = json.load(f)

                # 更新 dynamic_few_shot 字段
                existing_config["dynamic_few_shot"] = intent_examples

                # 写回文件
                os.makedirs(os.path.dirname(config_path), exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(existing_config, f, ensure_ascii=False, indent=2)

                logger.info(f"Updated few-shot examples to file: {config_path}")

            except Exception as file_error:
                logger.error(f"Failed to update few-shot examples to file: {file_error}")

    except Exception as e:
        logger.error(f"Failed to update few-shot examples: {e}")


async def generate_learning_report(pool) -> str:
    """生成学习报告（给店长看）"""
    try:
        insights = await extract_learning_insights(pool)

        if not insights:
            return "暂无学习数据"

        stats = insights.get("overall_stats", {})
        high_freq = insights.get("high_frequency_intents", [])
        bad_cases = insights.get("bad_feedback_cases", [])
        low_conf_cases = insights.get("low_confidence_cases", [])

        report = f"""# 客服学习报告

## 📊 总体统计 (最近7天)
- 总对话会话: {stats.get("total_sessions", 0)}
- 总消息数: {stats.get("total_messages", 0)}
- 平均置信度: {stats.get("avg_confidence", 0):.2f}
- 低置信度消息: {stats.get("low_confidence_count", 0)}

## 🔥 高频问题类型
"""

        for intent_data in high_freq[:5]:
            report += f"- **{intent_data['intent']}**: {intent_data['count']}次 (平均置信度: {intent_data['avg_confidence']:.2f})\n"

        if bad_cases:
            report += f"\n## 👎 需要改进的回复 ({len(bad_cases)}个)\n"
            for case in bad_cases[:3]:
                report += f"""
**用户问题**: {case["user_message"][:50]}...
**AI回复**: {case["ai_response"][:50]}...
**用户反馈**: {case["comment"] or "无具体意见"}
**置信度**: {case["confidence"]:.2f}
---
"""

        if low_conf_cases:
            report += f"\n## ⚠️ 低置信度回复 ({len(low_conf_cases)}个)\n"
            for case in low_conf_cases[:3]:
                report += f"""
**问题**: {case["user_message"][:50]}...
**回复**: {case["ai_response"][:50]}...
**置信度**: {case["confidence"]:.2f}
---
"""

        report += f"\n\n**报告生成时间**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"

        return report

    except Exception as e:
        logger.error(f"Failed to generate learning report: {e}")
        return f"生成学习报告失败: {e}"


async def get_analytics_summary(pool) -> dict:
    """获取分析摘要数据（供前端使用）"""
    try:
        # 今日对话数
        today_conversations = (
            await pool.fetchval(
                """
            SELECT COUNT(DISTINCT session_id)
            FROM cs_conversation_log
            WHERE created_at::date = CURRENT_DATE
            """
            )
            or 0
        )

        # 好评率统计
        feedback_stats = await pool.fetchrow(
            """
            SELECT
                COUNT(CASE WHEN rating = 'good' THEN 1 END) as good_count,
                COUNT(CASE WHEN rating = 'bad' THEN 1 END) as bad_count,
                COUNT(*) as total_feedback
            FROM cs_feedback
            WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
            """
        )

        good_count = feedback_stats["good_count"] if feedback_stats else 0
        bad_count = feedback_stats["bad_count"] if feedback_stats else 0
        total_feedback = feedback_stats["total_feedback"] if feedback_stats else 0
        good_rate = good_count / total_feedback if total_feedback > 0 else 0

        # 最近差评
        recent_bad_feedback = await pool.fetch(
            """
            SELECT f.session_id, f.comment, f.created_at,
                   l.user_message, l.ai_response, l.intent
            FROM cs_feedback f
            LEFT JOIN cs_conversation_log l ON f.session_id = l.session_id
            WHERE f.rating = 'bad' AND f.created_at >= CURRENT_DATE - INTERVAL '3 days'
            ORDER BY f.created_at DESC
            LIMIT 5
            """
        )

        # 高频问题统计
        frequent_intents = await pool.fetch(
            """
            SELECT intent, COUNT(*) as count
            FROM cs_conversation_log
            WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
            AND intent IS NOT NULL
            GROUP BY intent
            ORDER BY count DESC
            LIMIT 5
            """
        )

        return {
            "today_conversations": today_conversations,
            "good_rate": round(good_rate, 3),
            "total_feedback": total_feedback,
            "good_count": good_count,
            "bad_count": bad_count,
            "recent_bad_feedback": [
                {
                    "session_id": row["session_id"],
                    "comment": row["comment"],
                    "user_message": row["user_message"][:100] if row["user_message"] else "",
                    "ai_response": row["ai_response"][:100] if row["ai_response"] else "",
                    "intent": row["intent"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else "",
                }
                for row in recent_bad_feedback
            ],
            "frequent_intents": [dict(row) for row in frequent_intents],
        }

    except Exception as e:
        logger.error(f"Failed to get analytics summary: {e}")
        return {
            "today_conversations": 0,
            "good_rate": 0,
            "total_feedback": 0,
            "good_count": 0,
            "bad_count": 0,
            "recent_bad_feedback": [],
            "frequent_intents": [],
        }


# 定时任务：自动学习（可以通过scheduler调用）
async def run_automatic_learning(pool) -> None:
    """执行自动学习流程"""
    try:
        logger.info("Starting automatic learning process...")

        # 1. 更新 few-shot 示例
        await update_few_shot_examples(pool)

        # 2. 生成学习洞察
        insights = await extract_learning_insights(pool)

        # 3. 记录学习日志
        await pool.execute(
            """
            INSERT INTO system_log (module, level, message, data, created_at)
            VALUES ('cs_learning', 'INFO', 'Automatic learning completed', $1, NOW())
            """,
            json.dumps(insights, ensure_ascii=False, default=str),
        )

        logger.info("Automatic learning process completed")

    except Exception as e:
        logger.error(f"Automatic learning failed: {e}")
        # 记录错误日志
        import contextlib

        with contextlib.suppress(Exception):
            await pool.execute(
                """
                INSERT INTO system_log (module, level, message, created_at)
                VALUES ('cs_learning', 'ERROR', $1, NOW())
                """,
                f"Automatic learning failed: {e}",
            )
