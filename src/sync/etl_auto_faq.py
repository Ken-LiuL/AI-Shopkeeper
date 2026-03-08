from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

_AUTO_FAQ_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS auto_faq (
    id SERIAL PRIMARY KEY,
    question TEXT,
    answer_template TEXT,
    source TEXT,
    frequency INT,
    category TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(question)
);
"""

_QUESTION_PATTERN = re.compile(r"[^。！？!?\\n]{2,80}[？?]")
_QUESTION_PREFIXES = ("怎么", "如何", "为什么", "能不能", "可以", "是否", "有没有", "多久", "多少钱")


def _normalize_text(text: Any) -> str:
    if text is None:
        return ""
    value = str(text).strip()
    return " ".join(value.split())


def _parse_keywords(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [_normalize_text(item) for item in value if _normalize_text(item)]
    if isinstance(value, dict):
        parsed: list[str] = []
        for key, val in value.items():
            candidate = _normalize_text(val if isinstance(val, str) else key)
            if candidate:
                parsed.append(candidate)
        return parsed
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            return _parse_keywords(parsed)
        except Exception:
            parts = re.split(r"[，,；;、/\\s]+", text)
            return [_normalize_text(item) for item in parts if _normalize_text(item)]
    return []


def _extract_questions(text: Any) -> list[str]:
    content = _normalize_text(text)
    if not content:
        return []
    questions = [_normalize_text(m.group(0)) for m in _QUESTION_PATTERN.finditer(content)]
    if questions:
        return questions
    for prefix in _QUESTION_PREFIXES:
        if prefix in content:
            return [_normalize_text(f"{content}？")]
    return []


def _classify_keyword(keyword: str) -> str:
    if any(k in keyword for k in ("副作用", "不良反应", "过敏", "禁忌")):
        return "用药安全"
    if any(k in keyword for k in ("发货", "配送", "物流", "送达")):
        return "物流"
    if any(k in keyword for k in ("质量", "破损", "过期", "失效")):
        return "商品质量"
    if any(k in keyword for k in ("价格", "贵", "优惠", "折扣")):
        return "价格"
    return "售后"


def _classify_question(question: str) -> str:
    if any(k in question for k in ("发货", "配送", "多久", "送到")):
        return "物流"
    if any(k in question for k in ("怎么用", "如何用", "剂量", "副作用", "禁忌")):
        return "用药安全"
    if any(k in question for k in ("退", "换", "售后", "退款")):
        return "售后"
    if any(k in question for k in ("价格", "多少钱", "优惠")):
        return "价格"
    return "咨询"


async def _classify_items_llm(items: list[str], item_type: str = "keyword") -> dict[str, str]:
    """用 LLM 批量分类。"""
    try:
        from src.agents.llm import MODEL_FLASH, call_tool

        classify_tool = {
            "name": "classify_items",
            "description": "为医疗器械客服FAQ内容分类",
            "input_schema": {
                "type": "object",
                "properties": {
                    "classifications": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item": {"type": "string"},
                                "category": {
                                    "type": "string",
                                    "enum": [
                                        "产品使用",
                                        "售后服务",
                                        "配送物流",
                                        "价格优惠",
                                        "产品功能",
                                        "安全注意",
                                        "通用",
                                    ],
                                },
                            },
                            "required": ["item", "category"],
                        },
                    }
                },
                "required": ["classifications"],
            },
        }
        prompt = f"为以下医疗器械电商{item_type}分配FAQ类别：\n" + "\n".join(
            f"- {i}" for i in items[:30]
        )
        result = await call_tool(prompt, classify_tool, model=MODEL_FLASH)
        if not isinstance(result, dict):
            return {}
        classifications = result.get("classifications", [])
        if not isinstance(classifications, list):
            return {}
        return {
            str(c.get("item")): str(c.get("category"))
            for c in classifications
            if isinstance(c, dict) and c.get("item") and c.get("category")
        }
    except Exception:
        return {}


def _chunk_items(items: list[str], chunk_size: int = 30) -> list[list[str]]:
    if chunk_size <= 0:
        return [items]
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def _build_keyword_answer(keyword: str) -> str:
    return (
        f"关于“{keyword}”问题，建议先核对商品说明与订单信息；"
        "如仍异常，请提供订单号与具体症状，我们将优先协助处理。"
    )


def _build_question_answer(question: str) -> str:
    return (
        f"关于“{question}”，建议先确认商品规格、使用场景和订单状态；"
        "如需人工协助，请补充订单号与截图信息。"
    )


async def _table_exists(conn, table_name: str) -> bool:
    return bool(await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table_name}"))


async def _pick_review_keywords_column(conn) -> str | None:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'qnh_review_analysis'
        """
    )
    available = {row["column_name"] for row in rows}
    if "keywords" in available:
        return "keywords"
    return None


async def run_auto_faq_etl(pool) -> None:
    """自动生成 FAQ 条目并写入 auto_faq。"""
    try:
        async with pool.acquire() as conn:
            await conn.execute(_AUTO_FAQ_TABLE_SQL)

            keyword_counter: Counter[str] = Counter()
            question_counter: Counter[str] = Counter()

            review_keywords_col = await _pick_review_keywords_column(conn)
            if review_keywords_col:
                review_rows = await conn.fetch(
                    f"""
                    SELECT {review_keywords_col} AS keywords, content
                    FROM qnh_review_analysis
                    WHERE sentiment = 'negative'
                       OR COALESCE(rating, 5) <= 2
                    """
                )
                for row in review_rows:
                    for keyword in _parse_keywords(row["keywords"]):
                        if len(keyword) >= 2:
                            keyword_counter[keyword] += 1
                    for question in _extract_questions(row.get("content")):
                        if len(question) >= 2:
                            question_counter[question] += 1

            if await _table_exists(conn, "qnh_im_messages"):
                msg_rows = await conn.fetch(
                    """
                    SELECT content
                    FROM qnh_im_messages
                    WHERE content IS NOT NULL
                      AND COALESCE(role, 'customer') = 'customer'
                    """
                )
                for row in msg_rows:
                    for question in _extract_questions(row["content"]):
                        if len(question) >= 2:
                            question_counter[question] += 1
            elif await _table_exists(conn, "qnh_im_sessions"):
                session_rows = await conn.fetch(
                    """
                    SELECT extra
                    FROM qnh_im_sessions
                    WHERE extra IS NOT NULL
                    """
                )
                for row in session_rows:
                    extra = row["extra"]
                    if isinstance(extra, str):
                        try:
                            extra = json.loads(extra)
                        except Exception:
                            extra = {}
                    if not isinstance(extra, dict):
                        continue
                    message_candidates = [
                        extra.get("content"),
                        extra.get("message"),
                        extra.get("latestMessage"),
                    ]
                    for candidate in message_candidates:
                        for question in _extract_questions(candidate):
                            if len(question) >= 2:
                                question_counter[question] += 1

            records: list[tuple[str, str, str, int, str]] = []
            keyword_items = [keyword for keyword, _ in keyword_counter.most_common(30)]
            question_items = [question for question, _ in question_counter.most_common(50)]

            keyword_categories: dict[str, str] = {}
            for batch in _chunk_items(keyword_items, chunk_size=30):
                keyword_categories.update(await _classify_items_llm(batch, item_type="keyword"))

            question_categories: dict[str, str] = {}
            for batch in _chunk_items(question_items, chunk_size=30):
                question_categories.update(await _classify_items_llm(batch, item_type="question"))

            for keyword, freq in keyword_counter.most_common(30):
                question = f"{keyword}问题怎么处理？"
                records.append(
                    (
                        question,
                        _build_keyword_answer(keyword),
                        "qnh_review_analysis",
                        int(freq),
                        keyword_categories.get(keyword) or _classify_keyword(keyword),
                    )
                )
            for question, freq in question_counter.most_common(50):
                records.append(
                    (
                        question,
                        _build_question_answer(question),
                        "qnh_im_sessions",
                        int(freq),
                        question_categories.get(question) or _classify_question(question),
                    )
                )

            if not records:
                logger.info("Auto FAQ ETL done: no candidate records")
                return

            dedup: dict[str, tuple[str, str, str, int, str]] = {}
            for record in records:
                question = record[0]
                old = dedup.get(question)
                if old is None or record[3] > old[3]:
                    dedup[question] = record

            await conn.executemany(
                """
                INSERT INTO auto_faq (
                    question,
                    answer_template,
                    source,
                    frequency,
                    category,
                    updated_at
                )
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (question) DO UPDATE SET
                    answer_template = EXCLUDED.answer_template,
                    source = EXCLUDED.source,
                    frequency = EXCLUDED.frequency,
                    category = EXCLUDED.category,
                    updated_at = NOW()
                """,
                list(dedup.values()),
            )
            logger.info("Auto FAQ ETL done: upserted=%d", len(dedup))
    except Exception:
        logger.exception("Auto FAQ ETL failed")
