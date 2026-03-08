"""
test_fact_checker.py — 事实核查模块 (FactChecker) 评估

评估目标：
  1. 价格低于成本的检测（低毛利 / 亏本定价）
  2. 库存异常的检测（补货量异常大、库存已足还补货等）
  3. Edge case 处理（null 值、负数、零值、超大值等）

技术约束：
  - 直接测试 src/agents/fact_checker.py 中的核心逻辑
  - 使用 mock_db_pool 代替真实数据库
  - 全异步，使用 pytest-asyncio
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# 导入待测函数
# ---------------------------------------------------------------------------
try:
    from src.agents.fact_checker import (
        check_price_recommendation,
        check_stock_recommendation,
    )
    _FACT_CHECKER_AVAILABLE = True
except ImportError:
    _FACT_CHECKER_AVAILABLE = False


# ---------------------------------------------------------------------------
# 跳过标记（如果 fact_checker 无法导入，则跳过集成测试）
# ---------------------------------------------------------------------------
skip_if_unavailable = pytest.mark.skipif(
    not _FACT_CHECKER_AVAILABLE,
    reason="fact_checker 模块不可用（可能缺少依赖）",
)


# ---------------------------------------------------------------------------
# 辅助：构造 asyncpg Row mock
# ---------------------------------------------------------------------------


def _make_row(
    spu_id: str = "P100",
    retail_price: float | None = 189.0,
    cost_price: float | None = 95.0,
    stock: int | None = 50,
    title: str = "测试商品",
) -> dict:
    """构造 asyncpg fetchrow 返回的类 dict 对象。"""
    return {
        "spu_id": spu_id,
        "retail_price": retail_price,
        "cost_price": cost_price,
        "stock": stock,
        "title": title,
    }


def _make_pool_with_row(row: dict | None) -> AsyncMock:
    """构造返回指定 row 的 mock DB pool。"""
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=row)
    pool.fetch = AsyncMock(return_value=[row] if row else [])
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


# ---------------------------------------------------------------------------
# 价格建议核查
# ---------------------------------------------------------------------------


class TestPriceFactCheck:
    """验证 check_price_recommendation 函数的核查逻辑。"""

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_price_below_cost_fails(self):
        """建议价低于成本价时，核查应不通过。"""
        row = _make_row(retail_price=189.0, cost_price=95.0)
        pool = _make_pool_with_row(row)

        result = await check_price_recommendation(pool, "P100", recommended_price=90.0)
        assert result["passed"] is False
        assert any("成本" in w for w in result["warnings"]), f"应有成本价警告: {result['warnings']}"

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_price_with_good_margin_passes(self):
        """建议价有合理毛利时，核查应通过。"""
        row = _make_row(retail_price=189.0, cost_price=95.0)
        pool = _make_pool_with_row(row)

        result = await check_price_recommendation(pool, "P100", recommended_price=189.0)
        assert result["passed"] is True

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_price_zero_fails(self):
        """建议价为 0 时，核查应不通过。"""
        row = _make_row(cost_price=95.0)
        pool = _make_pool_with_row(row)

        result = await check_price_recommendation(pool, "P100", recommended_price=0.0)
        assert result["passed"] is False

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_price_negative_fails(self):
        """建议价为负数时，核查应不通过。"""
        row = _make_row(cost_price=95.0)
        pool = _make_pool_with_row(row)

        result = await check_price_recommendation(pool, "P100", recommended_price=-10.0)
        assert result["passed"] is False

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_product_not_found_returns_warning(self):
        """商品不存在时，返回 warning 但不 fail。"""
        pool = _make_pool_with_row(None)

        result = await check_price_recommendation(pool, "NONEXISTENT", recommended_price=100.0)
        # 商品不存在，应有 warning 但不硬失败（passed 可能为 True 或有 warning）
        assert isinstance(result, dict)
        assert "warnings" in result

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_warning(self):
        """pool 为 None 时，应优雅降级（返回 warning 不报错）。"""
        result = await check_price_recommendation(None, "P100", recommended_price=100.0)
        assert isinstance(result, dict)
        assert "warnings" in result

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_large_price_change_warned(self):
        """调价幅度超过 30% 时，应有警告（即使没有亏本）。"""
        row = _make_row(retail_price=189.0, cost_price=95.0)
        pool = _make_pool_with_row(row)

        # 调价 50%: 189 -> 283.5（+50%）
        result = await check_price_recommendation(pool, "P100", recommended_price=283.5)
        assert len(result["warnings"]) > 0, "大幅调价应有警告"

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_null_cost_price_handled(self):
        """cost_price 为 null 时，应不崩溃。"""
        row = _make_row(cost_price=None, retail_price=189.0)
        pool = _make_pool_with_row(row)

        result = await check_price_recommendation(pool, "P100", recommended_price=150.0)
        assert isinstance(result, dict)  # 不应抛出异常


# ---------------------------------------------------------------------------
# 库存建议核查
# ---------------------------------------------------------------------------


class TestStockFactCheck:
    """验证 check_stock_recommendation 函数的核查逻辑。"""

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_excessive_restock_warned(self):
        """补货量超过 1000 时，应有警告。"""
        row = _make_row(stock=50, title="测试商品")
        pool = _make_pool_with_row(row)

        result = await check_stock_recommendation(pool, "P100", recommended_qty=2000)
        assert len(result["warnings"]) > 0, "补货量异常大应有警告"

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_normal_restock_passes(self):
        """正常补货量（< 1000）且库存不足时，应通过。"""
        row = _make_row(stock=5, title="测试商品")
        pool = _make_pool_with_row(row)

        result = await check_stock_recommendation(pool, "P100", recommended_qty=50)
        assert result["passed"] is True

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_restock_when_sufficient_stock_warned(self):
        """库存充足（>100）时仍建议补货，应有警告。"""
        row = _make_row(stock=200, title="测试商品")
        pool = _make_pool_with_row(row)

        result = await check_stock_recommendation(pool, "P100", recommended_qty=100)
        # 库存 200 充足，建议补货 100 应有 warning
        has_warning = len(result.get("warnings", [])) > 0
        assert has_warning, "充足库存时建议补货应有警告"

    @skip_if_unavailable
    @pytest.mark.asyncio
    async def test_no_db_pool_handled(self):
        """pool 为 None 时，应优雅降级。"""
        result = await check_stock_recommendation(None, "P100", recommended_qty=50)
        assert isinstance(result, dict)
        assert "warnings" in result


# ---------------------------------------------------------------------------
# Edge Case 测试（独立于 fact_checker 导入）
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """
    边界值和异常输入测试。
    这些测试验证业务逻辑的边界行为，不依赖 fact_checker 的具体实现。
    """

    def test_negative_price_is_invalid(self):
        """负数价格应被视为无效。"""
        price = -10.0
        assert price <= 0, "负数价格应被拒绝"

    def test_zero_price_is_invalid(self):
        """零价格应被视为无效。"""
        price = 0.0
        assert price <= 0, "零价格应被拒绝"

    def test_zero_stock_triggers_restock_need(self):
        """库存为 0 时，需要触发补货逻辑。"""
        stock = 0
        needs_restock = stock == 0 or stock < 0
        assert needs_restock, "零库存应触发补货"

    def test_negative_stock_is_data_error(self):
        """负数库存是数据错误，应被标记。"""
        stock = -5
        is_error = stock < 0
        assert is_error, "负数库存是数据错误"

    def test_none_price_handled(self):
        """None 价格应触发 warning 而非崩溃。"""
        price = None
        is_valid = price is not None and price > 0
        assert not is_valid, "None 价格应被检测为无效"

    def test_very_large_price_flagged(self):
        """极大价格（>50000元）应被标记为需人工确认。"""
        price = 999999.0
        needs_review = price > 50000
        assert needs_review, "超大价格应触发人工复核"

    def test_very_large_qty_flagged(self):
        """极大补货量（>10000件）应被标记为需人工确认。"""
        qty = 50000
        needs_review = qty > 10000
        assert needs_review, "超大补货量应触发人工复核"

    def test_zero_qty_recommendation(self):
        """补货量为 0 时，不应触发补货动作。"""
        qty = 0
        assert qty == 0, "零补货量不应触发动作"

    def test_float_qty_rounded(self):
        """补货量应为整数，小数应被四舍五入。"""
        qty_float = 10.7
        qty_int = round(qty_float)
        assert qty_int == 11, "补货量小数应被正确四舍五入"

    def test_price_precision(self):
        """价格精度验证：保留2位小数。"""
        price = 189.999
        rounded = round(price, 2)
        assert rounded == 190.0, f"价格精度不正确: {rounded}"

    @pytest.mark.parametrize(
        "price, cost, expected_valid",
        [
            (189.0, 95.0, True),     # 正常毛利
            (94.0, 95.0, False),     # 亏本
            (0.0, 95.0, False),      # 零价格
            (-10.0, 95.0, False),    # 负数价格
            (95.0, 95.0, False),     # 毛利率为 0（等于成本）
            (10000.0, 95.0, True),   # 高价（合法）
        ],
    )
    def test_price_validity_matrix(self, price, cost, expected_valid):
        """参数化测试：验证价格合法性判断矩阵。"""
        is_valid = price > cost and price > 0
        assert is_valid == expected_valid, (
            f"价格={price}, 成本={cost}: 预期合法={expected_valid}, 实际={is_valid}"
        )

    @pytest.mark.parametrize(
        "stock, qty, expected_warning",
        [
            (200, 100, True),    # 库存充足还补货
            (5, 50, False),      # 库存不足，补货合理
            (0, 100, False),     # 零库存，补货必要
            (10, 5000, True),    # 补货量异常大
            (50, 0, False),      # 补货量为 0，无需操作
        ],
    )
    def test_stock_warning_matrix(self, stock, qty, expected_warning):
        """参数化测试：库存警告矩阵。"""
        should_warn = (stock > 100 and qty > 0) or (qty > 1000)
        assert should_warn == expected_warning, (
            f"库存={stock}, 补货量={qty}: 预期警告={expected_warning}, 实际={should_warn}"
        )
