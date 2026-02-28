"""
LLM-as-judge 自动评分系统
用Flash模型对客服回复质量进行多维度评分
"""

import logging

from ..llm import MODEL_FLASH, call_tool

logger = logging.getLogger(__name__)


async def evaluate_reply(
    user_message: str,
    ai_reply: str,
    conversation_history: list[dict] | None = None,
    product_results: list[dict] | None = None,
) -> dict:
    """
    评估AI客服回复质量

    Args:
        user_message: 用户消息
        ai_reply: AI回复
        conversation_history: 对话历史
        product_results: 商品搜索结果

    Returns:
        评分结果字典，包含各维度评分和反馈
    """
    try:
        # 构建评分提示词
        evaluation_prompt = _build_evaluation_prompt(
            user_message, ai_reply, conversation_history, product_results
        )

        # 定义评分工具schema
        evaluation_tool = {
            "name": "evaluate_cs_reply",
            "description": "评估客服回复质量",
            "input_schema": {
                "type": "object",
                "properties": {
                    "accuracy": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "信息准确性（0-1），是否瞎编商品信息",
                    },
                    "professionalism": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "专业度（0-1），医疗器械领域知识是否准确",
                    },
                    "tone": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "语气评分（0-1），是否亲切但不过分，符合美团客服风格",
                    },
                    "resolution": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "解决度（0-1），是否回答了用户问题",
                    },
                    "compliance": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "合规性（0-1），没有给医疗建议等红线",
                    },
                    "overall": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "综合评分（0-1）",
                    },
                    "feedback": {"type": "string", "description": "改进建议文本"},
                },
                "required": [
                    "accuracy",
                    "professionalism",
                    "tone",
                    "resolution",
                    "compliance",
                    "overall",
                    "feedback",
                ],
            },
        }

        system_prompt = """你是一个专业的客服质量评估专家，专门评估医疗器械电商平台的AI客服回复质量。

评分标准：
1. accuracy（信息准确性）: 回复中的商品信息、价格、功能是否准确，不能瞎编
2. professionalism（专业度）: 医疗器械专业知识是否准确，术语使用是否得当
3. tone（语气）: 是否亲切但不过分热情，符合美团客服的专业亲和风格
4. resolution（解决度）: 是否直接回答了用户的核心问题
5. compliance（合规性）: 是否避免给出医疗建议、诊断建议等违规内容
6. overall（综合评分）: 综合以上维度的整体评价

评分范围：0.0-1.0，1.0为最高分
反馈建议：简洁具体，指出主要问题和改进方向"""

        # 调用Flash模型进行评分
        result = await call_tool(
            prompt=evaluation_prompt,
            tool=evaluation_tool,
            model=MODEL_FLASH,
            system=system_prompt,
            trace_name="cs_reply_evaluation",
        )

        # 确保返回的分数在合理范围内
        for score_key in [
            "accuracy",
            "professionalism",
            "tone",
            "resolution",
            "compliance",
            "overall",
        ]:
            if score_key in result:
                result[score_key] = max(0.0, min(1.0, float(result[score_key])))

        logger.info(f"Reply evaluation completed, overall score: {result.get('overall', 0):.2f}")
        return result

    except Exception as e:
        logger.error(f"Failed to evaluate reply: {e}")
        # 返回默认低分，确保系统继续运行
        return {
            "accuracy": 0.5,
            "professionalism": 0.5,
            "tone": 0.5,
            "resolution": 0.5,
            "compliance": 0.5,
            "overall": 0.5,
            "feedback": f"评分失败: {str(e)}",
        }


def _build_evaluation_prompt(
    user_message: str,
    ai_reply: str,
    conversation_history: list[dict] | None = None,
    product_results: list[dict] | None = None,
) -> str:
    """构建评分提示词"""

    prompt = f"""请评估以下AI客服回复的质量：

# 用户问题
{user_message}

# AI回复
{ai_reply}
"""

    # 添加对话历史上下文
    if conversation_history and len(conversation_history) > 0:
        prompt += "\n# 对话历史\n"
        for msg in conversation_history[-3:]:  # 只显示最近3轮对话
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"{role}: {content[:100]}{'...' if len(content) > 100 else ''}\n"

    # 添加商品搜索结果
    if product_results and len(product_results) > 0:
        prompt += "\n# 相关商品信息\n"
        for i, product in enumerate(product_results[:3], 1):  # 只显示前3个商品
            name = product.get("name", "未知商品")
            description = product.get("description", "")
            price = product.get("retail_price", 0)
            prompt += f"{i}. {name} - ¥{price} - {description[:50]}{'...' if len(description) > 50 else ''}\n"

    prompt += """
请基于以上信息，对AI回复的质量进行评分。重点关注：
- 回复是否准确使用了商品信息
- 是否展现了专业的医疗器械知识
- 语气是否符合美团客服标准
- 是否解决了用户的具体问题
- 是否避免了医疗建议等合规风险
"""

    return prompt


async def evaluate_and_store(
    pool,
    session_id: str,
    user_message: str,
    ai_reply: str,
    conversation_history: list[dict] | None = None,
    product_results: list[dict] | None = None,
) -> None:
    """
    评分并存储到数据库（异步执行，不阻塞响应）

    Args:
        pool: 数据库连接池
        session_id: 会话ID
        user_message: 用户消息
        ai_reply: AI回复
        conversation_history: 对话历史
        product_results: 商品搜索结果
    """
    try:
        # 1. 执行评分
        scores = await evaluate_reply(
            user_message=user_message,
            ai_reply=ai_reply,
            conversation_history=conversation_history,
            product_results=product_results,
        )

        # 2. 创建评分表（如果不存在）
        await _ensure_scores_table(pool)

        # 3. 存储评分结果
        await pool.execute(
            """
            INSERT INTO cs_reply_scores (
                session_id, user_message, ai_reply,
                accuracy, professionalism, tone, resolution, compliance, overall, feedback,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
            """,
            session_id,
            user_message[:1000],  # 限制长度避免过长
            ai_reply[:2000],
            scores.get("accuracy", 0),
            scores.get("professionalism", 0),
            scores.get("tone", 0),
            scores.get("resolution", 0),
            scores.get("compliance", 0),
            scores.get("overall", 0),
            scores.get("feedback", "")[:500],  # 限制feedback长度
        )

        # 4. 如果评分很低，标记需要review
        overall_score = scores.get("overall", 0)
        if overall_score < 0.6:
            await _mark_for_review(pool, session_id, overall_score, scores.get("feedback", ""))
            logger.warning(
                f"Low score reply marked for review: session={session_id}, score={overall_score:.2f}"
            )

        logger.info(
            f"Evaluation stored for session {session_id}, overall score: {overall_score:.2f}"
        )

    except Exception as e:
        logger.error(f"Failed to evaluate and store: {e}")


async def _ensure_scores_table(pool) -> None:
    """确保cs_reply_scores表存在"""
    try:
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS cs_reply_scores (
                id SERIAL PRIMARY KEY,
                session_id TEXT,
                user_message TEXT,
                ai_reply TEXT,
                accuracy REAL,
                professionalism REAL,
                tone REAL,
                resolution REAL,
                compliance REAL,
                overall REAL,
                feedback TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # 创建索引
        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_cs_reply_scores_session
            ON cs_reply_scores(session_id)
        """)

        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_cs_reply_scores_overall
            ON cs_reply_scores(overall DESC)
        """)

        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_cs_reply_scores_created
            ON cs_reply_scores(created_at DESC)
        """)

    except Exception as e:
        logger.warning(f"Failed to ensure scores table: {e}")


async def _mark_for_review(pool, session_id: str, score: float, feedback: str) -> None:
    """标记低分回复需要人工review"""
    try:
        # 创建review表（如果不存在）
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS cs_review_queue (
                id SERIAL PRIMARY KEY,
                session_id TEXT,
                score REAL,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ,
                reviewer TEXT
            )
        """)

        # 插入review记录
        await pool.execute(
            """
            INSERT INTO cs_review_queue (session_id, score, reason)
            VALUES ($1, $2, $3)
            """,
            session_id,
            score,
            f"低分回复需要审核: {feedback}",
        )

    except Exception as e:
        logger.warning(f"Failed to mark for review: {e}")


async def get_recent_scores(pool, limit: int = 20) -> list[dict]:
    """获取最近的评分结果"""
    try:
        rows = await pool.fetch(
            """
            SELECT session_id, user_message, ai_reply,
                   accuracy, professionalism, tone, resolution, compliance, overall,
                   feedback, created_at
            FROM cs_reply_scores
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )

        return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"Failed to get recent scores: {e}")
        return []


async def get_score_analytics(pool) -> dict:
    """获取评分分析数据"""
    try:
        # 总体统计
        stats = await pool.fetchrow(
            """
            SELECT
                COUNT(*) as total_evaluations,
                AVG(overall) as avg_overall,
                AVG(accuracy) as avg_accuracy,
                AVG(professionalism) as avg_professionalism,
                AVG(tone) as avg_tone,
                AVG(resolution) as avg_resolution,
                AVG(compliance) as avg_compliance,
                COUNT(CASE WHEN overall < 0.6 THEN 1 END) as low_score_count
            FROM cs_reply_scores
            WHERE created_at >= NOW() - INTERVAL '7 days'
            """
        )

        # 每日趋势
        daily_trend = await pool.fetch(
            """
            SELECT
                DATE(created_at) as date,
                COUNT(*) as count,
                AVG(overall) as avg_score
            FROM cs_reply_scores
            WHERE created_at >= NOW() - INTERVAL '7 days'
            GROUP BY DATE(created_at)
            ORDER BY date
            """
        )

        return {
            "overall_stats": dict(stats) if stats else {},
            "daily_trend": [dict(row) for row in daily_trend],
            "generated_at": "NOW()",
        }

    except Exception as e:
        logger.error(f"Failed to get score analytics: {e}")
        return {}
