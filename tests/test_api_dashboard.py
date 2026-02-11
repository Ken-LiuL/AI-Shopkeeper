"""Tests for Dashboard API schemas and route logic."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.api.schemas import APIResponse, DashboardOverview, SalesTrendPoint, TopProduct


# ── Schema Tests ─────────────────────────────────────────────────────────────

class TestDashboardOverview:
    def test_defaults(self):
        o = DashboardOverview()
        assert o.total_products == 0
        assert o.today_orders == 0
        assert o.pending_alerts == 0
        assert o.pending_tasks == 0

    def test_with_values(self):
        o = DashboardOverview(total_products=100, today_orders=50, pending_alerts=3, pending_tasks=2)
        assert o.total_products == 100
        assert o.pending_tasks == 2

    def test_serialization(self):
        o = DashboardOverview(total_products=42)
        d = o.model_dump()
        assert d["total_products"] == 42
        assert "pending_alerts" in d


class TestSalesTrendPoint:
    def test_creation(self):
        p = SalesTrendPoint(date="2024-01-01", quantity=100, revenue=Decimal("5000.50"))
        assert p.date == "2024-01-01"
        assert p.quantity == 100
        assert p.revenue == Decimal("5000.50")

    def test_serialization(self):
        p = SalesTrendPoint(date="2024-01-01", quantity=10, revenue=Decimal("100"))
        d = p.model_dump()
        assert d["date"] == "2024-01-01"
        assert d["quantity"] == 10


class TestTopProduct:
    def test_creation(self):
        t = TopProduct(product_id="P001", name="血压计", total_sales=300, revenue=Decimal("50000"))
        assert t.product_id == "P001"
        assert t.name == "血压计"
        assert t.total_sales == 300

    def test_serialization(self):
        t = TopProduct(product_id="P1", name="T", total_sales=1, revenue=Decimal("10"))
        d = t.model_dump()
        assert set(d.keys()) == {"product_id", "name", "total_sales", "revenue"}


class TestAPIResponseWrapper:
    def test_success_default(self):
        r = APIResponse(data=DashboardOverview())
        assert r.success is True
        assert r.data.total_products == 0

    def test_with_message(self):
        r = APIResponse(data=None, message="error", success=False)
        assert r.success is False
        assert r.message == "error"

    def test_with_list_data(self):
        points = [
            SalesTrendPoint(date="2024-01-01", quantity=10, revenue=Decimal("100")),
            SalesTrendPoint(date="2024-01-02", quantity=20, revenue=Decimal("200")),
        ]
        r = APIResponse(data=points)
        assert len(r.data) == 2

    def test_with_top_products(self):
        products = [
            TopProduct(product_id="P1", name="A", total_sales=100, revenue=Decimal("1000")),
        ]
        r = APIResponse(data=products)
        assert r.data[0].product_id == "P1"


# ── DashboardOverview edge cases ─────────────────────────────────────────────

class TestDashboardOverviewEdgeCases:
    def test_large_numbers(self):
        o = DashboardOverview(total_products=999999, today_orders=100000)
        assert o.total_products == 999999

    def test_zero_values(self):
        o = DashboardOverview(total_products=0, today_orders=0, pending_alerts=0, pending_tasks=0)
        d = o.model_dump()
        assert all(v == 0 for v in d.values())
