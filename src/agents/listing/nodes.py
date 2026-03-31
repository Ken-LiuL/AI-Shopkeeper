"""Listing Agent 各节点实现"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.compliance.medical_device_rules import (
    apply_title_clean,
    check_text_violations,
)
from src.db import postgres as pg

from ..llm import MODEL_DEEPSEEK, MODEL_FLASH, MODEL_SONNET, call_tool, call_tool_with_reflection
from ..prompts.listing import compliance_prompt, filler_prompt, matcher_prompt, parser_prompt
from ..tools import COMPLIANCE_CHECK_TOOL, LISTING_INFO_TOOL, PARSED_PRODUCT_TOOL
from .state import ListingState

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
    # === GraphRAG 增强 ===
    graph_context = ""
    try:
        from src.db import neo4j as neo4j_db
        from src.skills.neo4j_skill import Neo4jSkill

        driver = neo4j_db.get_driver()
        skill = Neo4jSkill(driver=driver)
        product_name = str(
            parsed.get("cleaned_title")
            or parsed_data.get("product_name")
            or parsed_data.get("name")
            or ""
        ).strip()
        if product_name:
            suggested_categories = await skill.suggest_category(product_name)
            if suggested_categories:
                graph_context = (
                    "\n\n[图谱类目推荐]\n"
                    f"{_safe_json(suggested_categories)}"
                )
    except Exception:
        graph_context = ""
    if graph_context:
        meituan_candidates_context = f"{meituan_candidates_context}{graph_context}"

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


def _apply_listing_compliance_filter(
    listing_info: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    对 filler LLM 输出做硬编码合规后处理。

    检查 title / selling_points / description 是否含违规词，
    能自动修复的直接替换，无法修复的标记为 issue 供 compliance_node 合并。

    Returns:
        (cleaned_listing_info, auto_fixed_items)
        auto_fixed_items 格式与 ViolationItem 兼容，附加 original_text。
    """
    if not isinstance(listing_info, dict):
        return listing_info, []

    cleaned = dict(listing_info)
    auto_fixed_items: list[dict[str, Any]] = []

    # ── 标题清洗 ──────────────────────────────────────────────────────────
    raw_title = str(cleaned.get("title") or "")
    cleaned_title, removed_words = apply_title_clean(raw_title)
    if removed_words:
        auto_fixed_items.append({
            "field": "title",
            "action": "remove_marketing_words",
            "original_text": raw_title,
            "fixed_text": cleaned_title,
            "matched_words": removed_words,
            "rule_category": "标题营销词",
            "severity": "warning",
            "auto_fixed": True,
        })
        cleaned["title"] = cleaned_title

    # ── 标题违规词检查 ────────────────────────────────────────────────────
    title_after, title_violations = check_text_violations(
        cleaned.get("title", ""), field_name="title", auto_fix=True
    )
    if title_violations:
        if title_after != cleaned.get("title"):
            cleaned["title"] = title_after
        for v in title_violations:
            auto_fixed_items.append(dict(v))

    # ── 卖点逐条检查 ──────────────────────────────────────────────────────
    selling_points = cleaned.get("selling_points") or []
    if isinstance(selling_points, list):
        cleaned_points: list[str] = []
        for i, point in enumerate(selling_points):
            point_str = str(point)
            fixed_point, point_violations = check_text_violations(
                point_str, field_name=f"selling_points[{i}]", auto_fix=True
            )
            cleaned_points.append(fixed_point)
            for v in point_violations:
                auto_fixed_items.append(dict(v))
        cleaned["selling_points"] = cleaned_points

    # ── 描述检查 ──────────────────────────────────────────────────────────
    description = str(cleaned.get("description") or "")
    if description:
        fixed_desc, desc_violations = check_text_violations(
            description, field_name="description", auto_fix=True
        )
        if fixed_desc != description:
            cleaned["description"] = fixed_desc
        for v in desc_violations:
            auto_fixed_items.append(dict(v))

    return cleaned, auto_fixed_items


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

        # ── 硬编码合规后处理（LLM 输出层之后） ───────────────────────────
        filtered_result, auto_fixed_items = _apply_listing_compliance_filter(result)
        if auto_fixed_items:
            logger.info(
                "Filler compliance filter applied %d fix(es) to listing_info",
                len(auto_fixed_items),
            )

        return {
            "listing_info": filtered_result,
            "filler_auto_fixed": auto_fixed_items,
            "template_products": template_products,
            "store_category_hierarchy": category_tree,
        }
    except Exception as e:
        logger.error(f"Filler failed: {e}")
        return {"errors": state.get("errors", []) + [f"filler: {e}"]}


def _build_compliance_result(
    llm_result: dict[str, Any],
    filler_auto_fixed: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    合并 LLM 合规校验结果与 filler 硬编码修复记录，生成增强版合规结果。

    增加字段：
      - auto_fixed:            已自动修复的问题（来自 filler 后处理）
      - requires_manual_review: 需人工确认的问题（fatal/error 且未自动修复）
      - summary:               一句话摘要
    """
    issues: list[dict[str, Any]] = llm_result.get("issues") or []
    can_proceed: bool = bool(llm_result.get("can_proceed", True))
    passed: bool = bool(llm_result.get("passed", can_proceed))

    # ── 分类 filler 修复记录 ──────────────────────────────────────────────
    auto_fixed: list[dict[str, Any]] = [
        item for item in filler_auto_fixed if item.get("auto_fixed")
    ]
    unfixed_violations: list[dict[str, Any]] = [
        item for item in filler_auto_fixed if not item.get("auto_fixed")
    ]

    # ── 需人工确认 = LLM fatal/error issues + 未自动修复的 filler violations ─
    requires_manual_review: list[dict[str, Any]] = [
        issue for issue in issues
        if issue.get("severity") in ("fatal", "error")
    ] + [
        {
            "source": "filler_filter",
            "field": v.get("field", ""),
            "matched_text": v.get("matched_text", ""),
            "rule_category": v.get("rule_category", ""),
            "severity": v.get("severity", "error"),
            "suggestion": v.get("suggestion", ""),
        }
        for v in unfixed_violations
    ]

    # ── 摘要 ──────────────────────────────────────────────────────────────
    fatal_count = sum(1 for i in issues if i.get("severity") == "fatal")
    error_count = sum(1 for i in issues if i.get("severity") == "error")
    warning_count = sum(1 for i in issues if i.get("severity") == "warning")
    auto_fix_count = len(auto_fixed)
    manual_count = len(requires_manual_review)

    if not passed and (fatal_count > 0 or error_count > 0):
        summary = (
            f"合规校验未通过：{fatal_count} 条严重问题、{error_count} 条错误"
            + (f"、{auto_fix_count} 条已自动修复" if auto_fix_count else "")
            + f"，需人工确认 {manual_count} 条"
        )
    elif warning_count > 0 or manual_count > 0:
        summary = (
            f"通过合规校验，有 {warning_count} 条警告"
            + (f"、{auto_fix_count} 条已自动修复" if auto_fix_count else "")
            + (f"，需人工确认 {manual_count} 条" if manual_count else "")
        )
    else:
        summary = "通过合规校验" + (f"，{auto_fix_count} 条已自动修复" if auto_fix_count else "")

    return {
        **llm_result,
        "passed": passed,
        "can_proceed": can_proceed,
        "issues": issues,
        "auto_fixed": auto_fixed,
        "requires_manual_review": requires_manual_review,
        "summary": summary,
    }


def _build_final_result(state: ListingState, compliance_enriched: dict[str, Any]) -> dict[str, Any]:
    """
    将 LangGraph state 中的各阶段结果组装为标准化最终输出格式。
    """
    parsed = state.get("parsed_product") or {}
    parsed_data = parsed.get("parsed_data") or {} if isinstance(parsed, dict) else {}
    matched = state.get("matched_standard") or {}
    listing = state.get("listing_info") or {}

    can_proceed: bool = bool(compliance_enriched.get("can_proceed", True))
    has_fatal = any(
        i.get("severity") == "fatal"
        for i in (compliance_enriched.get("issues") or [])
    )
    ready_to_publish: bool = can_proceed and not has_fatal

    return {
        "parsed": {
            "cleaned_title": parsed.get("cleaned_title", ""),
            "brand": parsed_data.get("brand", ""),
            "category": parsed_data.get("category", ""),
            "barcode": parsed_data.get("barcode", ""),
            "specifications": parsed_data.get("specifications", {}),
            "compliance_info": parsed_data.get("compliance_info", {}),
            "confidence": parsed.get("confidence", 0.0),
        },
        "matching": {
            "standard_id": matched.get("matched_id", ""),
            "standard_name": matched.get("matched_name", ""),
            "confidence": state.get("match_confidence", 0.0),
            "match_reason": matched.get("match_reason", ""),
        },
        "listing": {
            "title": listing.get("title", ""),
            "price": listing.get("price") or listing.get("suggested_price", 0.0),
            "selling_points": listing.get("selling_points") or [],
            "keywords": listing.get("keywords") or [],
            "description": listing.get("description", ""),
            "category": listing.get("category", ""),
        },
        "compliance": {
            "passed": compliance_enriched.get("passed", False),
            "can_proceed": can_proceed,
            "issues": compliance_enriched.get("issues") or [],
            "auto_fixed": compliance_enriched.get("auto_fixed") or [],
            "requires_manual_review": compliance_enriched.get("requires_manual_review") or [],
            "summary": compliance_enriched.get("summary", ""),
        },
        "ready_to_publish": ready_to_publish,
    }


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

        def _reflect_compliance(initial_result_str: str) -> str:
            return f"""请审查以下合规校验结论，检查：
1. 是否遗漏了关键合规风险点
2. 风险等级与问题优先级是否匹配
3. 整改建议是否具体且可执行
4. 数据引用与政策依据是否一致

初始结论：
{initial_result_str}

请给出修订后的版本，如果没问题则保持不变。"""

        result = await call_tool_with_reflection(
            initial_prompt=prompt,
            reflection_prompt_fn=_reflect_compliance,
            tool=COMPLIANCE_CHECK_TOOL,
            model=MODEL_SONNET,
        )
        result_dict = result if isinstance(result, dict) else {"result": result}

        # ── 合并 filler 硬编码修复记录，生成增强版合规结果 ───────────────
        filler_auto_fixed: list[dict[str, Any]] = state.get("filler_auto_fixed") or []
        compliance_enriched = _build_compliance_result(result_dict, filler_auto_fixed)

        # ── 构建结构化最终结果 ────────────────────────────────────────────
        final_result = _build_final_result(state, compliance_enriched)

        if pool:
            try:
                from src.agents.action_tracker import record_action

                parsed_data = parsed.get("parsed_data", {}) if isinstance(parsed, dict) else {}
                matched = state.get("matched_standard") or {}
                issue_count = len(compliance_enriched.get("issues", []))
                await record_action(
                    pool=pool,
                    agent_type="listing",
                    action_type="listing_compliance",
                    product_id=matched.get("matched_id") or None,
                    product_name=parsed.get("cleaned_title") or parsed_data.get("title"),
                    decision=compliance_enriched,
                    confidence=1.0 if compliance_enriched.get("passed") else 0.6,
                    context_summary=f"category={category}, issues={issue_count}",
                    baseline_metrics={
                        "match_confidence": state.get("match_confidence"),
                        "market_avg_price": state.get("market_avg_price"),
                    },
                )
            except Exception as e:
                logger.warning("Failed to record listing compliance action: %s", e)

        return {
            "compliance_check": compliance_enriched,
            "policy_documents_context": policy_docs,
            "final_result": final_result,
        }
    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        return {"errors": state.get("errors", []) + [f"compliance: {e}"]}
