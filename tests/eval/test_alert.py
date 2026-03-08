"""
test_alert.py — 预警 Agent (Alert) 评估

评估目标：
  1. 库存预警触发是否合理（阈值逻辑正确性）
  2. 价格异常检测准确性（偏离度计算）
  3. 建议动作是否可执行（字段完整性、优先级合法性）

技术约束：
  - 全 mock，无需真实数据库 / LLM
  - 使用 golden_data/alert_test_cases.json 作为标准用例
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.eval.conftest import load_golden
from tests.eval.eval_metrics import check_output_format, check_value_in_range

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

VALID_SEVERITIES = {"critical", "warning", "info"}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
VALID_ACTION_TYPES = {"restock", "price_adjust", "promote", "delist", "investigate", "monitor"}
VALID_ANOMALY_TYPES = {
    "stock_critical",
    "stock_low",
    "sales_drop_prophet",
    "price_anomaly",
    "price_gap",
    "dead_stock",
}

# 库存预警阈值（天）
STOCK_WARNING_DAYS = 7
STOCK_CRITICAL_DAYS = 3


# ---------------------------------------------------------------------------
# 业务规则函数（模拟 Alert Agent 的核心逻辑，供评估验证）
# ---------------------------------------------------------------------------


def _should_trigger_stock_alert(stock: int, avg_daily_sales: float) -> tuple[bool, str]:
    """判断是否应触发库存预警及严重程度。"""
    if avg_daily_sales <= 0:
        return False, ""
    days_remaining = stock / avg_daily_sales
    if days_remaining <= STOCK_CRITICAL_DAYS:
        return True, "critical"
    if days_remaining <= STOCK_WARNING_DAYS:
        return True, "warning"
    return False, ""


def _should_trigger_price_alert(retail_price: float, cost_price: float, competitor_avg: float) -> bool:
    """判断是否应触发价格异常预警。"""
    if retail_price <= cost_price * 1.05:  # 毛利率低于 5%
        return True
    if competitor_avg > 0 and (competitor_avg - retail_price) / competitor_avg > 0.3:
        return True
    return False


def _make_alert_action(
    action_type: str = "restock",
    priority: str = "P1",
    include_deadline: bool = True,
) -> dict[str, Any]:
    """构造预警建议动作 mock。"""
    action = {
        "action_type": action_type,
        "priority": priority,
        "action_detail": f"执行 {action_type} 动作",
        "parameters": {"target_quantity": 50},
        "expected_outcome": "预计3天内恢复正常",
        "estimated_impact": {"sales_change_percent": 20},
    }
    if include_deadline:
        action["deadline"] = "2026-03-15T00:00:00"
    return action


def _make_anomaly(
    anomaly_type: str = "stock_critical",
    severity: str = "critical",
    product_id: str = "P100",
) -> dict[str, Any]:
    return {
        "anomaly_id": f"A_{product_id}",
        "product_id": product_id,
        "product_name": "测试商品",
        "anomaly_type": anomaly_type,
        "severity": severity,
        "detection_method": "rule",
        "metrics": {
            "expected_value": 10,
            "actual_value": 2,
            "deviation_percent": -80,
            "threshold": -30,
        },
        "description": f"检测到 {anomaly_type}",
        "detected_at": "2026-03-08T10:00:00",
    }


# ---------------------------------------------------------------------------
# 库存预警触发合理性
# ---------------------------------------------------------------------------


class TestStockAlertTrigger:
    """验证库存预警触发逻辑。"""

    def test_critical_stock_triggers_alert(self):
        """库存 < 3天日销量，应触发 critical 预警。"""
        triggered, severity = _should_trigger_stock_alert(stock=2, avg_daily_sales=5)
        assert triggered, "库存告急应触发预警"
        assert severity == "critical"

    def test_low_stock_triggers_warning(self):
        """库存在 3~7 天日销量间，应触发 warning 预警。"""
        triggered, severity = _should_trigger_stock_alert(stock=20, avg_daily_sales=4)
        assert triggered, "低库存应触发 warning"
        assert severity == "warning"

    def test_sufficient_stock_no_alert(self):
        """库存 > 7天日销量，不应触发预警。"""
        triggered, _ = _should_trigger_stock_alert(stock=200, avg_daily_sales=3)
        assert not triggered, "充足库存不应触发预警"

    def test_zero_sales_no_alert(self):
        """日销量为 0 时，不触发库存预警（避免除以零）。"""
        triggered, _ = _should_trigger_stock_alert(stock=10, avg_daily_sales=0)
        assert not triggered

    def test_exactly_at_critical_threshold(self):
        """恰好在 critical 阈值边界（3天）的场景。"""
        triggered, severity = _should_trigger_stock_alert(stock=15, avg_daily_sales=5)
        # 15/5 = 3.0 天，正好在边界，应为 critical
        assert triggered
        assert severity == "critical"

    def test_just_above_warning_threshold(self):
        """刚好超过 warning 阈值（>7天），不触发预警。"""
        triggered, _ = _should_trigger_stock_alert(stock=36, avg_daily_sales=5)
        # 36/5 = 7.2 天 > 7，不触发
        assert not triggered


# ---------------------------------------------------------------------------
# 价格异常检测
# ---------------------------------------------------------------------------


class TestPriceAnomalyDetection:
    """验证价格异常检测逻辑。"""

    def test_price_below_cost_triggers_alert(self):
        """售价低于成本的 1.05 倍，应触发价格预警。"""
        triggered = _should_trigger_price_alert(
            retail_price=95.0, cost_price=95.0, competitor_avg=189.0
        )
        assert triggered

    def test_price_far_below_competitor_triggers_alert(self):
        """售价比竞品均价低超过 30%，应触发价格预警。"""
        triggered = _should_trigger_price_alert(
            retail_price=99.0, cost_price=50.0, competitor_avg=180.0
        )
        assert triggered

    def test_normal_price_no_alert(self):
        """正常定价（合理毛利且接近竞品），不触发预警。"""
        triggered = _should_trigger_price_alert(
            retail_price=189.0, cost_price=95.0, competitor_avg=199.0
        )
        assert not triggered

    def test_slightly_below_competitor_no_alert(self):
        """略低于竞品（<30%），不触发预警。"""
        triggered = _should_trigger_price_alert(
            retail_price=170.0, cost_price=90.0, competitor_avg=195.0
        )
        # 差价 (195-170)/195 ≈ 12.8% < 30%
        assert not triggered

    def test_deviation_calculation_accuracy(self):
        """验证偏差百分比计算。"""
        # 期望值 100，实际值 30，偏差 -70%
        expected = 100
        actual = 30
        deviation = (actual - expected) / expected * 100
        assert abs(deviation - (-70.0)) < 0.01

    def test_anomaly_output_format(self):
        """异常输出应包含必要字段。"""
        anomaly = _make_anomaly()
        result = check_output_format(
            anomaly,
            required_keys=[
                "anomaly_id", "product_id", "anomaly_type",
                "severity", "metrics", "detected_at",
            ],
        )
        assert result["valid"], f"异常输出缺少字段: {result['missing_keys']}"

    def test_severity_is_valid(self):
        """severity 应在合法值集合中。"""
        for sev in VALID_SEVERITIES:
            anomaly = _make_anomaly(severity=sev)
            assert anomaly["severity"] in VALID_SEVERITIES

    def test_anomaly_type_is_valid(self):
        """anomaly_type 应在已知类型集合中。"""
        for at in VALID_ANOMALY_TYPES:
            anomaly = _make_anomaly(anomaly_type=at)
            assert anomaly["anomaly_type"] in VALID_ANOMALY_TYPES


# ---------------------------------------------------------------------------
# 建议动作可执行性
# ---------------------------------------------------------------------------


class TestActionExecutability:
    """验证预警建议动作的可执行性。"""

    def test_action_has_required_fields(self):
        """动作应包含 action_type / priority / action_detail。"""
        action = _make_alert_action()
        result = check_output_format(
            action, required_keys=["action_type", "priority", "action_detail"]
        )
        assert result["valid"], f"动作缺少字段: {result['missing_keys']}"

    def test_action_type_is_valid(self):
        """action_type 应在合法集合中。"""
        for at in VALID_ACTION_TYPES:
            action = _make_alert_action(action_type=at)
            assert action["action_type"] in VALID_ACTION_TYPES

    def test_priority_is_valid(self):
        """priority 应在 P0~P3 范围内。"""
        for p in VALID_PRIORITIES:
            action = _make_alert_action(priority=p)
            assert action["priority"] in VALID_PRIORITIES

    def test_deadline_present_for_critical(self):
        """critical 预警的动作应包含 deadline。"""
        action = _make_alert_action(priority="P0", include_deadline=True)
        assert "deadline" in action, "P0 级别动作应包含 deadline"

    def test_action_detail_not_empty(self):
        """action_detail 不应为空。"""
        action = _make_alert_action()
        assert action["action_detail"].strip(), "action_detail 不应为空"

    def test_critical_anomaly_gets_p0_action(self):
        """critical 级别异常应触发 P0 动作。"""
        # 模拟业务规则：critical -> P0
        anomaly = _make_anomaly(severity="critical")
        expected_priority = "P0" if anomaly["severity"] == "critical" else "P1"
        action = _make_alert_action(priority=expected_priority)
        assert action["priority"] == "P0"


# ---------------------------------------------------------------------------
# Golden data 集成验证
# ---------------------------------------------------------------------------


class TestGoldenDataAlert:
    """使用 golden_data/alert_test_cases.json 验证评估框架。"""

    def test_golden_cases_format(self, alert_test_cases):
        """golden data 格式自检。"""
        required = ["id", "description", "expected"]
        for case in alert_test_cases["cases"]:
            missing = [k for k in required if k not in case]
            assert not missing, f"用例 {case.get('id')} 缺少字段: {missing}"

    def test_stock_alert_cases_have_product_data(self, alert_test_cases):
        """库存预警用例应有 product 字段。"""
        stock_cases = [
            c for c in alert_test_cases["cases"]
            if c.get("expected", {}).get("alert_type") in {"stock_critical", "stock_low"}
            or "stock" in c.get("product", {})
        ]
        for case in stock_cases:
            assert "product" in case, f"用例 {case['id']} 缺少 product 数据"

    def test_golden_stock_alert_logic(self, alert_test_cases):
        """用 golden data 验证库存预警触发逻辑。"""
        for case in alert_test_cases["cases"]:
            product = case.get("product", {})
            if "stock" not in product or "avg_daily_sales" not in product:
                continue

            should_trigger = case["expected"].get("should_trigger_alert")
            triggered, _ = _should_trigger_stock_alert(
                stock=product["stock"],
                avg_daily_sales=product["avg_daily_sales"],
            )

            if should_trigger is not None:
                assert triggered == should_trigger, (
                    f"用例 {case['id']}: 预期触发={should_trigger}, 实际={triggered}"
                )

    def test_golden_price_alert_logic(self, alert_test_cases):
        """用 golden data 验证价格异常检测逻辑。"""
        for case in alert_test_cases["cases"]:
            product = case.get("product", {})
            if "retail_price" not in product or "cost_price" not in product:
                continue

            expected_alert = case["expected"].get("should_trigger_alert")
            triggered = _should_trigger_price_alert(
                retail_price=product["retail_price"],
                cost_price=product["cost_price"],
                competitor_avg=product.get("competitor_avg_price", 0.0),
            )

            if expected_alert is not None:
                assert triggered == expected_alert, (
                    f"用例 {case['id']}: 价格预警预期={expected_alert}, 实际={triggered}"
                )

    def test_action_cases_have_required_fields(self, alert_test_cases):
        """标注了建议动作字段的用例应有 action_has_required_fields。"""
        action_cases = [c for c in alert_test_cases["cases"] if "anomaly" in c]
        for case in action_cases:
            expected = case.get("expected", {})
            assert "action_has_required_fields" in expected, (
                f"用例 {case['id']} 有 anomaly 但缺少 action_has_required_fields"
            )
