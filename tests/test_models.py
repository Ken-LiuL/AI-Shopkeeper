"""Tests for Pydantic data models."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.models.product import Product, ProductStatus
from src.models.alert import Alert, AlertSeverity, AlertStatus
from src.models.bundle import Bundle, BundleItem


# ── Product ──────────────────────────────────────────────────────────────────

class TestProduct:
    def test_create_minimal(self):
        p = Product(product_id="P001", name="测试商品")
        assert p.product_id == "P001"
        assert p.status == ProductStatus.ACTIVE
        assert p.stock == 0
        assert p.monthly_sales == 0

    def test_create_full(self):
        p = Product(
            product_id="BP001", name="欧姆龙血压计",
            barcode="1234567890", category="血压计", brand="欧姆龙",
            cost_price=Decimal("198"), retail_price=Decimal("329"),
            stock=45, monthly_sales=62,
        )
        assert p.brand == "欧姆龙"
        assert p.retail_price == Decimal("329")

    def test_gross_margin(self):
        p = Product(product_id="P1", name="T", cost_price=Decimal("100"), retail_price=Decimal("200"))
        assert p.gross_margin == pytest.approx(0.5)

    def test_gross_margin_none_when_no_price(self):
        p = Product(product_id="P1", name="T")
        assert p.gross_margin is None

    def test_turnover_days(self):
        p = Product(product_id="P1", name="T", stock=60, monthly_sales=30)
        assert p.turnover_days == pytest.approx(60.0)

    def test_turnover_none_zero_sales(self):
        p = Product(product_id="P1", name="T", stock=10, monthly_sales=0)
        assert p.turnover_days is None

    def test_status_enum(self):
        for s in ["active", "inactive", "delisted"]:
            p = Product(product_id="P1", name="T", status=s)
            assert p.status == s

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError):
            Product(product_id="P1", name="T", status="deleted")

    def test_negative_stock_rejected(self):
        with pytest.raises(ValueError):
            Product(product_id="P1", name="T", stock=-1)

    def test_negative_price_rejected(self):
        with pytest.raises(ValueError):
            Product(product_id="P1", name="T", cost_price=Decimal("-10"))

    def test_product_id_max_length(self):
        with pytest.raises(ValueError):
            Product(product_id="A" * 33, name="T")


# ── Alert ────────────────────────────────────────────────────────────────────

class TestAlert:
    def test_create(self):
        a = Alert(alert_id="ALT001", alert_type="sales_drop", severity=AlertSeverity.WARNING)
        assert a.status == AlertStatus.PENDING
        assert a.severity == "warning"

    def test_severity_values(self):
        assert set(AlertSeverity) == {"critical", "warning", "info"}

    def test_status_values(self):
        assert set(AlertStatus) == {"pending", "acknowledged", "resolved", "ignored"}

    def test_metrics_default_empty(self):
        a = Alert(alert_id="A1", alert_type="t", severity="info")
        assert a.metrics == {}

    def test_invalid_severity(self):
        with pytest.raises(ValueError):
            Alert(alert_id="A1", alert_type="t", severity="urgent")


# ── Bundle ───────────────────────────────────────────────────────────────────

class TestBundle:
    def test_create(self):
        items = [
            BundleItem(product_id="BG001", name="血糖仪", unit_price=Decimal("99")),
            BundleItem(product_id="BG004", name="试纸", unit_price=Decimal("68")),
        ]
        b = Bundle(
            bundle_id="BDL001", name="血糖管理套装",
            products=items,
            original_price=Decimal("167"),
            bundle_price=Decimal("149"),
            discount_percent=10.78,
            confidence=0.72, lift=3.2,
        )
        assert b.savings == Decimal("18")
        assert len(b.products) == 2

    def test_savings_property(self):
        b = Bundle(
            bundle_id="B1", name="T",
            original_price=Decimal("200"), bundle_price=Decimal("180"),
        )
        assert b.savings == Decimal("20")

    def test_bundle_item_role(self):
        item = BundleItem(product_id="P1", name="主品", unit_price=Decimal("100"), role="主品")
        assert item.role == "主品"

    def test_default_status(self):
        b = Bundle(bundle_id="B1", name="T", original_price=Decimal("100"), bundle_price=Decimal("90"))
        assert b.status == "active"
