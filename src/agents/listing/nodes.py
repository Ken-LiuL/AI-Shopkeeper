"""Listing Agent 各节点实现"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.db import postgres as pg

from ..llm import MODEL_DEEPSEEK, MODEL_FLASH, MODEL_SONNET, call_tool
from ..prompts.listing import compliance_prompt, filler_prompt, matcher_prompt, parser_prompt
from ..tools import COMPLIANCE_CHECK_TOOL, LISTING_INFO_TOOL, PARSED_PRODUCT_TOOL

MATCHER_TOOL = {
    "name": "match_meituan_standard",
    "description": "将供应商商品匹配到美团标品库，返回匹配结果和置信度",
    "input_schema": {
        "type": "object",
        "properties": {
            "matched_id": {
                "type": "string",
                "description": "匹配到的美团标品ID，若未匹配到则为空字符串",
            },
            "matched_name": {
                "type": "string",
                "description": "匹配到的美团标品名称",
            },
            "confidence": {
                "type": "number",
                "description": "匹配置信度，0.0~1.0",
            },
            "match_reason": {
                "type": "string",
                "description": "匹配原因或说明",
            },
        },
        "required": ["matched_id", "matched_name", "confidence", "match_reason"],
    },
}
from .state import ListingState

logger = logging.getLogger(__name__)


async def _get_pool_or_none():
    try:
        return pg.get_pool()
    except Exception:
        logger.warning("Listing agent running without PostgreSQL pool")
        return None


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _build_keyword_candidates(parsed: dict[str, Any], parsed_data: dict[str, Any]) -> list[str]:
    keywords: list[str] = []
    for v in [
        parsed.get("cleaned_title", ""),
        parsed_data.get("category", ""),
        parsed_data.get("brand", ""),
        parsed_data.get("barcode", ""),
    ]:
        text = str(v or "").strip()
        if text:
            keywords.append(text)
    return keywords


async def _query_category_mapping(pool, keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
    if not pool or not keywords:
        return []
    try:
        token = keywords[0]
        pattern = f"%{token}%"
        rows = await pool.fetch(
            """
            SELECT
                category_name,
                source,
                parent_category,
                product_count,
                sample_products,
                keywords,
                (
                    CASE WHEN category_name ILIKE $1 THEN 3 ELSE 0 END +
                    CASE WHEN EXISTS (
                        SELECT 1
                        FROM unnest(COALESCE(keywords, ARRAY[]::text[])) AS kw
                        WHERE $2 ILIKE '%' || kw || '%'
                    ) THEN 2 ELSE 0 END
                ) AS score
            FROM category_mapping
            WHERE category_name ILIKE $1
               OR EXISTS (
                    SELECT 1
                    FROM unnest(COALESCE(keywords, ARRAY[]::text[])) AS kw
                    WHERE $2 ILIKE '%' || kw || '%'
               )
            ORDER BY score DESC, product_count DESC NULLS LAST, updated_at DESC
            LIMIT $3
            """,
            pattern,
            " ".join(keywords),
            limit,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("Listing category_mapping query failed (graceful): %s", e)
        return []


async def _query_similar_products(pool, title: str, brand: str, category: str, limit: int = 8) -> list[dict[str, Any]]:
    if not pool:
        return []
    try:
        title_pattern = f"%{title}%" if title else "%"
        category_pattern = f"%{category}%" if category else "%"
        rows = await pool.fetch(
            """
            SELECT spu_id, sku_id, name, brand, category, spec, retail_price, status
            FROM qnh_products
            WHERE name ILIKE $1
               OR ($2 <> '' AND brand = $2)
               OR ($3 <> '' AND category ILIKE $3)
            ORDER BY synced_at DESC NULLS LAST, retail_price DESC NULLS LAST
            LIMIT $4
            """,
            title_pattern,
            brand or "",
            category_pattern,
            limit,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("Listing qnh_products similar query failed (graceful): %s", e)
        return []


async def _query_category_template_products(pool, category: str, limit: int = 8) -> list[dict[str, Any]]:
    if not pool or not category:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT
                name,
                brand,
                spec,
                category,
                extra->>'description' AS description
            FROM qnh_products
            WHERE category = $1 OR category ILIKE $2
            ORDER BY synced_at DESC NULLS LAST
            LIMIT $3
            """,
            category,
            f"%{category}%",
            limit,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("Listing template products query failed (graceful): %s", e)
        return []


async def _query_store_category_tree(pool, category: str, limit: int = 10) -> list[dict[str, Any]]:
    if not pool or not category:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT category_id, category_name, parent_id, parent_name, level
            FROM store_category_tree
            WHERE category_name ILIKE $1 OR parent_name ILIKE $1
            ORDER BY level ASC, synced_at DESC
            LIMIT $2
            """,
            f"%{category}%",
            limit,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("Listing store_category_tree query failed (graceful): %s", e)
        return []


async def _query_policy_documents(pool, limit: int = 6) -> list[dict[str, Any]]:
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT title, content, fetched_at, url
            FROM policy_documents
            ORDER BY fetched_at DESC NULLS LAST, id DESC
            LIMIT $1
            """,
            limit,
        )
        docs: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            content = str(data.get("content") or "").strip()
            if not content:
                continue
            docs.append(
                {
                    "title": str(data.get("title") or "平台政策"),
                    "content": content[:1200],
                    "url": str(data.get("url") or ""),
                    "fetched_at": str(data.get("fetched_at") or ""),
                }
            )
        return docs
    except Exception as e:
        logger.warning("Listing policy_documents query failed (graceful): %s", e)
        return []


def _render_matcher_context(
    existing_candidates: str,
    category_candidates: list[dict[str, Any]],
    similar_products: list[dict[str, Any]],
) -> str:
    lines: list[str] = [existing_candidates or "暂无候选"]

    if category_candidates:
        lines.append("\n[类目映射候选]")
        for i, item in enumerate(category_candidates, 1):
            lines.append(
                f"{i}. {item.get('category_name', '')} "
                f"(source={item.get('source', '')}, score={item.get('score', 0)}, "
                f"samples={item.get('sample_products') or []})"
            )

    if similar_products:
        lines.append("\n[历史相似已上架商品]")
        for i, item in enumerate(similar_products, 1):
            lines.append(
                f"{i}. {item.get('name', '')} | brand={item.get('brand', '')} "
                f"| category={item.get('category', '')} | spec={item.get('spec', '')}"
            )

    return "\n".join(lines)


def _resolve_reference_category(state: ListingState) -> str:
    if state.get("matched_category"):
        return str(state.get("matched_category") or "")

    category_candidates = state.get("category_mapping_candidates") or []
    if category_candidates:
        top = category_candidates[0] or {}
        if top.get("category_name"):
            return str(top.get("category_name"))

    parsed = state.get("parsed_product", {})
    parsed_data = parsed.get("parsed_data", {}) if isinstance(parsed, dict) else {}
    return str(parsed_data.get("category") or "")


async def parser_node(state: ListingState) -> dict:
    """Parser Sub-Agent: 解析 1688/拼多多商品信息"""
    try:
        platform = state.get("source_platform", "alibaba")
        prompt = parser_prompt(
            source_platform=platform,
            raw_product_data=state.get("raw_product_data", "暂无数据"),
        )
        result = await call_tool(prompt, PARSED_PRODUCT_TOOL, model=MODEL_SONNET)
        return {"parsed_product": result}
    except Exception as e:
        logger.error(f"Parser failed: {e}")
        return {"errors": state.get("errors", []) + [f"parser: {e}"]}


async def matcher_node(state: ListingState) -> dict:
    """Matcher Sub-Agent: 匹配美团标品库"""
    parsed = state.get("parsed_product", {})
    parsed_data = parsed.get("parsed_data", {})

    pool = await _get_pool_or_none()
    keywords = _build_keyword_candidates(parsed, parsed_data)
    category_candidates = await _query_category_mapping(pool, keywords)
    similar_products = await _query_similar_products(
        pool,
        title=str(parsed.get("cleaned_title") or ""),
        brand=str(parsed_data.get("brand") or ""),
        category=str(parsed_data.get("category") or ""),
    )

    meituan_candidates_context = _render_matcher_context(
        state.get("meituan_candidates", "暂无候选"),
        category_candidates,
        similar_products,
    )

    try:
        prompt = matcher_prompt(
            cleaned_title=parsed.get("cleaned_title", ""),
            barcode=parsed_data.get("barcode", ""),
            specifications=_safe_json(parsed_data.get("specifications", {})),
            meituan_candidates=meituan_candidates_context,
        )
        # Matcher 使用 Flash（快速匹配），通过 call_tool 统一调用
        result = await call_tool(prompt, MATCHER_TOOL, model=MODEL_FLASH)

        matched_category = ""
        if category_candidates:
            matched_category = str(category_candidates[0].get("category_name") or "")

        return {
            "matched_standard": {
                "matched_id": result.get("matched_id", ""),
                "matched_name": result.get("matched_name", ""),
                "match_reason": result.get("match_reason", ""),
            },
            "match_confidence": result.get("confidence", 0.0),
            "category_mapping_candidates": category_candidates,
            "similar_products": similar_products,
            "matched_category": matched_category,
        }
    except Exception as e:
        logger.error(f"Matcher failed: {e}")
        return {
            "matched_standard": None,
            "match_confidence": 0,
            "category_mapping_candidates": category_candidates,
            "similar_products": similar_products,
            "errors": state.get("errors", []) + [f"matcher: {e}"],
        }


async def filler_node(state: ListingState) -> dict:
    """Filler Sub-Agent: 填充上架信息 + 标题SEO + 定价"""
    try:
        parsed = state.get("parsed_product", {})
        category = _resolve_reference_category(state)
        pool = await _get_pool_or_none()

        template_products = await _query_category_template_products(pool, category)
        category_tree = await _query_store_category_tree(pool, category)

        competitor_prices = state.get("competitor_prices", "暂无数据")
        if template_products:
            competitor_prices += "\n\n[同类商品标题/描述模板参考]\n" + _safe_json(template_products)
        if category_tree:
            competitor_prices += "\n\n[店铺类目层级参考]\n" + _safe_json(category_tree)

        prompt = filler_prompt(
            parsed_product=_safe_json(parsed),
            matched_standard=_safe_json(state.get("matched_standard", {})),
            competitor_prices=competitor_prices,
            market_avg_price=state.get("market_avg_price", 0),
        )
        result = await call_tool(prompt, LISTING_INFO_TOOL, model=MODEL_DEEPSEEK)
        return {
            "listing_info": result,
            "template_products": template_products,
            "store_category_hierarchy": category_tree,
        }
    except Exception as e:
        logger.error(f"Filler failed: {e}")
        return {"errors": state.get("errors", []) + [f"filler: {e}"]}


async def compliance_node(state: ListingState) -> dict:
    """Compliance Sub-Agent: 合规校验"""
    try:
        listing = state.get("listing_info", {})
        parsed = state.get("parsed_product", {})
        category = parsed.get("parsed_data", {}).get("category", "医疗器械")

        pool = await _get_pool_or_none()
        policy_docs = await _query_policy_documents(pool)

        listing_with_policy: dict[str, Any] = {
            "listing_info": listing,
            "policy_context": policy_docs,
        }

        prompt = compliance_prompt(
            listing_info=_safe_json(listing_with_policy),
            product_category=category,
        )
        result = await call_tool(prompt, COMPLIANCE_CHECK_TOOL, model=MODEL_SONNET)
        return {
            "compliance_check": result,
            "policy_documents_context": policy_docs,
        }
    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        return {"errors": state.get("errors", []) + [f"compliance: {e}"]}
