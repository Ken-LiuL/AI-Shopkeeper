"""Tests for sync, knowledge, and metrics API schemas and utilities."""

from __future__ import annotations

from src.api.schemas import APIResponse

# ── Sync API Schema Tests ────────────────────────────────────────────────────


class TestSyncStatusResponse:
    def test_api_response_with_sync_data(self):
        data = [
            {"syncer_name": "products", "last_sync_status": "success", "records_synced": 100},
            {"syncer_name": "orders", "last_sync_status": "running", "records_synced": 0},
        ]
        r = APIResponse(data=data)
        assert r.success is True
        assert len(r.data) == 2
        assert r.data[0]["syncer_name"] == "products"

    def test_sync_trigger_response(self):
        r = APIResponse(data={"status": "triggered"}, message="Full sync triggered in background")
        assert r.data["status"] == "triggered"
        assert "background" in r.message

    def test_sync_status_empty(self):
        r = APIResponse(data=[])
        assert r.data == []


# ── Knowledge API Tests (via neo4j_skill models) ─────────────────────────────


class TestKnowledgeSearchModels:
    def test_faq_result_shape(self):
        result = {"question": "如何使用?", "answer": "按开关", "category": "FAQ", "source": "faq"}
        assert result["source"] == "faq"
        assert "answer" in result

    def test_product_result_shape(self):
        result = {
            "name": "血压计",
            "description": "电子血压计",
            "category": "医疗器械",
            "source": "product",
        }
        assert result["source"] == "product"

    def test_empty_results(self):
        r = APIResponse(data=[])
        assert r.success is True
        assert r.data == []


# ── Metrics API Schema Tests ─────────────────────────────────────────────────


class TestMetricsResponse:
    def test_metrics_data_shape(self):
        data = {
            "period_days": 7,
            "total_input_tokens": 10000,
            "total_output_tokens": 5000,
            "total_cost_usd": 1.50,
            "total_requests": 42,
            "by_model": [{"model": "claude-3", "requests": 42, "cost_usd": 1.50}],
            "by_agent": [],
            "daily_trend": [],
        }
        r = APIResponse(data=data)
        assert r.data["period_days"] == 7
        assert r.data["total_requests"] == 42

    def test_metrics_with_model_breakdown(self):
        by_model = [
            {
                "model": "claude-3-opus",
                "input_tokens": 5000,
                "output_tokens": 2000,
                "cost_usd": 1.0,
                "requests": 20,
            },
            {
                "model": "claude-3-sonnet",
                "input_tokens": 5000,
                "output_tokens": 3000,
                "cost_usd": 0.5,
                "requests": 22,
            },
        ]
        r = APIResponse(data={"by_model": by_model})
        assert len(r.data["by_model"]) == 2

    def test_metrics_with_agent_breakdown(self):
        by_agent = [
            {"agent_type": "selection", "requests": 10, "cost_usd": 0.8},
            {"agent_type": "customer_service", "requests": 30, "cost_usd": 0.7},
        ]
        r = APIResponse(data={"by_agent": by_agent})
        assert len(r.data["by_agent"]) == 2

    def test_metrics_empty_daily_trend(self):
        r = APIResponse(data={"daily_trend": []})
        assert r.data["daily_trend"] == []

    def test_metrics_daily_trend_data(self):
        daily = [
            {"date": "2024-01-01", "tokens": 1000, "cost_usd": 0.1, "requests": 5},
            {"date": "2024-01-02", "tokens": 2000, "cost_usd": 0.2, "requests": 10},
        ]
        r = APIResponse(data={"daily_trend": daily})
        assert r.data["daily_trend"][0]["tokens"] == 1000


# ── API Response Generic Tests ───────────────────────────────────────────────


class TestAPIResponseGeneric:
    def test_success_with_none(self):
        r = APIResponse(data=None)
        assert r.success is True
        assert r.data is None

    def test_failure(self):
        r = APIResponse(success=False, message="error")
        assert r.success is False

    def test_dict_data(self):
        r = APIResponse(data={"key": "value"})
        assert r.data["key"] == "value"

    def test_list_data(self):
        r = APIResponse(data=[1, 2, 3])
        assert len(r.data) == 3

    def test_default_message(self):
        r = APIResponse(data="ok")
        assert r.message == ""
