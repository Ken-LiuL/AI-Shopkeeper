"""Tests for Prompt templates — Selection and CustomerService."""

from __future__ import annotations

import pytest

from src.agents.prompts.selection import (
    market_analysis_prompt,
    competitor_analysis_prompt,
    inventory_analysis_prompt,
    seasonal_factors_prompt,
    gap_identification_prompt,
    supplier_evaluation_prompt,
    scorer_prompt,
    scorer_reflection_prompt,
)
from src.agents.prompts.customer_service import (
    intent_prompt,
    reply_prompt,
    FAQ_TEMPLATES,
    HUMAN_TRANSFER_KEYWORDS,
)


# ---------------------------------------------------------------------------
# Selection Prompts Tests
# ---------------------------------------------------------------------------

class TestMarketAnalysisPrompt:
    """Tests for market_analysis_prompt."""

    def test_generates_without_error(self):
        """Prompt generates without raising exception."""
        result = market_analysis_prompt(
            keywords_data="test keywords",
            products_data="test products",
            categories="医疗器械",
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_keywords_data(self):
        """Prompt includes provided keywords data."""
        result = market_analysis_prompt(
            keywords_data="血压计搜索量5000",
            products_data="products",
            categories="医疗器械",
        )
        assert "血压计搜索量5000" in result

    def test_includes_products_data(self):
        """Prompt includes provided products data."""
        result = market_analysis_prompt(
            keywords_data="kw",
            products_data="鱼跃血压计月销320",
            categories="医疗器械",
        )
        assert "鱼跃血压计月销320" in result

    def test_includes_categories(self):
        """Prompt includes specified categories."""
        result = market_analysis_prompt(
            keywords_data="kw",
            products_data="prod",
            categories="血压计, 体温计",
        )
        assert "血压计, 体温计" in result

    def test_includes_heat_score_formula(self):
        """Prompt includes heat score calculation guidance."""
        result = market_analysis_prompt("kw", "prod", "cat")
        assert "heat_score" in result

    def test_includes_tool_instruction(self):
        """Prompt instructs to use output tool."""
        result = market_analysis_prompt("kw", "prod", "cat")
        assert "output_market_analysis" in result


class TestCompetitorAnalysisPrompt:
    """Tests for competitor_analysis_prompt."""

    def test_generates_without_error(self):
        """Prompt generates without raising exception."""
        result = competitor_analysis_prompt(
            competitor_stores="stores",
            competitor_products="products",
            stockouts="stockouts",
            our_products="our products",
        )
        assert isinstance(result, str)

    def test_includes_all_inputs(self):
        """Prompt includes all provided data."""
        result = competitor_analysis_prompt(
            competitor_stores="康复之家",
            competitor_products="制氧机",
            stockouts="N95口罩",
            our_products="血压计",
        )
        assert "康复之家" in result
        assert "制氧机" in result
        assert "N95口罩" in result
        assert "血压计" in result

    def test_includes_threat_assessment(self):
        """Prompt includes threat assessment rules."""
        result = competitor_analysis_prompt("s", "p", "st", "o")
        assert "threat" in result.lower() or "威胁" in result


class TestInventoryAnalysisPrompt:
    """Tests for inventory_analysis_prompt."""

    def test_generates_without_error(self):
        """Prompt generates without raising exception."""
        result = inventory_analysis_prompt(
            products="test products",
            sales_data="test sales",
        )
        assert isinstance(result, str)

    def test_includes_products_and_sales(self):
        """Prompt includes products and sales data."""
        result = inventory_analysis_prompt(
            products="SKU列表",
            sales_data="30天销售数据",
        )
        assert "SKU列表" in result
        assert "30天销售数据" in result

    def test_includes_turnover_rules(self):
        """Prompt includes inventory turnover classification."""
        result = inventory_analysis_prompt("p", "s")
        # Should mention turnover days or status classification
        assert "周转" in result or "fast_moving" in result or "slow_moving" in result


class TestSeasonalFactorsPrompt:
    """Tests for seasonal_factors_prompt."""

    def test_generates_without_error(self):
        """Prompt generates without raising exception."""
        result = seasonal_factors_prompt(
            current_date="2026-02-11",
            current_season="冬季",
            upcoming_events="春节",
            weather_forecast="降温",
            trending_events="无",
        )
        assert isinstance(result, str)

    def test_includes_all_inputs(self):
        """Prompt includes all temporal data."""
        result = seasonal_factors_prompt(
            current_date="2026-02-11",
            current_season="冬季",
            upcoming_events="春节、元宵",
            weather_forecast="寒潮预警",
            trending_events="流感高发",
        )
        assert "2026-02-11" in result
        assert "冬季" in result
        assert "春节" in result
        assert "寒潮预警" in result
        assert "流感高发" in result

    def test_includes_seasonal_rules(self):
        """Prompt includes seasonal demand rules."""
        result = seasonal_factors_prompt("d", "s", "e", "w", "t")
        # Should mention seasonal patterns
        assert "季节" in result or "season" in result.lower()

    def test_default_trending_events(self):
        """Prompt handles default trending events."""
        result = seasonal_factors_prompt("d", "s", "e", "w")
        assert isinstance(result, str)


class TestGapIdentificationPrompt:
    """Tests for gap_identification_prompt."""

    def test_generates_without_error(self):
        """Prompt generates without raising exception."""
        result = gap_identification_prompt(
            market_data='{"keywords": []}',
            competitor_data='{"competitors": []}',
            inventory_data='{"covered_keywords": []}',
            seasonal_data='{"factors": []}',
        )
        assert isinstance(result, str)

    def test_includes_all_analysis_data(self):
        """Prompt includes all upstream analysis results."""
        result = gap_identification_prompt(
            market_data="market_json",
            competitor_data="competitor_json",
            inventory_data="inventory_json",
            seasonal_data="seasonal_json",
        )
        assert "market_json" in result
        assert "competitor_json" in result
        assert "inventory_json" in result
        assert "seasonal_json" in result

    def test_includes_priority_rules(self):
        """Prompt includes priority classification rules."""
        result = gap_identification_prompt("m", "c", "i", "s")
        assert "high" in result.lower() or "优先" in result


class TestSupplierEvaluationPrompt:
    """Tests for supplier_evaluation_prompt."""

    def test_generates_without_error(self):
        """Prompt generates without raising exception."""
        result = supplier_evaluation_prompt(
            keyword="制氧机",
            market_price=2500,
            monthly_demand=100,
            alibaba_results="alibaba data",
            pdd_results="pdd data",
        )
        assert isinstance(result, str)

    def test_includes_keyword(self):
        """Prompt includes target keyword."""
        result = supplier_evaluation_prompt("血压计", 200, 50, "ali", "pdd")
        assert "血压计" in result

    def test_includes_both_channels(self):
        """Prompt includes both 1688 and pdd data."""
        result = supplier_evaluation_prompt(
            keyword="test",
            market_price=100,
            monthly_demand=50,
            alibaba_results="1688供应商数据",
            pdd_results="拼多多店铺数据",
        )
        assert "1688供应商数据" in result
        assert "拼多多店铺数据" in result

    def test_includes_price_info(self):
        """Prompt includes market price and demand."""
        result = supplier_evaluation_prompt("k", 1999, 200, "a", "p")
        assert "1999" in result
        assert "200" in result

    def test_includes_channel_comparison_rules(self):
        """Prompt includes channel comparison guidance."""
        result = supplier_evaluation_prompt("k", 100, 50, "a", "p")
        # Should mention both platforms
        assert "1688" in result
        assert "拼多多" in result


class TestScorerPrompt:
    """Tests for scorer_prompt."""

    def test_generates_without_error(self):
        """Prompt generates without raising exception."""
        result = scorer_prompt(
            gap_opportunities='{"opportunities": []}',
            supplier_evaluations='[]',
            seasonal_factors='{}',
            market_data='{}',
            competitor_data='{}',
            inventory_summary='{}',
        )
        assert isinstance(result, str)

    def test_includes_all_data_sources(self):
        """Prompt includes all upstream data."""
        result = scorer_prompt(
            gap_opportunities="gap_json",
            supplier_evaluations="supplier_json",
            seasonal_factors="seasonal_json",
            market_data="market_json",
            competitor_data="competitor_json",
            inventory_summary="inventory_json",
        )
        assert "gap_json" in result
        assert "supplier_json" in result
        assert "seasonal_json" in result
        assert "market_json" in result
        assert "competitor_json" in result
        assert "inventory_json" in result

    def test_includes_six_dimensions(self):
        """Prompt includes 6-dimension scoring model."""
        result = scorer_prompt("g", "s", "sf", "m", "c", "i")
        expected_dims = ["市场热度", "竞争空位", "供应链", "利润空间", "品类协同", "季节契合"]
        # At least some dimensions should be mentioned
        found = sum(1 for dim in expected_dims if dim in result)
        assert found >= 4, "Should mention at least 4 of 6 scoring dimensions"

    def test_includes_weight_config(self):
        """Prompt includes dimension weights."""
        result = scorer_prompt("g", "s", "sf", "m", "c", "i")
        # Should mention weights like 25%, 20%, etc.
        assert "25%" in result or "0.25" in result or "权重" in result


class TestScorerReflectionPrompt:
    """Tests for scorer_reflection_prompt."""

    def test_generates_without_error(self):
        """Prompt generates without raising exception."""
        result = scorer_reflection_prompt('{"recommendations": []}')
        assert isinstance(result, str)

    def test_includes_initial_result(self):
        """Prompt includes initial scoring result."""
        initial = '{"recommendations": [{"keyword": "血压计", "final_score": 85}]}'
        result = scorer_reflection_prompt(initial)
        assert "血压计" in result
        assert "85" in result

    def test_includes_verification_checklist(self):
        """Prompt includes verification items."""
        result = scorer_reflection_prompt('{}')
        # Should mention checking/验证
        assert "检查" in result or "verify" in result.lower() or "验证" in result

    def test_asks_for_reflection_notes(self):
        """Prompt asks to fill reflection_notes."""
        result = scorer_reflection_prompt('{}')
        assert "reflection_notes" in result


# ---------------------------------------------------------------------------
# CustomerService Prompts Tests
# ---------------------------------------------------------------------------

class TestIntentPrompt:
    """Tests for intent_prompt."""

    def test_generates_without_error(self):
        """Prompt generates without raising exception."""
        result = intent_prompt(
            user_message="有血压计吗？",
            conversation_history="无",
        )
        assert isinstance(result, str)

    def test_includes_user_message(self):
        """Prompt includes user message."""
        result = intent_prompt(
            user_message="推荐一款适合老人的血压计",
            conversation_history="无",
        )
        assert "推荐一款适合老人的血压计" in result

    def test_includes_conversation_history(self):
        """Prompt includes conversation history."""
        history = '[{"role": "user", "content": "你好"}]'
        result = intent_prompt("有血压计吗", history)
        assert history in result

    def test_includes_intent_categories(self):
        """Prompt includes all intent categories."""
        result = intent_prompt("test", "无")
        expected_intents = ["product_inquiry", "logistics", "complaint", "greeting"]
        found = sum(1 for intent in expected_intents if intent in result)
        assert found >= 3, "Should mention most intent categories"

    def test_includes_human_transfer_triggers(self):
        """Prompt mentions human transfer triggers."""
        result = intent_prompt("test", "无")
        # Should mention keywords that trigger human transfer
        assert "投诉" in result or "转人工" in result

    def test_includes_entity_extraction_guidance(self):
        """Prompt includes entity extraction guidance."""
        result = intent_prompt("test", "无")
        assert "product_mentioned" in result or "商品" in result

    def test_default_conversation_history(self):
        """Prompt handles default conversation history."""
        result = intent_prompt("test")
        assert isinstance(result, str)


class TestReplyPrompt:
    """Tests for reply_prompt."""

    def test_generates_without_error(self):
        """Prompt generates without raising exception."""
        result = reply_prompt(
            user_message="有血压计吗",
            intent='{"intent": "product_inquiry"}',
            retrieved_products_with_graph='[{"name": "鱼跃血压计"}]',
        )
        assert isinstance(result, str)

    def test_includes_user_message(self):
        """Prompt includes user message."""
        result = reply_prompt(
            user_message="老人用什么血压计好",
            intent='{}',
            retrieved_products_with_graph='[]',
        )
        assert "老人用什么血压计好" in result

    def test_includes_intent(self):
        """Prompt includes intent data."""
        result = reply_prompt(
            user_message="test",
            intent='{"intent": "recommendation", "confidence": 0.9}',
            retrieved_products_with_graph='[]',
        )
        assert "recommendation" in result

    def test_includes_products(self):
        """Prompt includes retrieved products."""
        result = reply_prompt(
            user_message="test",
            intent='{}',
            retrieved_products_with_graph='[{"name": "欧姆龙血压计", "price": 299}]',
        )
        assert "欧姆龙血压计" in result

    def test_includes_reply_principles(self):
        """Prompt includes reply generation principles."""
        result = reply_prompt("t", "{}", "[]")
        # Should mention accuracy, professionalism, brevity
        principles = ["准确", "专业", "简洁", "友好"]
        found = sum(1 for p in principles if p in result)
        assert found >= 2, "Should mention key reply principles"

    def test_includes_prohibited_phrases(self):
        """Prompt includes prohibited phrases."""
        result = reply_prompt("t", "{}", "[]")
        # Should mention what NOT to say
        assert "禁止" in result or "❌" in result

    def test_includes_upsell_guidance(self):
        """Prompt includes upsell/cross-sell guidance."""
        result = reply_prompt("t", "{}", "[]")
        assert "追销" in result or "推荐" in result or "upsell" in result.lower()


# ---------------------------------------------------------------------------
# FAQ Templates Tests
# ---------------------------------------------------------------------------

class TestFAQTemplates:
    """Tests for FAQ_TEMPLATES configuration."""

    def test_greeting_templates_exist(self):
        """Greeting templates exist."""
        assert "greeting" in FAQ_TEMPLATES
        assert len(FAQ_TEMPLATES["greeting"]) > 0

    def test_logistics_templates_exist(self):
        """Logistics templates exist."""
        assert "logistics" in FAQ_TEMPLATES
        assert len(FAQ_TEMPLATES["logistics"]) > 0

    def test_greeting_has_trigger_and_reply(self):
        """Greeting templates have trigger and reply."""
        for tpl in FAQ_TEMPLATES["greeting"]:
            assert "trigger" in tpl
            assert "reply" in tpl
            assert isinstance(tpl["trigger"], list)
            assert isinstance(tpl["reply"], str)

    def test_logistics_covers_common_questions(self):
        """Logistics templates cover common questions."""
        all_triggers = []
        for tpl in FAQ_TEMPLATES["logistics"]:
            all_triggers.extend(tpl.get("trigger", []))
        # Should cover delivery time, shipping status
        assert any("多久" in t for t in all_triggers) or any("到" in t for t in all_triggers)


class TestHumanTransferKeywords:
    """Tests for HUMAN_TRANSFER_KEYWORDS."""

    def test_is_list(self):
        """Transfer keywords is a list."""
        assert isinstance(HUMAN_TRANSFER_KEYWORDS, list)

    def test_contains_complaint_keywords(self):
        """Contains complaint-related keywords."""
        assert "投诉" in HUMAN_TRANSFER_KEYWORDS

    def test_contains_legal_keywords(self):
        """Contains legal/escalation keywords."""
        legal_keywords = ["律师", "起诉", "315", "消协"]
        found = sum(1 for kw in legal_keywords if kw in HUMAN_TRANSFER_KEYWORDS)
        assert found >= 2, "Should contain legal escalation keywords"

    def test_contains_refund_keywords(self):
        """Contains refund-related keywords."""
        assert "退款" in HUMAN_TRANSFER_KEYWORDS or "赔偿" in HUMAN_TRANSFER_KEYWORDS

    def test_all_lowercase_safe(self):
        """Keywords work with lowercase comparison."""
        # All keywords should be Chinese or lowercase English
        for kw in HUMAN_TRANSFER_KEYWORDS:
            assert kw == kw.lower(), f"Keyword '{kw}' should be lowercase"
