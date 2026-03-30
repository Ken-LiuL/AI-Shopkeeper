"""Structured knowledge source helpers for customer service and admin APIs."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_FAQ_ENTRIES = [
    {
        "id": "faq_001",
        "question": "您的退货政策是什么？",
        "answer": "我们支持7天无理由退货，医疗器械产品需保证包装完整且未使用。如有质量问题，支持30天内换货。",
        "category": "退换货",
        "source": "default",
    },
    {
        "id": "faq_002",
        "question": "配送范围和时间是多久？",
        "answer": "我们覆盖全国大部分地区，一般1-3个工作日送达。偏远地区可能需要3-7个工作日。支持货到付款。",
        "category": "配送",
        "source": "default",
    },
    {
        "id": "faq_003",
        "question": "营业时间是什么？",
        "answer": "线上商城24小时营业，客服工作时间：周一至周日 9:00-18:00。紧急情况可留言，我们会尽快回复。",
        "category": "服务时间",
        "source": "default",
    },
    {
        "id": "faq_004",
        "question": "医疗器械是否有质保？",
        "answer": "所有医疗器械均提供正规发票和质保服务。不同产品质保期不同，一般为1-3年，具体请咨询客服。",
        "category": "质保",
        "source": "default",
    },
    {
        "id": "faq_005",
        "question": "支持哪些支付方式？",
        "answer": "支持微信支付、支付宝、银联卡、货到付款等多种支付方式。大额订单可联系客服协商。",
        "category": "支付",
        "source": "default",
    },
    {
        "id": "faq_006",
        "question": "如何使用医疗器械？",
        "answer": "每个产品都配有详细说明书，部分产品提供视频教程。如有疑问请咨询专业医护人员或我们的客服。",
        "category": "使用指南",
        "source": "default",
    },
]


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _dedupe_key(question: str, answer: str) -> str:
    return f"{_normalize_text(question).lower()}::{_normalize_text(answer).lower()}"


def _stable_id(prefix: str, raw: str) -> str:
    return f"{prefix}_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"


def _extract_keywords(*parts: Any) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part is None:
            continue
        if isinstance(part, list | tuple):
            tokens = [_normalize_text(item) for item in part]
        else:
            tokens = [_normalize_text(token) for token in str(part).replace("/", " ").split()]
        for token in tokens:
            if len(token) < 2:
                continue
            lowered = token.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            keywords.append(token)
    return keywords[:12]


def _matches_category(filter_value: str | None, candidate: str | None) -> bool:
    if not filter_value:
        return True
    filter_text = _normalize_text(filter_value).lower()
    candidate_text = _normalize_text(candidate).lower()
    return filter_text in candidate_text or candidate_text in filter_text


def _build_product_answer(row: dict[str, Any]) -> str:
    name = _normalize_text(row.get("name")) or "该商品"
    category = _normalize_text(row.get("category"))
    brand = _normalize_text(row.get("brand"))
    spec = _normalize_text(row.get("spec"))
    description = _normalize_text(row.get("description"))
    price = row.get("price")
    status = _normalize_text(row.get("status"))

    parts = [f"{name}"]
    meta: list[str] = []
    if brand:
        meta.append(f"品牌：{brand}")
    if category:
        meta.append(f"类目：{category}")
    if spec:
        meta.append(f"规格：{spec}")
    if price not in (None, ""):
        meta.append(f"售价：{price}")
    if status:
        meta.append(f"状态：{status}")
    if meta:
        parts.append("；".join(meta))
    if description:
        parts.append(description[:200])
    return "。".join(part for part in parts if part)


async def table_exists(pool, table_name: str) -> bool:
    try:
        exists = await pool.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = $1
            )
            """,
            table_name,
        )
        return bool(exists)
    except Exception:
        return False


async def get_knowledge_source_counts(pool) -> dict[str, int]:
    counts = {
        "knowledge_base_count": 0,
        "auto_faq_count": 0,
        "policy_count": 0,
        "product_knowledge_count": 0,
    }
    table_mapping = {
        "knowledge_base": "knowledge_base_count",
        "auto_faq": "auto_faq_count",
        "policy_documents": "policy_count",
        "product_knowledge": "product_knowledge_count",
    }
    for table_name, field in table_mapping.items():
        if not await table_exists(pool, table_name):
            continue
        try:
            counts[field] = int(await pool.fetchval(f"SELECT COUNT(*) FROM {table_name}") or 0)
        except Exception:
            logger.debug("Knowledge count query failed for %s", table_name, exc_info=True)
    counts["total_knowledge_items"] = sum(counts.values())
    return counts


async def load_structured_knowledge(pool, limit_per_source: int = 200) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_entry(entry: dict[str, Any]) -> None:
        question = str(entry.get("question") or "")
        answer = str(entry.get("answer") or "")
        if not question or not answer:
            return
        key = _dedupe_key(question, answer)
        if key in seen:
            return
        seen.add(key)
        entries.append(entry)

    if await table_exists(pool, "knowledge_base"):
        try:
            rows = await pool.fetch(
                """
                SELECT category, subcategory, question, answer, keywords, priority, product_categories
                FROM knowledge_base
                ORDER BY priority DESC, updated_at DESC NULLS LAST, id DESC
                LIMIT $1
                """,
                limit_per_source,
            )
            for row in rows:
                add_entry(
                    {
                        "category": row["category"],
                        "subcategory": row["subcategory"],
                        "question": row["question"],
                        "answer": row["answer"],
                        "keywords": row["keywords"] or [],
                        "priority": int(row["priority"] or 0),
                        "product_categories": row["product_categories"] or [],
                        "source": "knowledge_base",
                    }
                )
        except Exception:
            logger.warning("Failed to load knowledge_base records", exc_info=True)

    if await table_exists(pool, "auto_faq"):
        try:
            rows = await pool.fetch(
                """
                SELECT id, question, answer_template, category, frequency, updated_at
                FROM auto_faq
                WHERE question IS NOT NULL AND answer_template IS NOT NULL
                ORDER BY frequency DESC NULLS LAST, updated_at DESC NULLS LAST, id DESC
                LIMIT $1
                """,
                limit_per_source,
            )
            for row in rows:
                add_entry(
                    {
                        "category": "faq",
                        "subcategory": row["category"] or "自动FAQ",
                        "question": row["question"],
                        "answer": row["answer_template"],
                        "keywords": _extract_keywords(row["question"], row["category"]),
                        "priority": min(int(row["frequency"] or 0), 20) + 20,
                        "product_categories": [],
                        "source": "auto_faq",
                    }
                )
        except Exception:
            logger.warning("Failed to load auto_faq records", exc_info=True)

    if await table_exists(pool, "policy_documents"):
        try:
            rows = await pool.fetch(
                "SELECT * FROM policy_documents ORDER BY fetched_at DESC NULLS LAST LIMIT $1",
                limit_per_source,
            )
            for raw_row in rows:
                row = dict(raw_row)
                title = _normalize_text(
                    row.get("title") or row.get("name") or row.get("policy_name") or "售后政策"
                )
                content = _normalize_text(
                    row.get("content")
                    or row.get("body")
                    or row.get("text")
                    or row.get("policy_text")
                )
                if not title or not content:
                    continue
                add_entry(
                    {
                        "category": "policy",
                        "subcategory": row.get("policy_type") or row.get("category") or "售后政策",
                        "question": f"{title}怎么办？",
                        "answer": content[:500],
                        "keywords": _extract_keywords(title, row.get("policy_type"), row.get("category")),
                        "priority": 50,
                        "product_categories": [],
                        "source": "policy_documents",
                    }
                )
        except Exception:
            logger.warning("Failed to load policy documents", exc_info=True)

    if await table_exists(pool, "product_knowledge"):
        try:
            rows = await pool.fetch(
                """
                SELECT name, category, brand, spec, description, price, status
                FROM product_knowledge
                WHERE name IS NOT NULL AND name != ''
                ORDER BY updated_at DESC NULLS LAST, id DESC
                LIMIT $1
                """,
                limit_per_source,
            )
            for raw_row in rows:
                row = dict(raw_row)
                category = _normalize_text(row.get("category"))
                add_entry(
                    {
                        "category": "product",
                        "subcategory": category or "商品知识",
                        "question": f"{_normalize_text(row.get('name'))}有什么特点？",
                        "answer": _build_product_answer(row),
                        "keywords": _extract_keywords(
                            row.get("name"),
                            row.get("brand"),
                            row.get("category"),
                            row.get("spec"),
                        ),
                        "priority": 10,
                        "product_categories": [category] if category else [],
                        "source": "product_knowledge",
                    }
                )
        except Exception:
            logger.warning("Failed to load product knowledge rows", exc_info=True)

    return entries


async def search_faq_context(pool, query: str, limit: int = 3) -> list[dict[str, Any]]:
    q = _normalize_text(query)
    if not q:
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_result(question: str, answer: str, *, category: str = "", source: str = "", keywords: list[str] | None = None) -> None:
        if len(results) >= limit:
            return
        key = _dedupe_key(question, answer)
        if key in seen:
            return
        seen.add(key)
        results.append(
            {
                "id": _stable_id(source or "faq", key),
                "question": question,
                "answer_template": answer,
                "keywords": keywords or [],
                "category": category,
                "source": source,
            }
        )

    patterns = [f"%{q}%"]
    patterns.extend([f"%{token}%" for token in q.split() if len(token) >= 2][:5])

    if await table_exists(pool, "auto_faq"):
        try:
            for pattern in patterns:
                if len(results) >= limit:
                    break
                rows = await pool.fetch(
                    """
                    SELECT id, question, answer_template, category, frequency
                    FROM auto_faq
                    WHERE question ILIKE $1 OR answer_template ILIKE $1 OR COALESCE(category, '') ILIKE $1
                    ORDER BY frequency DESC NULLS LAST, updated_at DESC NULLS LAST, id DESC
                    LIMIT $2
                    """,
                    pattern,
                    limit,
                )
                for row in rows:
                    add_result(
                        question=str(row["question"] or ""),
                        answer=str(row["answer_template"] or ""),
                        category=str(row["category"] or ""),
                        source="auto_faq",
                        keywords=_extract_keywords(row["question"], row["category"]),
                    )
        except Exception:
            logger.debug("FAQ context lookup failed on auto_faq", exc_info=True)

    if len(results) < limit and await table_exists(pool, "knowledge_base"):
        try:
            for pattern in patterns:
                if len(results) >= limit:
                    break
                rows = await pool.fetch(
                    """
                    SELECT id, category, subcategory, question, answer, keywords
                    FROM knowledge_base
                    WHERE question ILIKE $1
                       OR answer ILIKE $1
                       OR COALESCE(category, '') ILIKE $1
                       OR COALESCE(subcategory, '') ILIKE $1
                    ORDER BY priority DESC, updated_at DESC NULLS LAST, id DESC
                    LIMIT $2
                    """,
                    pattern,
                    limit,
                )
                for row in rows:
                    add_result(
                        question=str(row["question"] or ""),
                        answer=str(row["answer"] or ""),
                        category=str(row["subcategory"] or row["category"] or ""),
                        source="knowledge_base",
                        keywords=row["keywords"] or [],
                    )
        except Exception:
            logger.debug("FAQ context lookup failed on knowledge_base", exc_info=True)

    if len(results) < limit and await table_exists(pool, "policy_documents"):
        try:
            for pattern in patterns:
                if len(results) >= limit:
                    break
                rows = await pool.fetch(
                    """
                    SELECT *
                    FROM policy_documents
                    WHERE COALESCE(title, '') ILIKE $1 OR COALESCE(content, '') ILIKE $1
                    ORDER BY fetched_at DESC NULLS LAST
                    LIMIT $2
                    """,
                    pattern,
                    limit,
                )
                for raw_row in rows:
                    row = dict(raw_row)
                    title = _normalize_text(row.get("title") or row.get("name") or row.get("policy_name"))
                    content = _normalize_text(
                        row.get("content")
                        or row.get("body")
                        or row.get("text")
                        or row.get("policy_text")
                    )
                    if not title or not content:
                        continue
                    add_result(
                        question=title,
                        answer=content[:300],
                        category=str(row.get("policy_type") or row.get("category") or "售后政策"),
                        source="policy_documents",
                        keywords=_extract_keywords(title, row.get("policy_type"), row.get("category")),
                    )
        except Exception:
            logger.debug("FAQ context lookup failed on policy_documents", exc_info=True)

    if results:
        return results[:limit]

    for item in _DEFAULT_FAQ_ENTRIES[:limit]:
        add_result(
            question=item["question"],
            answer=item["answer"],
            category=item["category"],
            source=item["source"],
        )
    return results[:limit]


async def list_faq_entries(pool, category: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_entry(entry: dict[str, Any]) -> None:
        if len(entries) >= limit:
            return
        question = str(entry.get("question") or "")
        answer = str(entry.get("answer") or "")
        if not question or not answer:
            return
        if not _matches_category(category, entry.get("category")):
            return
        key = _dedupe_key(question, answer)
        if key in seen:
            return
        seen.add(key)
        entries.append(entry)

    if await table_exists(pool, "auto_faq"):
        try:
            rows = await pool.fetch(
                """
                SELECT id, question, answer_template, category, frequency
                FROM auto_faq
                ORDER BY frequency DESC NULLS LAST, updated_at DESC NULLS LAST, id DESC
                LIMIT $1
                """,
                limit * 2,
            )
            for row in rows:
                add_entry(
                    {
                        "id": f"auto_faq_{row['id']}",
                        "question": row["question"],
                        "answer": row["answer_template"],
                        "category": row["category"] or "自动FAQ",
                        "source": "auto_faq",
                    }
                )
        except Exception:
            logger.debug("Failed to list auto_faq entries", exc_info=True)

    if len(entries) < limit and await table_exists(pool, "knowledge_base"):
        try:
            rows = await pool.fetch(
                """
                SELECT id, category, subcategory, question, answer
                FROM knowledge_base
                ORDER BY priority DESC, updated_at DESC NULLS LAST, id DESC
                LIMIT $1
                """,
                limit * 2,
            )
            for row in rows:
                add_entry(
                    {
                        "id": f"kb_{row['id']}",
                        "question": row["question"],
                        "answer": row["answer"],
                        "category": row["subcategory"] or row["category"] or "知识库",
                        "source": "knowledge_base",
                    }
                )
        except Exception:
            logger.debug("Failed to list knowledge_base entries", exc_info=True)

    if len(entries) < limit and await table_exists(pool, "policy_documents"):
        try:
            rows = await pool.fetch(
                "SELECT * FROM policy_documents ORDER BY fetched_at DESC NULLS LAST LIMIT $1",
                limit,
            )
            for raw_row in rows:
                row = dict(raw_row)
                title = _normalize_text(row.get("title") or row.get("name") or row.get("policy_name"))
                content = _normalize_text(
                    row.get("content")
                    or row.get("body")
                    or row.get("text")
                    or row.get("policy_text")
                )
                if not title or not content:
                    continue
                add_entry(
                    {
                        "id": _stable_id("policy", title),
                        "question": title,
                        "answer": content[:300],
                        "category": row.get("policy_type") or row.get("category") or "售后政策",
                        "source": "policy_documents",
                    }
                )
        except Exception:
            logger.debug("Failed to list policy documents", exc_info=True)

    if entries:
        return entries[:limit]

    fallback = [item for item in _DEFAULT_FAQ_ENTRIES if _matches_category(category, item["category"])]
    return fallback[:limit]
