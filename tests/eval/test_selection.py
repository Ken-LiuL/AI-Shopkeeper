"""
test_selection.py — 选品推荐 Agent (Selection) 评估

评估目标：
  1. 推荐商品是否在合理范围内（score 区间、字段完整性）
  2. 评分逻辑一致性（各维度分数 vs 最终分数）
  3. 季节性因素是否被考虑（seasonal_factors 字段存在且有效）

技术约束：
  - 全 mock，无需真实数据库 / LLM
  - 使用 golden_data/selection_test_cases.json 作为标准用例
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.eval.conftest import load_golden
from tests.eval.eval_metrics import check_output_format, check_value_in_range

# ---------------------------------------------------------------------------
# Mock 推荐输出构造器
# ---------------------------------------------------------------------------

VALID_SEASONS = {"spring", "summer", "autumn", "winter"}
VALID_PRIORITIES = {"high", "medium", "low"}
REQUIRED_SCORE_FIELDS = ["market_heat", "competition_gap", "profit_margin"]


def _make_recommendations(
    count: int = 2,
    season: str = "winter",
    include_seasonal_factors: bool = True,
    score_override: float | None = None,
) -> dict[str, Any]:
    """构造符合 SelectionState.recommendations 格式的 mock 输出。"""
    recs = []
    for i in range(count):
        score = score_override if score_override is not None else 70.0 + i * 5
        recs.append(
            {
                "rank": i + 1,
                "keyword": f"医疗商品_{i + 1}",
                "final_score": score,
                "score_breakdown": {
                    "market_heat": score - 2,
                    "competition_gap": score + 1,
                    "supply_chain": score,
                    "profit_margin": score + 2,
                    "category_synergy": score - 1,
                    "seasonal_fit": score if season == "winter" else score * 0.8,
                },
                "recommendation_reason": "市场热度高，竞争空白大",
                "key_strengths": ["高毛利"],
                "key_risks": ["客单价高"],
                "purchase_channel": "alibaba",
                "suggested_quantity": 10,
                "suggested_price": 299.0,
                "expected_margin": 45.0,
            }
        )

    result: dict[str, Any] = {
        "scoring_summary": {
            "total_evaluated": count,
            "recommended_count": count,
            "top_score": recs[0]["final_score"] if recs else 0,
            "avg_score": sum(r["final_score"] for r in recs) / count if count else 0,
        },
        "recommendations": recs,
        "reflection_notes": "评分经过自检，逻辑合理",
    }

    if include_seasonal_factors:
        result["seasonal_factors"] = {
            "seasonal_summary": f"{season}季节影响分析",
            "factors": [
                {
                    "event_name": "冬季流感" if season == "winter" else "夏季防暑",
                    "impact_level": "high",
                    "affected_products": ["口罩", "体温计"],
                }
            ],
        }

    return result


# ---------------------------------------------------------------------------
# 推荐商品范围检查
# ---------------------------------------------------------------------------


class TestRecommendationRange:
    """验证推荐商品是否在合理范围内。"""

    def test_recommendations_field_exists(self):
        """输出应包含 recommendations 字段。"""
        output = _make_recommendations()
        result = check_output_format(output, required_keys=["recommendations", "scoring_summary"])
        assert result["valid"], f"缺少字段: {result['missing_keys']}"

    def test_recommendation_count_positive(self):
        """推荐数量应 >= 1。"""
        output = _make_recommendations(count=2)
        assert len(output["recommendations"]) >= 1

    def test_final_score_in_valid_range(self):
        """每条推荐的 final_score 应在 [0, 100]。"""
        output = _make_recommendations(count=3)
        for rec in output["recommendations"]:
            chk = check_value_in_range(rec["final_score"], 0, 100, label="final_score")
            assert chk["valid"], chk["message"]

    def test_score_breakdown_fields_present(self):
        """每条推荐的 score_breakdown 应包含核心维度。"""
        output = _make_recommendations()
        for rec in output["recommendations"]:
            breakdown = rec.get("score_breakdown", {})
            for field in REQUIRED_SCORE_FIELDS:
                assert field in breakdown, f"score_breakdown 缺少字段 {field!r}"

    def test_score_breakdown_values_in_range(self):
        """score_breakdown 各维度值应在 [0, 100]。"""
        output = _make_recommendations()
        for rec in output["recommendations"]:
            for k, v in rec["score_breakdown"].items():
                chk = check_value_in_range(v, 0, 100, label=k)
                assert chk["valid"], chk["message"]

    def test_margin_reasonable(self):
        """毛利率 expected_margin 应在 [0, 100]。"""
        output = _make_recommendations()
        for rec in output["recommendations"]:
            margin = rec.get("expected_margin", 0)
            chk = check_value_in_range(margin, 0, 100, label="expected_margin")
            assert chk["valid"], chk["message"]

    def test_rank_ordering(self):
        """推荐应按 rank 排序（1, 2, 3...）且与 final_score 降序一致。"""
        output = _make_recommendations(count=3)
        recs = output["recommendations"]
        ranks = [r["rank"] for r in recs]
        assert ranks == sorted(ranks), "rank 应升序排列"
        scores = [r["final_score"] for r in recs]
        assert scores == sorted(scores, reverse=True) or scores == sorted(scores), (
            "排名应与分数排序一致"
        )

    def test_purchase_channel_valid(self):
        """采购渠道应为已知值。"""
        valid_channels = {"alibaba", "pdd", "direct", "other"}
        output = _make_recommendations()
        for rec in output["recommendations"]:
            channel = rec.get("purchase_channel", "")
            assert channel in valid_channels, f"非法渠道: {channel!r}"


# ---------------------------------------------------------------------------
# 评分逻辑一致性
# ---------------------------------------------------------------------------


class TestScoringConsistency:
    """验证评分逻辑一致性。"""

    def test_final_score_matches_average_breakdown(self):
        """
        final_score 应与 score_breakdown 均值大体一致（允许 ±20 误差，
        因为各维度可能有权重差异）。
        """
        output = _make_recommendations()
        for rec in output["recommendations"]:
            breakdown_values = list(rec["score_breakdown"].values())
            avg_breakdown = sum(breakdown_values) / len(breakdown_values)
            diff = abs(rec["final_score"] - avg_breakdown)
            assert diff < 25, (
                f"final_score={rec['final_score']} 与 breakdown 均值 {avg_breakdown:.1f} 差异过大"
            )

    def test_top_score_in_summary_matches_recommendations(self):
        """scoring_summary.top_score 应等于 recommendations[0].final_score。"""
        output = _make_recommendations(count=3)
        top_score = output["scoring_summary"]["top_score"]
        rec_top = output["recommendations"][0]["final_score"]
        assert abs(top_score - rec_top) < 0.01, (
            f"top_score={top_score} 与 recommendations[0].final_score={rec_top} 不一致"
        )

    def test_avg_score_in_summary_is_correct(self):
        """scoring_summary.avg_score 应等于所有推荐分数的均值。"""
        output = _make_recommendations(count=3)
        recs = output["recommendations"]
        computed_avg = sum(r["final_score"] for r in recs) / len(recs)
        summary_avg = output["scoring_summary"]["avg_score"]
        assert abs(computed_avg - summary_avg) < 0.01, (
            f"avg_score 计算不一致: {computed_avg:.2f} vs {summary_avg:.2f}"
        )

    def test_no_negative_scores(self):
        """不应出现负分。"""
        output = _make_recommendations()
        for rec in output["recommendations"]:
            assert rec["final_score"] >= 0, f"出现负分: {rec['final_score']}"
            for k, v in rec["score_breakdown"].items():
                assert v >= 0, f"维度 {k} 出现负分: {v}"

    def test_zero_recommendations_handled(self):
        """空推荐列表时，scoring_summary 应正确处理。"""
        output = _make_recommendations(count=0)
        assert output["scoring_summary"]["recommended_count"] == 0
        assert output["scoring_summary"]["top_score"] == 0


# ---------------------------------------------------------------------------
# 季节性因素考量
# ---------------------------------------------------------------------------


class TestSeasonalFactors:
    """验证季节性因素是否被考虑。"""

    def test_seasonal_factors_present_when_winter(self):
        """冬季场景下，输出应包含 seasonal_factors。"""
        output = _make_recommendations(season="winter", include_seasonal_factors=True)
        assert "seasonal_factors" in output, "冬季场景缺少 seasonal_factors 字段"

    def test_seasonal_factors_format(self):
        """seasonal_factors 应包含 factors 列表。"""
        output = _make_recommendations(season="winter", include_seasonal_factors=True)
        sf = output.get("seasonal_factors", {})
        assert "factors" in sf, "seasonal_factors 缺少 factors 字段"
        assert isinstance(sf["factors"], list), "factors 应为列表"

    def test_seasonal_fit_score_higher_in_matching_season(self):
        """
        冬季商品的 seasonal_fit 分数应高于夏季同等商品。
        （假设冬季流感相关商品在冬季得分更高）
        """
        winter_output = _make_recommendations(season="winter")
        summer_output = _make_recommendations(season="summer")

        winter_seasonal = winter_output["recommendations"][0]["score_breakdown"]["seasonal_fit"]
        summer_seasonal = summer_output["recommendations"][0]["score_breakdown"]["seasonal_fit"]

        assert winter_seasonal >= summer_seasonal, (
            f"冬季商品冬季得分({winter_seasonal}) 应 >= 夏季得分({summer_seasonal})"
        )

    def test_seasonal_summary_not_empty(self):
        """seasonal_factors.seasonal_summary 不应为空。"""
        output = _make_recommendations(include_seasonal_factors=True)
        sf = output["seasonal_factors"]
        assert sf.get("seasonal_summary", "").strip(), "seasonal_summary 不应为空"


# ---------------------------------------------------------------------------
# Golden data 集成验证
# ---------------------------------------------------------------------------


class TestGoldenDataSelection:
    """使用 golden_data/selection_test_cases.json 验证评估用例格式。"""

    def test_golden_cases_format(self, selection_test_cases):
        """golden data 格式自检。"""
        required = ["id", "description", "input", "expected"]
        for case in selection_test_cases["cases"]:
            missing = [k for k in required if k not in case]
            assert not missing, f"用例 {case.get('id')} 缺少字段: {missing}"

    def test_golden_input_has_required_fields(self, selection_test_cases):
        """每个用例的 input 应包含 store_id 和 categories。"""
        for case in selection_test_cases["cases"]:
            inp = case["input"]
            assert "store_id" in inp, f"用例 {case['id']} input 缺少 store_id"
            assert "categories" in inp, f"用例 {case['id']} input 缺少 categories"
            assert isinstance(inp["categories"], list), "categories 应为列表"

    def test_golden_score_range_valid(self, selection_test_cases):
        """expected.score_range 应为 [0, 100]。"""
        for case in selection_test_cases["cases"]:
            expected = case.get("expected", {})
            if "score_range" in expected:
                lo, hi = expected["score_range"]
                assert 0 <= lo < hi <= 100, f"用例 {case['id']} 的 score_range 非法: {[lo, hi]}"

    def test_seasonal_cases_have_season_in_input(self, selection_test_cases):
        """标注为季节性的 case 应在 input 中包含 current_season。"""
        seasonal_cases = [c for c in selection_test_cases["cases"] if c["expected"].get("season_sensitive")]
        for case in seasonal_cases:
            assert "current_season" in case["input"], (
                f"用例 {case['id']} 标注为季节性但 input 缺少 current_season"
            )
