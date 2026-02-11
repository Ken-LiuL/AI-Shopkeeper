"""Tests for CustomerService API schemas."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Schema Tests
# ---------------------------------------------------------------------------

class TestChatRequest:
    """Tests for ChatRequest schema."""

    def test_request_with_required_fields(self):
        """Request accepts required fields."""
        from src.api.schemas import ChatRequest
        
        request = ChatRequest(
            session_id="session_001",
            message="有血压计吗",
        )
        assert request.session_id == "session_001"
        assert request.message == "有血压计吗"

    def test_request_with_history(self):
        """Request accepts conversation history."""
        from src.api.schemas import ChatRequest
        
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "亲，在的呢~"},
        ]
        request = ChatRequest(
            session_id="session_001",
            message="有血压计吗",
            conversation_history=history,
        )
        assert len(request.conversation_history) == 2

    def test_request_default_history(self):
        """Request defaults to empty history."""
        from src.api.schemas import ChatRequest
        
        request = ChatRequest(
            session_id="session_001",
            message="你好",
        )
        assert request.conversation_history == []


class TestChatResponse:
    """Tests for ChatResponse schema."""

    def test_response_with_all_fields(self):
        """Response accepts all fields."""
        from src.api.schemas import ChatResponse
        
        response = ChatResponse(
            session_id="session_001",
            reply="亲，推荐这款血压计~",
            intent="product_inquiry",
            sources=[{"product_id": "P001", "name": "血压计"}],
        )
        assert response.reply == "亲，推荐这款血压计~"
        assert response.intent == "product_inquiry"
        assert len(response.sources) == 1

    def test_response_optional_fields(self):
        """Response allows optional fields."""
        from src.api.schemas import ChatResponse
        
        response = ChatResponse(
            session_id="session_001",
            reply="亲，在的呢~",
        )
        assert response.intent is None
        assert response.sources == []


class TestSessionHistory:
    """Tests for SessionHistory schema."""

    def test_history_creation(self):
        """History can be created with messages."""
        from src.api.schemas import SessionHistory
        
        history = SessionHistory(
            session_id="session_001",
            messages=[
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "亲，在的呢~"},
            ],
        )
        assert history.session_id == "session_001"
        assert len(history.messages) == 2

    def test_history_default_empty(self):
        """History defaults to empty messages."""
        from src.api.schemas import SessionHistory
        
        history = SessionHistory(session_id="session_001")
        assert history.messages == []


# ---------------------------------------------------------------------------
# Additional Schema Tests
# ---------------------------------------------------------------------------

class TestAlertSchemas:
    """Tests for Alert-related schemas."""

    def test_alert_update_request(self):
        """AlertUpdateRequest validates status."""
        from src.api.schemas import AlertUpdateRequest
        
        # Valid statuses
        for status in ["acknowledged", "resolved", "ignored"]:
            request = AlertUpdateRequest(status=status)
            assert request.status == status


class TestBundleSchemas:
    """Tests for Bundle-related schemas."""

    def test_bundle_generate_request(self):
        """BundleGenerateRequest has optional fields."""
        from src.api.schemas import BundleGenerateRequest
        
        request = BundleGenerateRequest()
        assert request.min_support is None
        assert request.min_confidence is None
        assert request.max_bundles is None

    def test_bundle_generate_with_params(self):
        """BundleGenerateRequest accepts params."""
        from src.api.schemas import BundleGenerateRequest
        
        request = BundleGenerateRequest(
            min_support=0.01,
            min_confidence=0.5,
            max_bundles=10,
        )
        assert request.min_support == 0.01


class TestListingSchemas:
    """Tests for Listing-related schemas."""

    def test_listing_parse_request(self):
        """ListingParseRequest has url and platform."""
        from src.api.schemas import ListingParseRequest
        
        request = ListingParseRequest(url="https://example.com")
        assert request.url == "https://example.com"
        assert request.platform == "alibaba"

    def test_listing_parse_pdd(self):
        """ListingParseRequest supports pdd platform."""
        from src.api.schemas import ListingParseRequest
        
        request = ListingParseRequest(url="https://pdd.com", platform="pdd")
        assert request.platform == "pdd"


class TestProductSchemas:
    """Tests for Product-related schemas."""

    def test_product_create_request(self):
        """ProductCreateRequest has name as required."""
        from src.api.schemas import ProductCreateRequest
        
        request = ProductCreateRequest(name="测试商品")
        assert request.name == "测试商品"
        assert request.stock == 0
        assert request.status == "active"

    def test_product_update_request(self):
        """ProductUpdateRequest has all optional fields."""
        from src.api.schemas import ProductUpdateRequest
        
        request = ProductUpdateRequest()
        assert request.name is None
        assert request.retail_price is None


class TestDashboardSchemas:
    """Tests for Dashboard-related schemas."""

    def test_dashboard_overview(self):
        """DashboardOverview has default values."""
        from src.api.schemas import DashboardOverview
        
        overview = DashboardOverview()
        assert overview.total_products == 0
        assert overview.today_orders == 0
        assert overview.pending_alerts == 0

    def test_top_product(self):
        """TopProduct has required fields."""
        from decimal import Decimal
        from src.api.schemas import TopProduct
        
        product = TopProduct(
            product_id="P001",
            name="血压计",
            total_sales=100,
            revenue=Decimal("19900.00"),
        )
        assert product.product_id == "P001"


class TestPaginatedResponse:
    """Tests for PaginatedResponse schema."""

    def test_paginated_response_defaults(self):
        """PaginatedResponse has sensible defaults."""
        from src.api.schemas import PaginatedResponse
        
        response = PaginatedResponse()
        assert response.success is True
        assert response.data == []
        assert response.total == 0
        assert response.page == 1
        assert response.page_size == 20

    def test_paginated_response_with_data(self):
        """PaginatedResponse works with data."""
        from src.api.schemas import PaginatedResponse
        
        response = PaginatedResponse(
            data=[{"id": 1}, {"id": 2}],
            total=100,
            page=2,
            page_size=10,
        )
        assert len(response.data) == 2
        assert response.total == 100
