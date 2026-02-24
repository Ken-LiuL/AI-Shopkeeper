"""Tests for Database Skill — PostgreSQL CRUD operations."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.skills.database import (
    AlertCreate,
    AlertRecord,
    DatabaseSkill,
    Order,
    Product,
    ProductCreate,
    ProductUpdate,
    SalesStats,
    SelectionRun,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_pool():
    """Create a mock asyncpg pool with proper async context manager."""
    pool = MagicMock()
    conn = AsyncMock()

    # Create a proper async context manager
    class AsyncContextManager:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args):
            return False

    pool.acquire.return_value = AsyncContextManager()
    return pool, conn


@pytest.fixture
def db_skill_with_pool(mock_db_pool):
    """Create DatabaseSkill with mock pool."""
    pool, conn = mock_db_pool
    skill = DatabaseSkill(pool=pool)
    return skill, conn


@pytest.fixture
def db_skill_no_pool():
    """Create DatabaseSkill without pool."""
    return DatabaseSkill(pool=None)


# ---------------------------------------------------------------------------
# Product Model Tests
# ---------------------------------------------------------------------------


class TestProductModel:
    """Tests for Product Pydantic model."""

    def test_create_product(self):
        """Create Product with all fields."""
        product = Product(
            product_id="P001",
            name="鱼跃血压计",
            category="血压计",
            price=199.0,
            cost=80.0,
            stock=50,
            status="active",
            description="电子血压计",
        )
        assert product.product_id == "P001"
        assert product.price == 199.0

    def test_create_product_defaults(self):
        """Create Product with default values."""
        product = Product(product_id="P001", name="Test")
        assert product.status == "active"
        assert product.stock == 0


# ---------------------------------------------------------------------------
# Get Product Tests
# ---------------------------------------------------------------------------


class TestGetProduct:
    """Tests for get_product method."""

    async def test_get_product_found(self, db_skill_with_pool):
        """Get product returns Product when found."""
        skill, conn = db_skill_with_pool

        conn.fetchrow.return_value = {
            "product_id": "P001",
            "name": "鱼跃血压计",
            "category": "血压计",
            "price": 199.0,
            "cost": 80.0,
            "stock": 50,
            "status": "active",
            "description": "desc",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }

        product = await skill.get_product("P001")

        assert product is not None
        assert isinstance(product, Product)
        assert product.product_id == "P001"
        assert product.name == "鱼跃血压计"

    async def test_get_product_not_found(self, db_skill_with_pool):
        """Get product returns None when not found."""
        skill, conn = db_skill_with_pool
        conn.fetchrow.return_value = None

        product = await skill.get_product("NONEXISTENT")

        assert product is None

    async def test_get_product_no_pool(self, db_skill_no_pool):
        """Get product without pool returns None."""
        product = await db_skill_no_pool.get_product("P001")
        assert product is None


# ---------------------------------------------------------------------------
# List Products Tests
# ---------------------------------------------------------------------------


class TestListProducts:
    """Tests for list_products method."""

    async def test_list_products_default(self, db_skill_with_pool):
        """List products returns Product list."""
        skill, conn = db_skill_with_pool

        conn.fetch.return_value = [
            {
                "product_id": "P001",
                "name": "血压计",
                "category": "医疗器械",
                "price": 199.0,
                "cost": 80.0,
                "stock": 50,
                "status": "active",
                "description": "",
                "created_at": None,
                "updated_at": None,
            },
            {
                "product_id": "P002",
                "name": "体温计",
                "category": "医疗器械",
                "price": 29.0,
                "cost": 10.0,
                "stock": 100,
                "status": "active",
                "description": "",
                "created_at": None,
                "updated_at": None,
            },
        ]

        products = await skill.list_products()

        assert len(products) == 2
        assert all(isinstance(p, Product) for p in products)

    async def test_list_products_with_category(self, db_skill_with_pool):
        """List products filters by category."""
        skill, conn = db_skill_with_pool
        conn.fetch.return_value = []

        await skill.list_products(category="血压计", status="active")

        # Verify query was called with category filter
        conn.fetch.assert_called_once()
        call_args = conn.fetch.call_args
        assert "血压计" in call_args[0] or "血压计" in str(call_args)

    async def test_list_products_pagination(self, db_skill_with_pool):
        """List products supports limit and offset."""
        skill, conn = db_skill_with_pool
        conn.fetch.return_value = []

        await skill.list_products(limit=10, offset=20)

        # Verify limit and offset passed
        conn.fetch.assert_called_once()

    async def test_list_products_no_pool(self, db_skill_no_pool):
        """List products without pool returns empty list."""
        products = await db_skill_no_pool.list_products()
        assert products == []


# ---------------------------------------------------------------------------
# Create Product Tests
# ---------------------------------------------------------------------------


class TestCreateProduct:
    """Tests for create_product method."""

    async def test_create_product_success(self, db_skill_with_pool):
        """Create product returns new Product."""
        skill, conn = db_skill_with_pool

        conn.fetchrow.return_value = {
            "product_id": "P003",
            "name": "新血压计",
            "category": "血压计",
            "price": 299.0,
            "cost": 100.0,
            "stock": 30,
            "status": "active",
            "description": "desc",
            "created_at": datetime.now(),
            "updated_at": None,
        }

        data = ProductCreate(
            name="新血压计",
            category="血压计",
            price=299.0,
            cost=100.0,
            stock=30,
            description="desc",
        )

        product = await skill.create_product(data)

        assert product is not None
        assert product.name == "新血压计"
        assert product.price == 299.0

    async def test_create_product_no_pool(self, db_skill_no_pool):
        """Create product without pool returns None."""
        data = ProductCreate(name="Test", price=100.0)
        product = await db_skill_no_pool.create_product(data)
        assert product is None


# ---------------------------------------------------------------------------
# Update Product Tests
# ---------------------------------------------------------------------------


class TestUpdateProduct:
    """Tests for update_product method."""

    async def test_update_product_partial(self, db_skill_with_pool):
        """Update product with partial data."""
        skill, conn = db_skill_with_pool

        conn.fetchrow.return_value = {
            "product_id": "P001",
            "name": "血压计",
            "category": "血压计",
            "price": 179.0,  # Updated price
            "cost": 80.0,
            "stock": 50,
            "status": "active",
            "description": "",
            "created_at": None,
            "updated_at": datetime.now(),
        }

        data = ProductUpdate(price=179.0)
        product = await skill.update_product("P001", data)

        assert product is not None
        assert product.price == 179.0

    async def test_update_product_empty_data(self, db_skill_with_pool):
        """Update with empty data returns current product."""
        skill, conn = db_skill_with_pool

        conn.fetchrow.return_value = {
            "product_id": "P001",
            "name": "血压计",
            "category": "血压计",
            "price": 199.0,
            "cost": 80.0,
            "stock": 50,
            "status": "active",
            "description": "",
            "created_at": None,
            "updated_at": None,
        }

        data = ProductUpdate()  # No changes
        product = await skill.update_product("P001", data)

        # Should call get_product instead of update
        assert product is not None

    async def test_update_product_not_found(self, db_skill_with_pool):
        """Update non-existent product returns None."""
        skill, conn = db_skill_with_pool
        conn.fetchrow.return_value = None

        data = ProductUpdate(price=199.0)
        product = await skill.update_product("NONEXISTENT", data)

        assert product is None


# ---------------------------------------------------------------------------
# Delete Product Tests
# ---------------------------------------------------------------------------


class TestDeleteProduct:
    """Tests for delete_product method (soft delete)."""

    async def test_delete_product_success(self, db_skill_with_pool):
        """Delete product sets status to discontinued."""
        skill, conn = db_skill_with_pool
        conn.execute.return_value = "UPDATE 1"

        success = await skill.delete_product("P001")

        assert success is True

    async def test_delete_product_not_found(self, db_skill_with_pool):
        """Delete non-existent product returns False."""
        skill, conn = db_skill_with_pool
        conn.execute.return_value = "UPDATE 0"

        success = await skill.delete_product("NONEXISTENT")

        assert success is False

    async def test_delete_product_no_pool(self, db_skill_no_pool):
        """Delete product without pool returns False."""
        success = await db_skill_no_pool.delete_product("P001")
        assert success is False


# ---------------------------------------------------------------------------
# Order Tests
# ---------------------------------------------------------------------------


class TestGetOrders:
    """Tests for get_orders method."""

    async def test_get_orders_default(self, db_skill_with_pool):
        """Get orders returns Order list."""
        skill, conn = db_skill_with_pool

        conn.fetch.return_value = [
            {
                "order_id": "O001",
                "product_id": "P001",
                "product_name": "血压计",
                "quantity": 2,
                "unit_price": 199.0,
                "total_amount": 398.0,
                "order_date": datetime.now(),
                "status": "completed",
            },
        ]

        orders = await skill.get_orders()

        assert len(orders) == 1
        assert isinstance(orders[0], Order)
        assert orders[0].order_id == "O001"

    async def test_get_orders_by_product(self, db_skill_with_pool):
        """Get orders filters by product_id."""
        skill, conn = db_skill_with_pool
        conn.fetch.return_value = []

        await skill.get_orders(product_id="P001")

        conn.fetch.assert_called_once()

    async def test_get_orders_by_date_range(self, db_skill_with_pool):
        """Get orders filters by date range."""
        skill, conn = db_skill_with_pool
        conn.fetch.return_value = []

        await skill.get_orders(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 11),
        )

        conn.fetch.assert_called_once()


# ---------------------------------------------------------------------------
# Daily Sales Tests
# ---------------------------------------------------------------------------


class TestGetDailySales:
    """Tests for get_daily_sales method (for Prophet training)."""

    async def test_get_daily_sales(self, db_skill_with_pool):
        """Get daily sales returns ds/y format."""
        skill, conn = db_skill_with_pool

        conn.fetch.return_value = [
            {"ds": date(2026, 2, 1), "y": 10},
            {"ds": date(2026, 2, 2), "y": 12},
            {"ds": date(2026, 2, 3), "y": 8},
        ]

        sales = await skill.get_daily_sales("P001", days=30)

        assert len(sales) == 3
        assert "ds" in sales[0]
        assert "y" in sales[0]


# ---------------------------------------------------------------------------
# Sales Stats Tests
# ---------------------------------------------------------------------------


class TestGetSalesStats:
    """Tests for get_sales_stats method."""

    async def test_get_sales_stats(self, db_skill_with_pool):
        """Get sales stats returns aggregated statistics."""
        skill, conn = db_skill_with_pool

        conn.fetch.return_value = [
            {
                "product_id": "P001",
                "product_name": "血压计",
                "total_quantity": 100,
                "total_revenue": 19900.0,
                "total_cost": 8000.0,
                "gross_profit": 11900.0,
                "gross_margin": 0.598,
                "order_count": 80,
            },
        ]

        stats = await skill.get_sales_stats()

        assert len(stats) == 1
        assert isinstance(stats[0], SalesStats)
        assert stats[0].gross_margin == 0.598


# ---------------------------------------------------------------------------
# Alert CRUD Tests
# ---------------------------------------------------------------------------


class TestAlertCRUD:
    """Tests for alert-related methods."""

    async def test_create_alert(self, db_skill_with_pool):
        """Create alert returns AlertRecord."""
        skill, conn = db_skill_with_pool

        conn.fetchrow.return_value = {
            "alert_id": 1,
            "product_id": "P001",
            "alert_type": "sales_drop",
            "severity": "critical",
            "title": "销量下降",
            "description": "销量下降70%",
            "root_cause": "竞品降价",
            "suggestion": "考虑调价",
            "status": "open",
            "created_at": datetime.now(),
            "resolved_at": None,
        }

        data = AlertCreate(
            product_id="P001",
            alert_type="sales_drop",
            severity="critical",
            title="销量下降",
            description="销量下降70%",
        )

        alert = await skill.create_alert(data)

        assert alert is not None
        assert isinstance(alert, AlertRecord)
        assert alert.severity == "critical"

    async def test_get_alerts(self, db_skill_with_pool):
        """Get alerts returns AlertRecord list."""
        skill, conn = db_skill_with_pool

        conn.fetch.return_value = [
            {
                "alert_id": 1,
                "product_id": "P001",
                "alert_type": "sales_drop",
                "severity": "critical",
                "title": "销量下降",
                "description": "desc",
                "root_cause": "",
                "suggestion": "",
                "status": "open",
                "created_at": datetime.now(),
                "resolved_at": None,
            },
        ]

        alerts = await skill.get_alerts(status="open", severity="critical")

        assert len(alerts) == 1
        assert alerts[0].alert_type == "sales_drop"

    async def test_resolve_alert(self, db_skill_with_pool):
        """Resolve alert updates status."""
        skill, conn = db_skill_with_pool
        conn.execute.return_value = "UPDATE 1"

        success = await skill.resolve_alert(1)

        assert success is True

    async def test_acknowledge_alert(self, db_skill_with_pool):
        """Acknowledge alert updates status."""
        skill, conn = db_skill_with_pool
        conn.execute.return_value = "UPDATE 1"

        success = await skill.acknowledge_alert(1)

        assert success is True


# ---------------------------------------------------------------------------
# Selection Run Tests
# ---------------------------------------------------------------------------


class TestSelectionRun:
    """Tests for selection run methods."""

    async def test_create_selection_run(self, db_skill_with_pool):
        """Create selection run returns SelectionRun."""
        skill, conn = db_skill_with_pool

        conn.fetchrow.return_value = {
            "run_id": 1,
            "trigger": "scheduled",
            "status": "running",
            "total_evaluated": 0,
            "recommended_count": 0,
            "top_score": 0.0,
            "results": None,
            "started_at": datetime.now(),
            "completed_at": None,
        }

        run = await skill.create_selection_run(trigger="scheduled")

        assert run is not None
        assert isinstance(run, SelectionRun)
        assert run.status == "running"

    async def test_complete_selection_run(self, db_skill_with_pool):
        """Complete selection run updates results."""
        skill, conn = db_skill_with_pool
        conn.execute.return_value = "UPDATE 1"

        success = await skill.complete_selection_run(
            run_id=1,
            total_evaluated=10,
            recommended_count=5,
            top_score=87.5,
            results={"recommendations": []},
        )

        assert success is True

    async def test_fail_selection_run(self, db_skill_with_pool):
        """Fail selection run updates status."""
        skill, conn = db_skill_with_pool
        conn.execute.return_value = "UPDATE 1"

        success = await skill.fail_selection_run(run_id=1, error="timeout")

        assert success is True

    async def test_get_latest_selection_runs(self, db_skill_with_pool):
        """Get latest selection runs returns list."""
        skill, conn = db_skill_with_pool

        conn.fetch.return_value = [
            {
                "run_id": 2,
                "trigger": "manual",
                "status": "completed",
                "total_evaluated": 10,
                "recommended_count": 5,
                "top_score": 87.5,
                "results": None,
                "started_at": datetime.now(),
                "completed_at": datetime.now(),
            },
            {
                "run_id": 1,
                "trigger": "scheduled",
                "status": "completed",
                "total_evaluated": 8,
                "recommended_count": 4,
                "top_score": 82.0,
                "results": None,
                "started_at": datetime.now(),
                "completed_at": datetime.now(),
            },
        ]

        runs = await skill.get_latest_selection_runs(limit=10)

        assert len(runs) == 2
        assert runs[0].run_id == 2  # Most recent first


# ---------------------------------------------------------------------------
# No Pool Tests
# ---------------------------------------------------------------------------


class TestNoPoolOperations:
    """Tests for operations without database pool."""

    async def test_fetch_no_pool_returns_empty(self, db_skill_no_pool):
        """Fetch without pool returns empty list."""
        products = await db_skill_no_pool.list_products()
        assert products == []

        orders = await db_skill_no_pool.get_orders()
        assert orders == []

        alerts = await db_skill_no_pool.get_alerts()
        assert alerts == []

    async def test_execute_no_pool_returns_empty(self, db_skill_no_pool):
        """Execute without pool returns empty string."""
        # This is tested implicitly by delete_product
        success = await db_skill_no_pool.delete_product("P001")
        assert success is False

    async def test_create_no_pool_returns_none(self, db_skill_no_pool):
        """Create operations without pool return None."""
        alert = await db_skill_no_pool.create_alert(
            AlertCreate(product_id="P001", alert_type="test")
        )
        assert alert is None

        run = await db_skill_no_pool.create_selection_run()
        assert run is None
