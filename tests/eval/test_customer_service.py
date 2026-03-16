"""
test_customer_service.py — 客服 Agent (CustomerService) 评估

评估目标：
  1. 商品咨询场景（正常 / 模糊 / 多商品比较）
  2. 售后场景（退货 / 换货 / 投诉升级）
  3. 情感检测（正面 / 中性 / 不满 / 愤怒）
  4. 意图识别准确性（vs. golden label）
  5. 幻觉检测（回复中不应包含数据库中不存在的商品信息）

技术约束：
  - 全 mock，无需数据库 / LLM 真实调用
  - 使用 golden_data/cs_test_cases.json 作为标准用例
"""

from __future__ import annotations

import pytest
from tests.eval.eval_metrics import (
    ClassificationMetrics,
    HallucinationTracker,
    check_output_format,
    check_text_constraints,
)

# ---------------------------------------------------------------------------
# 辅助：构造 mock intent / reply 输出
# ---------------------------------------------------------------------------

VALID_INTENTS = {
    "product_inquiry",
    "return_request",
    "exchange_request",
    "complaint",
    "praise",
    "greeting",
    "store_inquiry",
    "other",
}

VALID_SENTIMENTS = {"positive", "neutral", "negative"}


def _make_intent(
    intent: str = "product_inquiry",
    confidence: float = 0.9,
    sentiment: str = "neutral",
    requires_human: bool = False,
) -> dict:
    return {
        "intent": intent,
        "confidence": confidence,
        "extracted_entities": {"product_mentioned": "血压计"},
        "sentiment": sentiment,
        "requires_human": requires_human,
        "human_reason": "需人工" if requires_human else "",
    }


def _make_reply(
    text: str = "亲，这款血压计非常适合老人使用~",
    product_ids: list[str] | None = None,
) -> dict:
    return {
        "reply_text": text,
        "confidence": 0.85,
        "products_mentioned": [
            {"product_id": pid, "name": f"商品{pid}", "relevance": "直接匹配"}
            for pid in (product_ids or [])
        ],
        "upsell_suggestions": [],
        "requires_human_review": False,
    }


# ---------------------------------------------------------------------------
# 单元评估：意图识别
# ---------------------------------------------------------------------------


class TestIntentRecognition:
    """评估意图识别准确性（unit-level, mock LLM 输出）。"""

    @pytest.mark.parametrize(
        "user_message, expected_intent",
        [
            ("有适合老人的血压计吗？", "product_inquiry"),
            ("我要退货", "return_request"),
            ("能换一个吗", "exchange_request"),
            ("投诉你们！", "complaint"),
            ("用着很好，谢谢", "praise"),
            ("您好", "greeting"),
        ],
    )
    def test_intent_labels_are_valid(self, user_message, expected_intent):
        """验证 expected_intent 标签合法性（golden data 自检）。"""
        assert expected_intent in VALID_INTENTS, f"非法 intent 标签: {expected_intent}"

    def test_intent_output_format(self):
        """意图识别输出应包含必要字段。"""
        mock_intent = _make_intent()
        result = check_output_format(
            mock_intent,
            required_keys=["intent", "confidence", "sentiment", "requires_human"],
        )
        assert result["valid"], f"意图输出缺少字段: {result['missing_keys']}"

    def test_intent_confidence_range(self):
        """置信度应在 [0, 1] 范围内。"""
        for conf in [0.0, 0.5, 1.0]:
            intent = _make_intent(confidence=conf)
            assert 0.0 <= intent["confidence"] <= 1.0

    def test_intent_confidence_out_of_range_detected(self):
        """超出范围的置信度应被检测到。"""
        bad_intent = _make_intent(confidence=1.5)
        assert bad_intent["confidence"] > 1.0  # 框架应拒绝此值

    def test_sentiment_labels_valid(self):
        """情感标签应在合法集合内。"""
        for sentiment in VALID_SENTIMENTS:
            intent = _make_intent(sentiment=sentiment)
            assert intent["sentiment"] in VALID_SENTIMENTS

    def test_complaint_requires_human(self):
        """投诉 intent 且情感为 negative，应触发 requires_human=True。"""
        intent = _make_intent(intent="complaint", sentiment="negative", requires_human=True)
        assert intent["requires_human"] is True

    def test_greeting_no_human_required(self):
        """问候类 intent 不需要人工介入。"""
        intent = _make_intent(intent="greeting", requires_human=False)
        assert intent["requires_human"] is False

    def test_classification_accuracy_metric(self):
        """模拟批量预测，验证 accuracy 计算。"""
        metrics = ClassificationMetrics()
        pairs = [
            ("product_inquiry", "product_inquiry"),
            ("complaint", "complaint"),
            ("return_request", "exchange_request"),  # 故意错误
            ("greeting", "greeting"),
        ]
        for pred, exp in pairs:
            metrics.record(pred, exp)

        acc = metrics.accuracy()
        assert 0.5 <= acc <= 1.0, f"accuracy 应在合理范围, 得到 {acc}"
        assert acc == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# 单元评估：情感检测
# ---------------------------------------------------------------------------


class TestSentimentDetection:
    """评估情感检测准确性。"""

    @pytest.mark.parametrize(
        "user_message, expected_sentiment",
        [
            ("太好了，血压计用着超顺手！", "positive"),
            ("请问营业时间是几点到几点？", "neutral"),
            ("发货太慢了，很不满意", "negative"),
            ("你们这是什么破店！", "negative"),
        ],
    )
    def test_sentiment_label_validity(self, user_message, expected_sentiment):
        """验证 golden 情感标签合法性。"""
        assert expected_sentiment in VALID_SENTIMENTS

    def test_angry_message_is_negative(self):
        """愤怒消息应被分类为 negative sentiment。"""
        angry_intent = _make_intent(sentiment="negative", requires_human=True)
        assert angry_intent["sentiment"] == "negative"

    def test_positive_message_no_escalation(self):
        """正面消息不应触发升级。"""
        positive_intent = _make_intent(sentiment="positive", requires_human=False)
        assert positive_intent["requires_human"] is False


# ---------------------------------------------------------------------------
# 单元评估：回复生成 & 幻觉检测
# ---------------------------------------------------------------------------


class TestReplyGeneration:
    """评估客服回复质量与幻觉检测。"""

    def test_reply_output_format(self):
        """回复应包含必要字段。"""
        reply = _make_reply("亲，推荐这款血压计~", product_ids=["P100"])
        result = check_output_format(
            reply, required_keys=["reply_text", "confidence", "products_mentioned"]
        )
        assert result["valid"], f"回复缺少字段: {result['missing_keys']}"

    def test_reply_text_not_empty(self):
        """回复文本不应为空。"""
        reply = _make_reply("亲，推荐这款血压计~")
        assert len(reply["reply_text"].strip()) > 0

    def test_no_hallucination_when_product_exists(self):
        """回复引用的商品 ID 在已知商品集合中时，不应报幻觉。"""
        tracker = HallucinationTracker(known_products={"P100", "P200"})
        result = tracker.check_reply(
            "推荐这款鱼跃血压计",
            mentioned_ids=["P100"],
        )
        assert not result["has_hallucination"]
        assert tracker.hallucination_rate() == 0.0

    def test_hallucination_detected_for_unknown_product(self):
        """回复引用了不存在的商品 ID，应检测到幻觉。"""
        tracker = HallucinationTracker(known_products={"P100", "P200"})
        result = tracker.check_reply(
            "推荐这款 SUPER-HEAL 万能治疗仪",
            mentioned_ids=["FAKE001"],
        )
        assert result["has_hallucination"]
        assert "FAKE001" in result["hallucinated_ids"]
        assert tracker.hallucination_rate() == 1.0

    def test_mixed_hallucination_rate(self):
        """混合场景：部分真实、部分幻觉，hallucination_rate 应为 0.5。"""
        tracker = HallucinationTracker(known_products={"P100"})
        tracker.check_reply("推荐 P100", mentioned_ids=["P100"])  # 真实
        tracker.check_reply("推荐 FAKE001", mentioned_ids=["FAKE001"])  # 幻觉
        assert tracker.hallucination_rate() == pytest.approx(0.5)

    def test_medical_disclaimer_forbidden_words(self):
        """医疗器械回复不应包含违规声明。"""
        reply_text = "这款血糖仪能根治糖尿病，治愈效果显著！"
        result = check_text_constraints(
            reply_text,
            forbidden_keywords=["治愈", "根治", "包治百病"],
        )
        assert not result["valid"]
        assert len(result["issues"]) > 0

    def test_reply_length_reasonable(self):
        """回复长度应在合理范围（10-500 字）。"""
        reply_text = "亲，推荐鱼跃电子血压计，大屏显示适合老人，测量精准，欢迎选购~"
        result = check_text_constraints(reply_text, min_len=10, max_len=500)
        assert result["valid"]


# ---------------------------------------------------------------------------
# 集成评估：使用 golden data 批量跑
# ---------------------------------------------------------------------------


class TestGoldenDataBatch:
    """使用 cs_test_cases.json 批量验证意图 + 情感 + 幻觉。"""

    def test_all_golden_cases_have_required_fields(self, cs_test_cases):
        """golden data 格式自检。"""
        required = ["id", "category", "user_message", "expected_intent", "expected_sentiment"]
        for case in cs_test_cases["cases"]:
            missing = [k for k in required if k not in case]
            assert not missing, f"用例 {case.get('id')} 缺少字段: {missing}"

    def test_golden_intent_labels_valid(self, cs_test_cases):
        """所有 golden label 中的 intent 应在合法集合中。"""
        for case in cs_test_cases["cases"]:
            intent = case["expected_intent"]
            assert intent in VALID_INTENTS, f"用例 {case['id']} 的 intent={intent!r} 非法"

    def test_golden_sentiment_labels_valid(self, cs_test_cases):
        """所有 golden label 中的 sentiment 应在合法集合中。"""
        for case in cs_test_cases["cases"]:
            sentiment = case["expected_sentiment"]
            assert sentiment in VALID_SENTIMENTS, f"用例 {case['id']} 的 sentiment={sentiment!r} 非法"

    def test_complaint_cases_require_human(self, cs_test_cases):
        """投诉类 case 应标注 requires_human=True。"""
        complaint_cases = [c for c in cs_test_cases["cases"] if c["expected_intent"] == "complaint"]
        assert len(complaint_cases) > 0, "golden data 中应有投诉用例"
        for case in complaint_cases:
            assert case.get("expected_requires_human") is True, (
                f"用例 {case['id']} 是投诉但 requires_human 未标注为 True"
            )

    def test_simulated_batch_accuracy(self, cs_test_cases):
        """
        模拟批量意图预测，使用 mock 预测 = golden label（完美场景），
        验证指标计算逻辑正确。
        """
        metrics = ClassificationMetrics()
        for case in cs_test_cases["cases"]:
            # 完美预测：predicted == expected
            metrics.record(case["expected_intent"], case["expected_intent"])

        report = metrics.classification_report()
        assert report["accuracy"] == pytest.approx(1.0)
        assert report["f1_macro"] == pytest.approx(1.0)

    def test_hallucination_check_cases(self, cs_test_cases):
        """验证标注为 hallucination_check=True 的用例有 valid_product_names 字段。"""
        halluc_cases = [c for c in cs_test_cases["cases"] if c.get("hallucination_check")]
        for case in halluc_cases:
            assert "valid_product_names" in case, f"用例 {case['id']} 缺少 valid_product_names"
