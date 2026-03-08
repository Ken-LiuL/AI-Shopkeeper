"""
test_bundle.py — 套餐 Agent (Bundle) 评估

评估目标：
  1. 商品组合是否合理（品类关联性、组合数量）
  2. 定价是否在合理区间（折扣率、毛利率）
  3. 是否考虑了关联购买数据（association_rules 存在且有效）

技术约束：
  - 全 mock，无需真实数据库 / LLM
  - 套餐定价逻辑基于成本价和市场价验证
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.eval.eval_metrics import check_output_format, check_value_in_range

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 合理折扣范围：5%~30%
MIN_DISCOUNT_RATE = 0.05
MAX_DISCOUNT_RATE = 0.30

# 最低毛利率要求
MIN_GROSS_MARGIN = 0.10

# 套餐商品数量范围
MIN_BUNDLE_ITEMS = 2
MAX_BUNDLE_ITEMS = 6


# ---------------------------------------------------------------------------
# Mock 套餐数据构造器
# ---------------------------------------------------------------------------


def _make_bundle_proposal(
    name: str = "血压健康套餐",
    items: list[dict] | None = None,
    bundle_price: float = 220.0,
    total_cost: float = 130.0,
    total_retail: float = 260.0,
    include_association: bool = True,
    confidence: float = 0.75,
) -> dict[str, Any]:
    """构造套餐提案 mock。"""
    if items is None:
        items = [
            {"product_id": "P100", "name": "鱼跃血压计", "retail_price": 189.0, "cost_price": 95.0},
            {"product_id": "P101", "name": "血压计臂带", "retail_price": 39.0, "cost_price": 20.0},
            {"product_id": "P102", "name": "家用血压记录本", "retail_price": 15.0, "cost_price": 5.0},
        ]

    discount_rate = (total_retail - bundle_price) / total_retail if total_retail > 0 else 0
    gross_margin = (bundle_price - total_cost) / bundle_price if bundle_price > 0 else 0

    proposal: dict[str, Any] = {
        "bundle_name": name,
        "scene": "居家血压管理",
        "items": items,
        "bundle_price": bundle_price,
        "total_retail_price": total_retail,
        "total_cost": total_cost,
        "discount_rate": round(discount_rate, 4),
        "gross_margin": round(gross_margin, 4),
        "confidence_score": confidence,
        "reason": "血压计与臂带高频关联购买",
    }

    if include_association:
        proposal["association_rule"] = {
            "antecedent": ["鱼跃血压计"],
            "consequent": ["血压计臂带"],
            "support": 0.15,
            "confidence": 0.62,
            "lift": 3.2,
        }

    return proposal


def _make_bundle_output(count: int = 2) -> dict[str, Any]:
    """构造完整的套餐 Agent 输出 mock。"""
    proposals = [
        _make_bundle_proposal(
            name=f"套餐_{i + 1}",
            bundle_price=200.0 + i * 30,
            total_cost=120.0 + i * 15,
            total_retail=250.0 + i * 30,
        )
        for i in range(count)
    ]
    return {
        "bundle_proposals": {
            "total_bundles": count,
            "proposals": proposals,
        },
        "association_rules": {
            "total_rules": 5,
            "top_rules": [
                {"antecedent": ["血压计"], "consequent": ["臂带"], "lift": 3.2},
            ],
        },
        "bundle_pricing": [
            {
                "bundle_name": p["bundle_name"],
                "bundle_price": p["bundle_price"],
                "gross_margin": p["gross_margin"],
                "discount_rate": p["discount_rate"],
            }
            for p in proposals
        ],
    }


# ---------------------------------------------------------------------------
# 商品组合合理性
# ---------------------------------------------------------------------------


class TestBundleComposition:
    """验证套餐商品组合是否合理。"""

    def test_bundle_item_count_in_range(self):
        """套餐商品数量应在 [2, 6] 范围内。"""
        proposal = _make_bundle_proposal()
        item_count = len(proposal["items"])
        chk = check_value_in_range(item_count, MIN_BUNDLE_ITEMS, MAX_BUNDLE_ITEMS, label="item_count")
        assert chk["valid"], chk["message"]

    def test_bundle_has_required_fields(self):
        """套餐提案应包含必要字段。"""
        proposal = _make_bundle_proposal()
        result = check_output_format(
            proposal,
            required_keys=["bundle_name", "items", "bundle_price", "total_cost", "gross_margin"],
        )
        assert result["valid"], f"套餐提案缺少字段: {result['missing_keys']}"

    def test_each_item_has_product_id(self):
        """每个套餐商品应有 product_id。"""
        proposal = _make_bundle_proposal()
        for item in proposal["items"]:
            assert "product_id" in item, f"商品缺少 product_id: {item}"

    def test_no_duplicate_products_in_bundle(self):
        """套餐中不应有重复商品。"""
        proposal = _make_bundle_proposal()
        ids = [item["product_id"] for item in proposal["items"]]
        assert len(ids) == len(set(ids)), f"套餐中有重复商品: {ids}"

    def test_bundle_reason_not_empty(self):
        """套餐组合理由不应为空。"""
        proposal = _make_bundle_proposal()
        assert proposal.get("reason", "").strip(), "套餐 reason 不应为空"

    def test_single_item_bundle_invalid(self):
        """单商品不能构成套餐。"""
        single_item = [{"product_id": "P100", "name": "血压计", "retail_price": 189.0, "cost_price": 95.0}]
        proposal = _make_bundle_proposal(items=single_item)
        item_count = len(proposal["items"])
        assert item_count < MIN_BUNDLE_ITEMS, "单商品套餐应被过滤"

    def test_output_has_bundle_proposals_and_pricing(self):
        """完整输出应包含 bundle_proposals 和 bundle_pricing。"""
        output = _make_bundle_output()
        result = check_output_format(output, required_keys=["bundle_proposals", "bundle_pricing"])
        assert result["valid"], f"套餐输出缺少字段: {result['missing_keys']}"


# ---------------------------------------------------------------------------
# 套餐定价合理性
# ---------------------------------------------------------------------------


class TestBundlePricing:
    """验证套餐定价是否在合理区间。"""

    def test_bundle_price_less_than_sum_retail(self):
        """套餐价应低于所有商品零售价之和（有折扣）。"""
        proposal = _make_bundle_proposal(bundle_price=220.0, total_retail=260.0)
        assert proposal["bundle_price"] < proposal["total_retail_price"], (
            "套餐价应低于零售总价"
        )

    def test_discount_rate_in_valid_range(self):
        """折扣率应在 [5%, 30%] 之间。"""
        proposal = _make_bundle_proposal(bundle_price=220.0, total_retail=260.0)
        discount = proposal["discount_rate"]
        chk = check_value_in_range(discount, MIN_DISCOUNT_RATE, MAX_DISCOUNT_RATE, label="discount_rate")
        assert chk["valid"], chk["message"]

    def test_bundle_price_above_cost(self):
        """套餐价必须高于成本总价（不亏本销售）。"""
        proposal = _make_bundle_proposal(bundle_price=220.0, total_cost=130.0)
        assert proposal["bundle_price"] > proposal["total_cost"], "套餐价不能低于成本"

    def test_gross_margin_above_minimum(self):
        """毛利率应高于最低要求（10%）。"""
        proposal = _make_bundle_proposal(bundle_price=220.0, total_cost=130.0)
        chk = check_value_in_range(
            proposal["gross_margin"], MIN_GROSS_MARGIN, 1.0, label="gross_margin"
        )
        assert chk["valid"], chk["message"]

    def test_zero_price_bundle_rejected(self):
        """套餐价为 0 应被检测为异常。"""
        proposal = _make_bundle_proposal(bundle_price=0.0, total_cost=130.0)
        assert proposal["bundle_price"] <= 0, "零价格应被标记"
        assert proposal["bundle_price"] <= proposal["total_cost"], "零价格低于成本，应报错"

    def test_negative_margin_detected(self):
        """毛利率为负时应被检测。"""
        proposal = _make_bundle_proposal(bundle_price=100.0, total_cost=150.0)
        assert proposal["gross_margin"] < 0, "负毛利率应被检测"

    def test_too_high_discount_detected(self):
        """折扣超过 30% 应被检测为异常折扣。"""
        proposal = _make_bundle_proposal(bundle_price=150.0, total_retail=260.0)
        # 折扣 (260-150)/260 ≈ 42%
        assert proposal["discount_rate"] > MAX_DISCOUNT_RATE, "超高折扣应被标记"

    def test_pricing_consistency(self):
        """discount_rate 计算应与 bundle_price / total_retail 一致。"""
        proposal = _make_bundle_proposal(bundle_price=220.0, total_retail=260.0)
        computed = (proposal["total_retail_price"] - proposal["bundle_price"]) / proposal["total_retail_price"]
        assert abs(computed - proposal["discount_rate"]) < 0.001, (
            f"discount_rate 不一致: 计算={computed:.4f}, 记录={proposal['discount_rate']}"
        )


# ---------------------------------------------------------------------------
# 关联购买数据考量
# ---------------------------------------------------------------------------


class TestAssociationRules:
    """验证套餐是否考虑了关联购买数据。"""

    def test_association_rule_present(self):
        """套餐提案应包含关联规则来源。"""
        proposal = _make_bundle_proposal(include_association=True)
        assert "association_rule" in proposal, "套餐应包含关联规则字段"

    def test_association_rule_format(self):
        """关联规则应包含 support / confidence / lift。"""
        proposal = _make_bundle_proposal(include_association=True)
        rule = proposal["association_rule"]
        result = check_output_format(rule, required_keys=["support", "confidence", "lift"])
        assert result["valid"], f"关联规则缺少字段: {result['missing_keys']}"

    def test_association_confidence_in_range(self):
        """关联规则 confidence 应在 [0, 1]。"""
        proposal = _make_bundle_proposal(include_association=True)
        conf = proposal["association_rule"]["confidence"]
        chk = check_value_in_range(conf, 0.0, 1.0, label="association.confidence")
        assert chk["valid"], chk["message"]

    def test_lift_above_one_means_positive_association(self):
        """lift > 1 表示正向关联（商品间有关联购买倾向）。"""
        proposal = _make_bundle_proposal(include_association=True)
        lift = proposal["association_rule"]["lift"]
        assert lift > 1.0, f"套餐商品 lift={lift} 应 > 1 才有正向关联"

    def test_output_association_rules_summary(self):
        """完整输出应包含关联规则汇总。"""
        output = _make_bundle_output()
        result = check_output_format(output, required_keys=["association_rules"])
        assert result["valid"], "输出缺少 association_rules 汇总"

    def test_bundle_without_association_flagged(self):
        """没有关联规则来源的套餐应被标注（降低置信度）。"""
        proposal = _make_bundle_proposal(include_association=False, confidence=0.3)
        assert "association_rule" not in proposal
        assert proposal["confidence_score"] < 0.5, "无关联规则的套餐置信度应较低"
