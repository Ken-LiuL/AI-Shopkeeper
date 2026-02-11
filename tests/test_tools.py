"""Tests for Tool Schema definitions — validate all 17+ tools."""

from __future__ import annotations

import pytest

from src.agents.tools import (
    # Selection
    MARKET_ANALYSIS_TOOL,
    COMPETITOR_ANALYSIS_TOOL,
    INVENTORY_ANALYSIS_TOOL,
    SEASONAL_FACTORS_TOOL,
    GAP_OPPORTUNITIES_TOOL,
    SUPPLIER_EVALUATION_TOOL,
    RECOMMENDATIONS_TOOL,
    # CustomerService
    INTENT_TOOL,
    REPLY_TOOL,
    # Alert
    ANOMALIES_TOOL,
    ROOT_CAUSES_TOOL,
    ACTIONS_TOOL,
    # Bundle
    ASSOCIATION_RULES_TOOL,
    BUNDLE_PROPOSALS_TOOL,
    BUNDLE_PRICING_TOOL,
    # Listing
    PARSED_PRODUCT_TOOL,
    LISTING_INFO_TOOL,
    COMPLIANCE_CHECK_TOOL,
    # Collections
    ALL_TOOLS,
    SELECTION_TOOLS,
    CUSTOMER_SERVICE_TOOLS,
    ALERT_TOOLS,
    BUNDLE_TOOLS,
    LISTING_TOOLS,
)


# ---------------------------------------------------------------------------
# Schema Validation Helpers
# ---------------------------------------------------------------------------

def validate_tool_schema(tool: dict) -> list[str]:
    """
    Validate a tool schema against Anthropic Tool Use requirements.
    Returns list of validation errors (empty if valid).
    """
    errors = []

    # Required top-level fields
    if "name" not in tool:
        errors.append("Missing 'name' field")
    elif not isinstance(tool["name"], str) or not tool["name"]:
        errors.append("'name' must be a non-empty string")

    if "description" not in tool:
        errors.append("Missing 'description' field")
    elif not isinstance(tool["description"], str):
        errors.append("'description' must be a string")

    if "input_schema" not in tool:
        errors.append("Missing 'input_schema' field")
    else:
        schema = tool["input_schema"]
        if not isinstance(schema, dict):
            errors.append("'input_schema' must be a dict")
        else:
            if schema.get("type") != "object":
                errors.append("input_schema.type must be 'object'")
            if "properties" not in schema:
                errors.append("input_schema must have 'properties'")
            elif not isinstance(schema["properties"], dict):
                errors.append("input_schema.properties must be a dict")
            # required should be a list if present
            if "required" in schema and not isinstance(schema["required"], list):
                errors.append("input_schema.required must be a list")

    return errors


def validate_property_types(properties: dict) -> list[str]:
    """Validate property type definitions."""
    errors = []
    valid_types = {"string", "number", "integer", "boolean", "array", "object", "null"}
    
    for prop_name, prop_def in properties.items():
        if isinstance(prop_def, dict):
            # Check type field
            if "type" in prop_def:
                prop_type = prop_def["type"]
                if prop_type not in valid_types:
                    errors.append(f"Property '{prop_name}' has invalid type: {prop_type}")
            # Check enum is a list
            if "enum" in prop_def and not isinstance(prop_def["enum"], list):
                errors.append(f"Property '{prop_name}' enum must be a list")
            # Check array items
            if prop_def.get("type") == "array" and "items" not in prop_def:
                errors.append(f"Array property '{prop_name}' missing 'items'")
            # Recursively check nested objects
            if prop_def.get("type") == "object" and "properties" in prop_def:
                nested_errors = validate_property_types(prop_def["properties"])
                errors.extend([f"{prop_name}.{e}" for e in nested_errors])

    return errors


# ---------------------------------------------------------------------------
# Selection Tools Tests
# ---------------------------------------------------------------------------

class TestSelectionTools:
    """Tests for Selection Agent tool schemas."""

    def test_market_analysis_tool_valid(self):
        """Market analysis tool has valid schema."""
        errors = validate_tool_schema(MARKET_ANALYSIS_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_market_analysis_tool_required_fields(self):
        """Market analysis tool has correct required fields."""
        required = MARKET_ANALYSIS_TOOL["input_schema"]["required"]
        assert "analysis_summary" in required
        assert "keywords" in required
        assert "products" in required

    def test_market_analysis_keywords_structure(self):
        """Market analysis keywords array has correct item structure."""
        props = MARKET_ANALYSIS_TOOL["input_schema"]["properties"]
        keywords_items = props["keywords"]["items"]["properties"]
        assert "keyword" in keywords_items
        assert "search_volume" in keywords_items
        assert "heat_score" in keywords_items
        assert "trend" in keywords_items

    def test_competitor_analysis_tool_valid(self):
        """Competitor analysis tool has valid schema."""
        errors = validate_tool_schema(COMPETITOR_ANALYSIS_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_competitor_analysis_required(self):
        """Competitor analysis has required fields."""
        required = COMPETITOR_ANALYSIS_TOOL["input_schema"]["required"]
        assert "competitor_summary" in required
        assert "gap_products" in required
        assert "stockout_opportunities" in required

    def test_inventory_analysis_tool_valid(self):
        """Inventory analysis tool has valid schema."""
        errors = validate_tool_schema(INVENTORY_ANALYSIS_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_seasonal_factors_tool_valid(self):
        """Seasonal factors tool has valid schema."""
        errors = validate_tool_schema(SEASONAL_FACTORS_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_seasonal_factors_enums(self):
        """Seasonal factors has correct enum values."""
        factors_props = SEASONAL_FACTORS_TOOL["input_schema"]["properties"]["factors"]["items"]["properties"]
        assert "season" in factors_props["event_type"]["enum"]
        assert "holiday" in factors_props["event_type"]["enum"]
        assert "high" in factors_props["impact_level"]["enum"]

    def test_gap_opportunities_tool_valid(self):
        """Gap opportunities tool has valid schema."""
        errors = validate_tool_schema(GAP_OPPORTUNITIES_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_gap_opportunities_structure(self):
        """Gap opportunities has correct structure."""
        props = GAP_OPPORTUNITIES_TOOL["input_schema"]["properties"]
        assert "gap_summary" in props
        assert "opportunities" in props
        opp_items = props["opportunities"]["items"]["properties"]
        assert "keyword" in opp_items
        assert "priority" in opp_items
        assert "market_heat_score" in opp_items

    def test_supplier_evaluation_tool_valid(self):
        """Supplier evaluation tool has valid schema."""
        errors = validate_tool_schema(SUPPLIER_EVALUATION_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_supplier_evaluation_dual_channel(self):
        """Supplier evaluation supports both alibaba and pdd channels."""
        props = SUPPLIER_EVALUATION_TOOL["input_schema"]["properties"]
        assert "alibaba_evaluation" in props
        assert "pdd_evaluation" in props
        assert "cost_comparison" in props
        # Check channel enums
        rec_channel = props["recommendation"]["properties"]["best_channel"]["enum"]
        assert "alibaba" in rec_channel
        assert "pdd" in rec_channel

    def test_recommendations_tool_valid(self):
        """Recommendations tool has valid schema."""
        errors = validate_tool_schema(RECOMMENDATIONS_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_recommendations_score_breakdown(self):
        """Recommendations includes 6-dimension score breakdown."""
        recs_items = RECOMMENDATIONS_TOOL["input_schema"]["properties"]["recommendations"]["items"]
        breakdown = recs_items["properties"]["score_breakdown"]["properties"]
        expected_dims = [
            "market_heat", "competition_gap", "supply_chain",
            "profit_margin", "category_synergy", "seasonal_fit"
        ]
        for dim in expected_dims:
            assert dim in breakdown, f"Missing dimension: {dim}"

    def test_recommendations_has_reflection_notes(self):
        """Recommendations includes reflection_notes for self-reflection."""
        props = RECOMMENDATIONS_TOOL["input_schema"]["properties"]
        assert "reflection_notes" in props


# ---------------------------------------------------------------------------
# CustomerService Tools Tests
# ---------------------------------------------------------------------------

class TestCustomerServiceTools:
    """Tests for CustomerService Agent tool schemas."""

    def test_intent_tool_valid(self):
        """Intent tool has valid schema."""
        errors = validate_tool_schema(INTENT_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_intent_tool_required_fields(self):
        """Intent tool has correct required fields."""
        required = INTENT_TOOL["input_schema"]["required"]
        assert "intent" in required
        assert "confidence" in required
        assert "requires_human" in required

    def test_intent_tool_all_intents(self):
        """Intent tool covers all expected intent types."""
        intent_enum = INTENT_TOOL["input_schema"]["properties"]["intent"]["enum"]
        expected_intents = [
            "product_inquiry", "usage_question", "recommendation",
            "logistics", "after_sales", "complaint", "greeting", "other"
        ]
        for intent in expected_intents:
            assert intent in intent_enum, f"Missing intent: {intent}"

    def test_intent_tool_sentiment(self):
        """Intent tool has sentiment field with correct enum."""
        sentiment_enum = INTENT_TOOL["input_schema"]["properties"]["sentiment"]["enum"]
        assert set(sentiment_enum) == {"positive", "neutral", "negative", "urgent"}

    def test_intent_tool_extracted_entities(self):
        """Intent tool can extract relevant entities."""
        entities = INTENT_TOOL["input_schema"]["properties"]["extracted_entities"]["properties"]
        assert "product_mentioned" in entities
        assert "target_population" in entities
        assert "scenario" in entities

    def test_reply_tool_valid(self):
        """Reply tool has valid schema."""
        errors = validate_tool_schema(REPLY_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_reply_tool_length_limit(self):
        """Reply tool has maxLength for reply_text."""
        reply_props = REPLY_TOOL["input_schema"]["properties"]["reply_text"]
        assert "maxLength" in reply_props
        assert reply_props["maxLength"] == 150

    def test_reply_tool_upsell_limit(self):
        """Reply tool limits upsell suggestions to 2."""
        upsell = REPLY_TOOL["input_schema"]["properties"]["upsell_suggestions"]
        assert upsell.get("maxItems") == 2


# ---------------------------------------------------------------------------
# Alert Tools Tests
# ---------------------------------------------------------------------------

class TestAlertTools:
    """Tests for Alert Agent tool schemas."""

    def test_anomalies_tool_valid(self):
        """Anomalies tool has valid schema."""
        errors = validate_tool_schema(ANOMALIES_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_anomalies_tool_types(self):
        """Anomalies tool covers all anomaly types."""
        anomaly_types = ANOMALIES_TOOL["input_schema"]["properties"]["anomalies"]["items"]["properties"]["anomaly_type"]["enum"]
        expected_types = [
            "sales_drop_prophet", "sales_spike_prophet", "zero_sales",
            "stockout_urgent", "margin_warning"
        ]
        for t in expected_types:
            assert t in anomaly_types, f"Missing anomaly type: {t}"

    def test_root_causes_tool_valid(self):
        """Root causes tool has valid schema."""
        errors = validate_tool_schema(ROOT_CAUSES_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_actions_tool_valid(self):
        """Actions tool has valid schema."""
        errors = validate_tool_schema(ACTIONS_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_actions_tool_priorities(self):
        """Actions tool has correct priority levels."""
        action_props = ACTIONS_TOOL["input_schema"]["properties"]["recommended_actions"]["items"]["properties"]
        priority_enum = action_props["priority"]["enum"]
        assert set(priority_enum) == {"P0", "P1", "P2", "P3"}


# ---------------------------------------------------------------------------
# Bundle Tools Tests
# ---------------------------------------------------------------------------

class TestBundleTools:
    """Tests for Bundle Agent tool schemas."""

    def test_association_rules_tool_valid(self):
        """Association rules tool has valid schema."""
        errors = validate_tool_schema(ASSOCIATION_RULES_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_bundle_proposals_tool_valid(self):
        """Bundle proposals tool has valid schema."""
        errors = validate_tool_schema(BUNDLE_PROPOSALS_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_bundle_pricing_tool_valid(self):
        """Bundle pricing tool has valid schema."""
        errors = validate_tool_schema(BUNDLE_PRICING_TOOL)
        assert errors == [], f"Validation errors: {errors}"


# ---------------------------------------------------------------------------
# Listing Tools Tests
# ---------------------------------------------------------------------------

class TestListingTools:
    """Tests for Listing Agent tool schemas."""

    def test_parsed_product_tool_valid(self):
        """Parsed product tool has valid schema."""
        errors = validate_tool_schema(PARSED_PRODUCT_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_parsed_product_platforms(self):
        """Parsed product supports alibaba and pdd platforms."""
        platform_enum = PARSED_PRODUCT_TOOL["input_schema"]["properties"]["source_platform"]["enum"]
        assert "alibaba" in platform_enum
        assert "pdd" in platform_enum

    def test_listing_info_tool_valid(self):
        """Listing info tool has valid schema."""
        errors = validate_tool_schema(LISTING_INFO_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_listing_info_title_length(self):
        """Listing info has title length limit."""
        title = LISTING_INFO_TOOL["input_schema"]["properties"]["optimized_title"]
        assert title.get("maxLength") == 30

    def test_compliance_check_tool_valid(self):
        """Compliance check tool has valid schema."""
        errors = validate_tool_schema(COMPLIANCE_CHECK_TOOL)
        assert errors == [], f"Validation errors: {errors}"

    def test_compliance_severity_levels(self):
        """Compliance check has correct severity levels."""
        issues = COMPLIANCE_CHECK_TOOL["input_schema"]["properties"]["issues"]["items"]["properties"]
        severity_enum = issues["severity"]["enum"]
        assert set(severity_enum) == {"fatal", "error", "warning", "info"}


# ---------------------------------------------------------------------------
# Tool Collections Tests
# ---------------------------------------------------------------------------

class TestToolCollections:
    """Tests for tool collection lists."""

    def test_selection_tools_count(self):
        """Selection tools contains 7 tools."""
        assert len(SELECTION_TOOLS) == 7

    def test_customer_service_tools_count(self):
        """Customer service tools contains 2 tools."""
        assert len(CUSTOMER_SERVICE_TOOLS) == 2

    def test_alert_tools_count(self):
        """Alert tools contains 3 tools."""
        assert len(ALERT_TOOLS) == 3

    def test_bundle_tools_count(self):
        """Bundle tools contains 3 tools."""
        assert len(BUNDLE_TOOLS) == 3

    def test_listing_tools_count(self):
        """Listing tools contains 3 tools."""
        assert len(LISTING_TOOLS) == 3

    def test_all_tools_is_union(self):
        """ALL_TOOLS is union of all agent-specific tool lists."""
        expected_count = (
            len(SELECTION_TOOLS) +
            len(CUSTOMER_SERVICE_TOOLS) +
            len(ALERT_TOOLS) +
            len(BUNDLE_TOOLS) +
            len(LISTING_TOOLS)
        )
        assert len(ALL_TOOLS) == expected_count

    def test_all_tools_unique_names(self):
        """All tools have unique names."""
        names = [t["name"] for t in ALL_TOOLS]
        assert len(names) == len(set(names)), "Duplicate tool names found"

    def test_all_tools_valid(self):
        """All tools pass schema validation."""
        for tool in ALL_TOOLS:
            errors = validate_tool_schema(tool)
            assert errors == [], f"Tool '{tool.get('name')}' validation errors: {errors}"

    def test_all_tools_property_types_valid(self):
        """All tools have valid property types."""
        for tool in ALL_TOOLS:
            props = tool["input_schema"]["properties"]
            errors = validate_property_types(props)
            assert errors == [], f"Tool '{tool['name']}' property errors: {errors}"
