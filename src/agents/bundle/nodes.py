"""Bundle Agent 各节点实现"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..llm import MODEL_DEEPSEEK, MODEL_PRO, call_tool
from ..prompts.bundle import order_mining_prompt, pricing_prompt, scene_design_prompt
from ..tools import ASSOCIATION_RULES_TOOL, BUNDLE_PRICING_TOOL, BUNDLE_PROPOSALS_TOOL
from .state import BundleState

logger = logging.getLogger(__name__)

DEFAULT_FP_CONFIG = json.dumps({
    "min_support": 0.01,
    "min_confidence": 0.30,
    "min_lift": 1.5,
    "max_itemset_size": 4,
    "min_order_count": 30,
}, ensure_ascii=False)


async def order_mining_node(state: BundleState) -> dict:
    """OrderMining Sub-Agent: FP-Growth 关联规则分析"""
    try:
        prompt = order_mining_prompt(
            orders_summary=state.get("orders_summary", "暂无数据"),
            fp_growth_config=state.get("fp_growth_config", DEFAULT_FP_CONFIG),
        )
        result = await call_tool(prompt, ASSOCIATION_RULES_TOOL, model=MODEL_PRO)
        return {"association_rules": result}
    except Exception as e:
        logger.error(f"Order mining failed: {e}")
        return {"errors": state.get("errors", []) + [f"order_mining: {e}"]}


async def scene_design_node(state: BundleState) -> dict:
    """Scene Sub-Agent: 场景理解 + 套餐命名"""
    try:
        prompt = scene_design_prompt(
            association_rules=json.dumps(state.get("association_rules", {}), ensure_ascii=False),
            product_details=state.get("product_details", "暂无数据"),
        )
        result = await call_tool(prompt, BUNDLE_PROPOSALS_TOOL, model=MODEL_DEEPSEEK)
        return {"bundle_proposals": result}
    except Exception as e:
        logger.error(f"Scene design failed: {e}")
        return {"errors": state.get("errors", []) + [f"scene_design: {e}"]}


async def pricing_node(state: BundleState) -> dict:
    """Pricing Sub-Agent: 套餐定价"""
    proposals = state.get("bundle_proposals", {})
    bundles = proposals.get("bundles", [])
    rules = state.get("association_rules", {}).get("rules", [])

    pricing_results: list[dict[str, Any]] = []
    errors = list(state.get("errors", []))

    # 构建 rule_id -> lift 映射
    lift_map: dict[str, float] = {}
    for rule in rules:
        rid = rule.get("rule_id", "")
        if rid:
            lift_map[rid] = rule.get("lift", 1.5)

    for bundle in bundles:
        bundle_id = bundle.get("bundle_id", "")
        try:
            # 查找对应的 lift
            lift_value = lift_map.get(bundle_id, 1.5)

            prompt = pricing_prompt(
                bundle_proposal=json.dumps(bundle, ensure_ascii=False),
                product_costs=state.get("product_costs", "暂无数据"),
                lift_value=lift_value,
            )
            result = await call_tool(prompt, BUNDLE_PRICING_TOOL, model=MODEL_DEEPSEEK)
            pricing_results.append(result)
        except Exception as e:
            logger.error(f"Pricing failed for bundle {bundle_id}: {e}")
            errors.append(f"pricing_{bundle_id}: {e}")

    return {"bundle_pricing": pricing_results, "errors": errors}
