"""Bundle Agent 各节点实现"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from ..llm import MODEL_DEEPSEEK, MODEL_PRO, MODEL_SONNET, call_tool, call_tool_with_reflection
from ..prompts.bundle import order_mining_prompt, pricing_prompt, scene_design_prompt
from ..tools import ASSOCIATION_RULES_TOOL, BUNDLE_PRICING_TOOL, BUNDLE_PROPOSALS_TOOL
from .state import BundleState

logger = logging.getLogger(__name__)

DEFAULT_FP_CONFIG = json.dumps(
    {
        "min_support": 0.01,
        "min_confidence": 0.30,
        "min_lift": 1.5,
        "max_itemset_size": 4,
        "min_order_count": 30,
    },
    ensure_ascii=False,
)


def _normalize_key(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except Exception:
        return 0.0


def _season_tag_for_month(month: int) -> str:
    if month in (3, 4, 5):
        return "春季"
    if month in (6, 7, 8):
        return "夏季"
    if month in (9, 10, 11):
        return "秋季"
    return "冬季"


def _round_marketing_price(value: float) -> float:
    if value <= 0:
        return 0.0
    integer = int(value)
    candidate_9 = integer + 0.9
    if candidate_9 < value:
        candidate_9 = integer + 1.9
    candidate_8 = integer + 0.8
    if candidate_8 < value:
        candidate_8 = integer + 1.8
    rounded = candidate_8 if candidate_8 <= candidate_9 else candidate_9
    if int(rounded) % 10 == 4:
        rounded = int(rounded) + 1.9
    return round(rounded, 1)


def _build_catalog_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        name_key = _normalize_key(row.get("name"))
        if name_key:
            index[name_key] = row
        for pid_key in ("product_id", "spu_id", "sku_id"):
            pid = str(row.get(pid_key) or "").strip()
            if pid:
                index[f"id:{pid}"] = row
    return index


def _lookup_product(catalog: dict[str, dict[str, Any]], product: dict[str, Any]) -> dict[str, Any] | None:
    product_id = str(product.get("product_id") or "").strip()
    if product_id:
        hit = catalog.get(f"id:{product_id}")
        if hit:
            return hit
    name_key = _normalize_key(product.get("name"))
    if name_key:
        return catalog.get(name_key)
    return None


async def _fetch_top_association_pairs(pool, limit: int = 24) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT product_a, product_b, co_occurrence, confidence
        FROM product_associations
        ORDER BY co_occurrence DESC, confidence DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(row) for row in rows]


async def _fetch_product_catalog(pool, names: list[str]) -> list[dict[str, Any]]:
    if not names:
        return []
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (name)
            spu_id AS product_id,
            spu_id,
            sku_id,
            name,
            category,
            brand,
            retail_price,
            cost_price,
            synced_at
        FROM qnh_products
        WHERE name = ANY($1::text[])
        ORDER BY name, synced_at DESC NULLS LAST, product_id DESC
        """,
        names,
    )
    return [dict(row) for row in rows]


async def _fetch_seasonality_context(pool, month: int, names: list[str]) -> list[dict[str, Any]]:
    season_tag = _season_tag_for_month(month)
    if names:
        rows = await pool.fetch(
            """
            SELECT product_name, peak_months, seasonal_tag, avg_monthly_sales, peak_ratio
            FROM product_seasonality
            WHERE product_name = ANY($1::text[])
              AND ($2 = ANY(peak_months) OR seasonal_tag = $3 OR seasonal_tag = '全年')
            ORDER BY peak_ratio DESC NULLS LAST, avg_monthly_sales DESC NULLS LAST
            LIMIT 30
            """,
            names,
            month,
            season_tag,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT product_name, peak_months, seasonal_tag, avg_monthly_sales, peak_ratio
            FROM product_seasonality
            WHERE $1 = ANY(peak_months) OR seasonal_tag = $2 OR seasonal_tag = '全年'
            ORDER BY peak_ratio DESC NULLS LAST, avg_monthly_sales DESC NULLS LAST
            LIMIT 30
            """,
            month,
            season_tag,
        )
    return [dict(row) for row in rows]


async def order_mining_node(state: BundleState) -> dict:
    """OrderMining Sub-Agent: FP-Growth 关联规则分析"""
    try:
        orders_summary = state.get("orders_summary", "暂无数据")
        product_details = state.get("product_details", "暂无数据")
        product_costs = state.get("product_costs", "暂无数据")
        db_association_pairs: list[dict[str, Any]] = []
        db_product_rows: list[dict[str, Any]] = []
        pool = state.get("db_pool")

        if pool:
            db_association_pairs = await _fetch_top_association_pairs(pool)
            names = sorted(
                {
                    str(pair.get("product_a") or "").strip()
                    for pair in db_association_pairs
                }
                | {
                    str(pair.get("product_b") or "").strip()
                    for pair in db_association_pairs
                }
            )
            names = [name for name in names if name]
            db_product_rows = await _fetch_product_catalog(pool, names)

            if db_association_pairs:
                orders_summary = json.dumps(
                    {
                        "source": "product_associations",
                        "top_pairs": db_association_pairs,
                    },
                    ensure_ascii=False,
                )
            if db_product_rows:
                product_details = json.dumps(
                    [
                        {
                            "product_id": row.get("product_id"),
                            "name": row.get("name"),
                            "category": row.get("category"),
                            "brand": row.get("brand"),
                            "retail_price": _to_float(row.get("retail_price")),
                        }
                        for row in db_product_rows
                    ],
                    ensure_ascii=False,
                )
                product_costs = json.dumps(
                    [
                        {
                            "product_id": row.get("product_id"),
                            "name": row.get("name"),
                            "retail_price": _to_float(row.get("retail_price")),
                            "cost_price": _to_float(row.get("cost_price")),
                        }
                        for row in db_product_rows
                    ],
                    ensure_ascii=False,
                )

        # === GraphRAG 增强 ===
        graph_context = ""
        try:
            from src.db import neo4j as neo4j_db
            from src.skills.neo4j_skill import Neo4jSkill

            driver = neo4j_db.get_driver()
            skill = Neo4jSkill(driver=driver)
            scenario_bundles = await skill.get_scenario_bundles(limit=15)
            if scenario_bundles:
                graph_context = (
                    "\n\n# 图谱场景组合推荐\n"
                    f"{json.dumps(scenario_bundles, ensure_ascii=False)}"
                )
        except Exception:
            graph_context = ""
        if graph_context:
            orders_summary = f"{orders_summary}{graph_context}"

        prompt = order_mining_prompt(
            orders_summary=orders_summary,
            fp_growth_config=state.get("fp_growth_config", DEFAULT_FP_CONFIG),
        )
        result = await call_tool(prompt, ASSOCIATION_RULES_TOOL, model=MODEL_PRO)
        return {
            "association_rules": result,
            "db_association_pairs": db_association_pairs,
            "db_product_catalog": _build_catalog_index(db_product_rows),
            "product_details": product_details,
            "product_costs": product_costs,
        }
    except Exception as e:
        logger.error(f"Order mining failed: {e}")
        return {"errors": state.get("errors", []) + [f"order_mining: {e}"]}


async def scene_design_node(state: BundleState) -> dict:
    """Scene Sub-Agent: 场景理解 + 套餐命名"""
    try:
        month = datetime.utcnow().month
        season_tag = _season_tag_for_month(month)
        seasonality_context: list[dict[str, Any]] = []
        product_details = state.get("product_details", "暂无数据")
        pool = state.get("db_pool")
        association_pairs = state.get("db_association_pairs", [])

        if pool:
            names = sorted(
                {
                    str(pair.get("product_a") or "").strip()
                    for pair in association_pairs
                }
                | {
                    str(pair.get("product_b") or "").strip()
                    for pair in association_pairs
                }
            )
            names = [name for name in names if name]
            seasonality_context = await _fetch_seasonality_context(pool, month, names)
            if seasonality_context:
                product_details = (
                    f"{product_details}\n\n"
                    f"当前月份={month}，当前季节={season_tag}。"
                    "请优先从以下应季商品中构建套餐：\n"
                    f"{json.dumps(seasonality_context, ensure_ascii=False)}"
                )

        prompt = scene_design_prompt(
            association_rules=json.dumps(state.get("association_rules", {}), ensure_ascii=False),
            product_details=product_details,
        )
        result = await call_tool(prompt, BUNDLE_PROPOSALS_TOOL, model=MODEL_DEEPSEEK)
        return {"bundle_proposals": result, "db_seasonality": seasonality_context}
    except Exception as e:
        logger.error(f"Scene design failed: {e}")
        return {"errors": state.get("errors", []) + [f"scene_design: {e}"]}


async def pricing_node(state: BundleState) -> dict:
    """Pricing Sub-Agent: 套餐定价"""
    proposals = state.get("bundle_proposals", {})
    bundles = proposals.get("bundles", [])
    rules = state.get("association_rules", {}).get("rules", [])
    pool = state.get("db_pool")

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
            catalog = state.get("db_product_catalog", {})
            matched_products: list[dict[str, Any]] = []
            retail_total = 0.0
            cost_total = 0.0

            for product in bundle.get("products", []):
                matched = _lookup_product(catalog, product) or {}
                fallback_price = _to_float(product.get("unit_price"))
                retail_price = _to_float(matched.get("retail_price")) or fallback_price
                cost_price = _to_float(matched.get("cost_price"))
                retail_total += retail_price
                cost_total += cost_price
                matched_products.append(
                    {
                        "product_id": matched.get("product_id") or product.get("product_id"),
                        "name": matched.get("name") or product.get("name"),
                        "retail_price": round(retail_price, 2),
                        "cost_price": round(cost_price, 2),
                    }
                )

            cost_context = json.dumps(
                {
                    "products": matched_products,
                    "derived_totals": {
                        "retail_total": round(retail_total, 2),
                        "cost_total": round(cost_total, 2),
                    },
                },
                ensure_ascii=False,
            )

            prompt = pricing_prompt(
                bundle_proposal=json.dumps(bundle, ensure_ascii=False),
                product_costs=cost_context,
                lift_value=lift_value,
            )
            def _reflect_bundle_pricing(initial_result_str: str) -> str:
                return f"""请审查以下套餐定价建议，检查：
1. 套餐价是否高于成本总和
2. 毛利率是否合理（建议不低于25%）
3. 折扣力度是否与场景和关联强度匹配
4. 数据引用和计算是否一致

初始定价建议：
{initial_result_str}

请给出修订后的版本，如果没问题则保持不变。"""

            result = await call_tool_with_reflection(
                initial_prompt=prompt,
                reflection_prompt_fn=_reflect_bundle_pricing,
                tool=BUNDLE_PRICING_TOOL,
                model=MODEL_SONNET,
            )
            if not isinstance(result, dict):
                result = {}

            pricing = result.get("pricing", {})
            if not isinstance(pricing, dict):
                pricing = {}

            original_total = round(
                retail_total if retail_total > 0 else _to_float(pricing.get("original_total")),
                2,
            )
            llm_bundle_price = _to_float(pricing.get("bundle_price"))
            min_bundle_price = max(
                cost_total + 0.01,
                (cost_total / 0.75) if cost_total > 0 else 0.0,
            )
            target_bundle_price = llm_bundle_price if llm_bundle_price > min_bundle_price else min_bundle_price
            bundle_price = _round_marketing_price(target_bundle_price)
            if bundle_price <= cost_total and cost_total > 0:
                bundle_price = _round_marketing_price(cost_total * 1.05)

            savings_amount = max(0.0, round(original_total - bundle_price, 2))
            discount_percent = round((savings_amount / original_total * 100.0), 2) if original_total > 0 else 0.0
            gross_margin_percent = (
                round(((bundle_price - cost_total) / bundle_price * 100.0), 2) if bundle_price > 0 else 0.0
            )
            approved = gross_margin_percent >= 25.0 and bundle_price > cost_total

            result["bundle_id"] = result.get("bundle_id") or bundle_id
            result["pricing"] = {
                "original_total": original_total,
                "bundle_price": bundle_price,
                "discount_percent": discount_percent,
                "savings_amount": savings_amount,
                "gross_margin_percent": gross_margin_percent,
            }
            result["approved"] = approved
            if not approved and not result.get("rejection_reason"):
                result["rejection_reason"] = "套餐毛利不足或套餐价未覆盖成本"

            # === 事实核查 ===
            try:
                from src.agents.fact_checker import validate_agent_output

                validation = await validate_agent_output(pool, "bundle", result)
                if not validation["valid"]:
                    result["fact_check_warnings"] = validation["warnings"]
                    result["fact_check_passed"] = False
                    logger.warning(f"Bundle pricing failed fact check: {validation['warnings']}")
                elif validation["warnings"]:
                    result["fact_check_warnings"] = validation["warnings"]
                    result["fact_check_passed"] = True
            except Exception:
                pass

            pricing_results.append(result)

            if pool:
                try:
                    from src.agents.action_tracker import record_action

                    await record_action(
                        pool=pool,
                        agent_type="bundle",
                        action_type="bundle_pricing",
                        product_id=bundle_id or None,
                        product_name=str(bundle.get("bundle_name") or bundle_id or ""),
                        decision=result if isinstance(result, dict) else {"result": result},
                        confidence=float(bundle.get("confidence_score", 0.7) or 0.7),
                        context_summary=str(bundle.get("target_scenario") or "")[:300],
                        baseline_metrics={
                            "retail_total": round(retail_total, 2),
                            "cost_total": round(cost_total, 2),
                            "lift_value": lift_value,
                        },
                    )
                except Exception as e:
                    logger.warning("Failed to record bundle action for %s: %s", bundle_id, e)
        except Exception as e:
            logger.error(f"Pricing failed for bundle {bundle_id}: {e}")
            errors.append(f"pricing_{bundle_id}: {e}")

    return {"bundle_pricing": pricing_results, "errors": errors}
