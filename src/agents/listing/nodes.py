"""Listing Agent 各节点实现"""

from __future__ import annotations

import json
import logging

from ..llm import MODEL_DEEPSEEK, MODEL_FLASH, MODEL_SONNET, call_tool
from ..prompts.listing import compliance_prompt, filler_prompt, matcher_prompt, parser_prompt
from ..tools import COMPLIANCE_CHECK_TOOL, LISTING_INFO_TOOL, PARSED_PRODUCT_TOOL
from .state import ListingState

logger = logging.getLogger(__name__)


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

    try:
        prompt = matcher_prompt(
            cleaned_title=parsed.get("cleaned_title", ""),
            barcode=parsed_data.get("barcode", ""),
            specifications=json.dumps(parsed_data.get("specifications", {}), ensure_ascii=False),
            meituan_candidates=state.get("meituan_candidates", "暂无候选"),
        )
        # Matcher 使用 Haiku（快速匹配）
        # NOTE: Matcher 不用 tool_use，直接返回文本
        # 实际中可能用数据库精确查询 + LLM 辅助模糊匹配
        from ..llm import get_client

        client = get_client()
        response = await client.messages.create(
            model=MODEL_FLASH,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        # 简化处理：将匹配结果存入 state
        match_text = response.content[0].text if response.content else ""
        return {
            "matched_standard": {"raw_match": match_text},
            "match_confidence": 0.5,  # 实际由匹配逻辑决定
        }
    except Exception as e:
        logger.error(f"Matcher failed: {e}")
        return {
            "matched_standard": None,
            "match_confidence": 0,
            "errors": state.get("errors", []) + [f"matcher: {e}"],
        }


async def filler_node(state: ListingState) -> dict:
    """Filler Sub-Agent: 填充上架信息 + 标题SEO + 定价"""
    try:
        parsed = state.get("parsed_product", {})
        prompt = filler_prompt(
            parsed_product=json.dumps(parsed, ensure_ascii=False),
            matched_standard=json.dumps(state.get("matched_standard", {}), ensure_ascii=False),
            competitor_prices=state.get("competitor_prices", "暂无数据"),
            market_avg_price=state.get("market_avg_price", 0),
        )
        result = await call_tool(prompt, LISTING_INFO_TOOL, model=MODEL_DEEPSEEK)
        return {"listing_info": result}
    except Exception as e:
        logger.error(f"Filler failed: {e}")
        return {"errors": state.get("errors", []) + [f"filler: {e}"]}


async def compliance_node(state: ListingState) -> dict:
    """Compliance Sub-Agent: 合规校验"""
    try:
        listing = state.get("listing_info", {})
        parsed = state.get("parsed_product", {})
        category = parsed.get("parsed_data", {}).get("category", "医疗器械")

        prompt = compliance_prompt(
            listing_info=json.dumps(listing, ensure_ascii=False),
            product_category=category,
        )
        result = await call_tool(prompt, COMPLIANCE_CHECK_TOOL, model=MODEL_SONNET)
        return {"compliance_check": result}
    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        return {"errors": state.get("errors", []) + [f"compliance: {e}"]}
