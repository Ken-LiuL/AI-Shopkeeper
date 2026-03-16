"""
test_business_advisor.py — 经营建议 Agent (BusinessAdvisor) 评估

评估目标：
  1. 数据引用是否准确（建议中的数字与已知数据一致）
  2. 建议是否可操作（包含具体行动步骤）
  3. 是否有自相矛盾（同一回复内逻辑冲突检测）

技术约束：
  - 全 mock，无需真实 LLM / 数据库
  - 重点验证回复的结构化质量
"""

from __future__ import annotations

import re
from typing import Any

from tests.eval.eval_metrics import check_output_format, check_text_constraints, check_value_in_range

# ---------------------------------------------------------------------------
# Mock 经营建议输出构造器
# ---------------------------------------------------------------------------

VALID_INTENTS = {
    "sales_analysis", "inventory_advice", "pricing_strategy",
    "competitor_analysis", "product_recommendation", "general_advice",
}

VALID_SOURCES = {"database", "market_data", "competitor_data", "historical_data"}


def _make_advisor_reply(
    reply: str = "根据最近30天数据，您的血压计销量下降15%，建议：1）优化商品图片 2）参与平台活动 3）调整价格至180元以提升竞争力。",
    intent: str = "sales_analysis",
    sources: list[dict] | None = None,
    needs_human: bool = False,
    data_citations: list[dict] | None = None,
) -> dict[str, Any]:
    """构造经营建议回复 mock。"""
    return {
        "reply": reply,
        "intent": intent,
        "sources": sources or [
            {"type": "database", "description": "30天销售数据", "confidence": 0.9},
        ],
        "needs_human": needs_human,
        "data_citations": data_citations or [
            {"metric": "sales_volume", "value": "下降15%", "period": "30天"},
        ],
        "actionable_steps": _extract_steps(reply),
        "result": {"status": "success", "summary": "提供了销售分析建议"},
    }


def _extract_steps(text: str) -> list[str]:
    """从回复文本中提取编号步骤。"""
    # 匹配 "1）" "2）" 或 "1." "2." 形式的步骤
    steps = re.findall(r"[1-9][）\.\)]\s*(.+?)(?=[1-9][）\.\)]|$)", text)
    return [s.strip() for s in steps if s.strip()]


def _make_contradictory_reply() -> dict[str, Any]:
    """构造一个自相矛盾的建议 mock（用于测试矛盾检测）。"""
    return _make_advisor_reply(
        reply="建议涨价至300元以提升利润。同时，建议降价至150元以提升销量。",
        data_citations=[
            {"metric": "price", "value": "涨至300元", "period": ""},
            {"metric": "price", "value": "降至150元", "period": ""},
        ],
    )


# ---------------------------------------------------------------------------
# 数据引用准确性
# ---------------------------------------------------------------------------


class TestDataCitationAccuracy:
    """验证经营建议中数据引用的准确性。"""

    def test_reply_has_data_citations(self):
        """经营建议应包含数据引用。"""
        reply = _make_advisor_reply()
        assert len(reply.get("data_citations", [])) > 0, "经营建议应有数据引用"

    def test_citation_has_required_fields(self):
        """每条数据引用应包含 metric 和 value。"""
        reply = _make_advisor_reply()
        for citation in reply["data_citations"]:
            result = check_output_format(citation, required_keys=["metric", "value"])
            assert result["valid"], f"数据引用缺少字段: {result['missing_keys']}"

    def test_sources_are_valid(self):
        """数据来源应是已知类型。"""
        reply = _make_advisor_reply()
        for source in reply["sources"]:
            assert source["type"] in VALID_SOURCES, f"未知数据来源类型: {source['type']!r}"

    def test_source_confidence_in_range(self):
        """数据来源置信度应在 [0, 1]。"""
        reply = _make_advisor_reply()
        for source in reply["sources"]:
            if "confidence" in source:
                chk = check_value_in_range(source["confidence"], 0.0, 1.0, label="source.confidence")
                assert chk["valid"], chk["message"]

    def test_percentage_values_in_reply_are_valid(self):
        """回复中出现的百分比应在合理范围内 (<200%)。"""
        reply_text = "您的血压计销量下降15%，毛利率为35%"
        percentages = [float(m) for m in re.findall(r"(\d+(?:\.\d+)?)%", reply_text)]
        for pct in percentages:
            assert pct < 200, f"百分比 {pct}% 超出合理范围"

    def test_data_in_reply_consistent_with_citation(self):
        """
        回复文本中的数字应与 data_citations 中的值一致。
        （简化版：验证 citation 中的 value 出现在回复中）
        """
        reply = _make_advisor_reply(
            reply="根据30天数据，销量下降15%，建议调整策略。",
            data_citations=[{"metric": "sales_volume", "value": "下降15%", "period": "30天"}],
        )
        for citation in reply["data_citations"]:
            value_str = citation["value"]
            # 提取数字部分验证
            numbers = re.findall(r"\d+", value_str)
            for num in numbers:
                assert num in reply["reply"], (
                    f"引用数据 {value_str!r} 中的 {num!r} 未在回复中体现"
                )

    def test_reply_output_format(self):
        """回复输出应包含必要字段。"""
        reply = _make_advisor_reply()
        result = check_output_format(
            reply, required_keys=["reply", "intent", "sources", "needs_human"]
        )
        assert result["valid"], f"回复输出缺少字段: {result['missing_keys']}"


# ---------------------------------------------------------------------------
# 建议可操作性
# ---------------------------------------------------------------------------


class TestActionability:
    """验证经营建议的可操作性。"""

    def test_reply_contains_actionable_steps(self):
        """回复应包含具体可执行步骤。"""
        reply = _make_advisor_reply()
        steps = reply.get("actionable_steps", [])
        assert len(steps) >= 1, f"经营建议应包含至少 1 个可操作步骤，实际: {steps}"

    def test_steps_are_not_empty(self):
        """每个步骤应有实质内容，不为空。"""
        reply = _make_advisor_reply()
        for step in reply.get("actionable_steps", []):
            assert step.strip(), f"存在空步骤: {step!r}"

    def test_reply_has_concrete_action_verbs(self):
        """回复应包含动作动词（调整、优化、参与、下架等）。"""
        action_verbs = ["调整", "优化", "参与", "降价", "涨价", "补货", "下架", "促销", "联系"]
        reply_text = _make_advisor_reply()["reply"]
        found = [v for v in action_verbs if v in reply_text]
        assert len(found) >= 1, f"回复缺少具体动作动词，当前: {reply_text[:100]}"

    def test_reply_not_too_short(self):
        """经营建议回复长度应 >= 30 字符。"""
        reply = _make_advisor_reply()
        result = check_text_constraints(reply["reply"], min_len=30)
        assert result["valid"], f"回复过短: {result['issues']}"

    def test_intent_is_valid(self):
        """intent 应在合法集合中。"""
        reply = _make_advisor_reply()
        assert reply["intent"] in VALID_INTENTS, f"非法 intent: {reply['intent']!r}"

    def test_general_advice_still_has_steps(self):
        """即使是通用建议，也应有可操作步骤。"""
        reply = _make_advisor_reply(
            reply="建议您：1）定期分析销售数据 2）关注竞品动态 3）优化库存结构",
            intent="general_advice",
        )
        assert len(reply["actionable_steps"]) >= 2


# ---------------------------------------------------------------------------
# 自相矛盾检测
# ---------------------------------------------------------------------------


class TestContradictionDetection:
    """验证回复中是否存在自相矛盾。"""

    def _has_price_contradiction(self, reply_text: str) -> bool:
        """
        简单规则：同一回复中同时建议"涨价"和"降价"，则视为矛盾。
        """
        has_increase = any(w in reply_text for w in ["涨价", "提高价格", "调高价格"])
        has_decrease = any(w in reply_text for w in ["降价", "降低价格", "调低价格"])
        return has_increase and has_decrease

    def _has_stock_contradiction(self, reply_text: str) -> bool:
        """同一回复中同时建议"补货"和"清仓"，则视为矛盾。"""
        has_restock = any(w in reply_text for w in ["补货", "增加库存", "备货"])
        has_clearance = any(w in reply_text for w in ["清仓", "减少库存", "下架"])
        return has_restock and has_clearance

    def test_non_contradictory_reply_passes(self):
        """正常回复不应触发矛盾检测。"""
        reply = _make_advisor_reply()
        assert not self._has_price_contradiction(reply["reply"]), "正常回复不应有价格矛盾"

    def test_contradictory_price_advice_detected(self):
        """同时建议涨价和降价的回复，应被检测为矛盾。"""
        bad_reply = _make_contradictory_reply()
        assert self._has_price_contradiction(bad_reply["reply"]), (
            "涨价+降价矛盾应被检测"
        )

    def test_consistent_stock_advice(self):
        """仅建议补货或仅建议清仓，不构成矛盾。"""
        restock_reply = _make_advisor_reply(
            reply="建议补货50件，当前库存偏低，预计3天售罄。"
        )
        assert not self._has_stock_contradiction(restock_reply["reply"])

    def test_contradictory_stock_advice_detected(self):
        """同时建议补货和清仓，应被检测为矛盾。"""
        contradiction = "建议立即补货200件。同时，库存积压严重，建议清仓处理。"
        assert self._has_stock_contradiction(contradiction)

    def test_citation_value_not_contradictory(self):
        """data_citations 中的数值不应自相矛盾（同一指标出现两个相反的值）。"""
        bad_reply = _make_contradictory_reply()
        citations = bad_reply.get("data_citations", [])
        price_citations = [c for c in citations if c["metric"] == "price"]
        # 两条 price citation 存在时，应检测矛盾
        if len(price_citations) >= 2:
            values = [c["value"] for c in price_citations]
            assert len(set(values)) > 1, "两条相同指标引用应有不同值（矛盾场景）"

    def test_reply_logic_direction_consistent(self):
        """
        建议的逻辑方向应一致：
        如果分析结论是"销量下降"，则建议应是促销/降价/优化，而非涨价。
        """
        reply_text = "销量下降15%。建议：1）降价促销 2）优化商品图片 3）参与平台活动。"
        # 分析结论：下降
        has_decline_context = "下降" in reply_text
        # 建议方向：促销/降价（合理）
        has_promotion = "促销" in reply_text or "降价" in reply_text
        # 确保没有反向建议（涨价）
        has_increase = "涨价" in reply_text

        assert has_decline_context and has_promotion and not has_increase, (
            "在销量下降背景下，不应建议涨价"
        )
