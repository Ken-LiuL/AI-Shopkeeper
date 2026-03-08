"""
事实核查模块 — 验证 Agent 输出是否与数据库一致。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def check_price_recommendation(pool, product_id: str, recommended_price: float) -> dict[str, Any]:
    """核查价格建议是否合理。"""
    checks: dict[str, Any] = {"passed": True, "warnings": []}

    if not pool:
        checks["warnings"].append("数据库连接不可用，跳过价格核查")
        return checks

    try:
        row = await pool.fetchrow(
            "SELECT retail_price, cost_price, stock FROM qnh_products WHERE spu_id = $1",
            product_id,
        )
        if not row:
            checks["warnings"].append(f"商品 {product_id} 不在数据库中")
            return checks

        cost = float(row["cost_price"]) if row["cost_price"] else None
        current = float(row["retail_price"]) if row["retail_price"] else None

        if cost and recommended_price < cost:
            checks["passed"] = False
            checks["warnings"].append(f"建议价 ¥{recommended_price} 低于成本价 ¥{cost}")

        if cost and recommended_price < cost * 1.1:
            checks["warnings"].append(f"建议价 ¥{recommended_price} 毛利率低于10%（成本 ¥{cost}）")

        if current and current > 0 and abs(recommended_price - current) / current > 0.3:
            pct = abs(recommended_price - current) / current * 100
            checks["warnings"].append(f"调价幅度 {pct:.0f}% 超过30%（当前 ¥{current}）")

        if recommended_price <= 0:
            checks["passed"] = False
            checks["warnings"].append("建议价为负数或零")

    except Exception as e:
        logger.warning(f"Fact check failed: {e}")

    return checks


async def check_stock_recommendation(pool, product_id: str, recommended_qty: int) -> dict[str, Any]:
    """核查补货建议是否合理。"""
    checks: dict[str, Any] = {"passed": True, "warnings": []}

    if not pool:
        checks["warnings"].append("数据库连接不可用，跳过库存核查")
        return checks

    try:
        row = await pool.fetchrow(
            "SELECT stock, title FROM qnh_products WHERE spu_id = $1",
            product_id,
        )
        if not row:
            return checks

        current_stock = row["stock"] or 0

        if recommended_qty > 1000:
            checks["warnings"].append(f"补货量 {recommended_qty} 异常大（当前库存 {current_stock}）")

        if current_stock > 100 and recommended_qty > 0:
            checks["warnings"].append(f"当前库存 {current_stock} 充足，建议谨慎补货")

    except Exception as e:
        logger.warning(f"Stock fact check failed: {e}")

    return checks


async def validate_agent_output(pool, agent_type: str, output: dict[str, Any]) -> dict[str, Any]:
    """统一的 Agent 输出验证入口。"""
    validation: dict[str, Any] = {"valid": True, "checks": [], "warnings": []}

    try:
        if agent_type == "alert":
            # 兼容 action output 的不同结构:
            # 1) {"actions": [...]} 2) {"recommended_actions": [...]}
            actions = output.get("actions", [])
            if not actions and "recommended_actions" in output:
                actions = output.get("recommended_actions", [])

            for action in actions:
                action_type = action.get("action_type")
                params = action.get("parameters", {}) if isinstance(action.get("parameters"), dict) else {}
                product_id = action.get("product_id") or output.get("product_id")

                if action_type == "price_adjust":
                    target_price = action.get("target_price")
                    if target_price is None:
                        target_price = params.get("target_price")
                    if target_price is not None and product_id:
                        check = await check_price_recommendation(pool, str(product_id), float(target_price))
                        if not check["passed"]:
                            validation["valid"] = False
                        validation["warnings"].extend(check["warnings"])

                elif action_type == "restock":
                    qty = action.get("quantity")
                    if qty is None:
                        qty = params.get("restock_quantity")
                    if qty is not None and product_id:
                        check = await check_stock_recommendation(pool, str(product_id), int(qty))
                        if not check["passed"]:
                            validation["valid"] = False
                        validation["warnings"].extend(check["warnings"])

        elif agent_type == "bundle":
            # 兼容 pricing 输出:
            # 1) {"proposals":[{"suggested_price":...}]}
            # 2) {"pricing":{"bundle_price":...}} or {"bundle_price":...}
            proposals = output.get("proposals", [])
            if proposals:
                for proposal in proposals:
                    price = proposal.get("suggested_price")
                    if price is not None and float(price) <= 0:
                        validation["valid"] = False
                        validation["warnings"].append(f"套餐价格为 {price}，不合理")
            else:
                pricing = output.get("pricing", {})
                price = None
                if isinstance(pricing, dict):
                    price = pricing.get("bundle_price") or pricing.get("suggested_price")
                if price is None:
                    price = output.get("bundle_price") or output.get("suggested_price")
                if price is not None and float(price) <= 0:
                    validation["valid"] = False
                    validation["warnings"].append(f"套餐价格为 {price}，不合理")

    except Exception as e:
        logger.warning(f"Validation failed: {e}")

    return validation
