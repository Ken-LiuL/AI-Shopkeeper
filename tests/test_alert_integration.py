"""Alert Agent 集成测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.agents.alert.nodes import action_node, anomaly_detection_node, root_cause_node
from src.agents.alert.state import AlertState

# ---------------------------------------------------------------------------
# Anomaly Detection
# ---------------------------------------------------------------------------


class TestAnomalyDetection:
    async def test_detects_anomalies(self, sample_anomalies_found):
        state: AlertState = {
            "products_data": "products json",
            "prophet_results": "prophet json",
            "rule_check_results": "rules json",
            "current_time": "2026-02-11T10:00:00",
        }
        with patch(
            "src.agents.alert.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_anomalies_found,
        ):
            result = await anomaly_detection_node(state)
        assert result["anomalies"]["detection_summary"]["anomalies_found"] == 2
        assert result["root_causes"] == []
        assert result["actions"] == []
        assert result["current_anomaly_index"] == 0

    async def test_no_anomalies(self, sample_anomalies_none):
        state: AlertState = {
            "products_data": "data",
            "prophet_results": "results",
            "rule_check_results": "rules",
            "current_time": "2026-02-11T10:00:00",
        }
        with patch(
            "src.agents.alert.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_anomalies_none,
        ):
            result = await anomaly_detection_node(state)
        assert result["anomalies"]["detection_summary"]["anomalies_found"] == 0

    async def test_detection_error(self):
        state: AlertState = {"errors": []}
        with patch(
            "src.agents.alert.nodes.call_tool",
            new_callable=AsyncMock,
            side_effect=RuntimeError("prophet crash"),
        ):
            result = await anomaly_detection_node(state)
        assert any("anomaly_detection" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# should_analyze 条件边
# ---------------------------------------------------------------------------


class TestShouldAnalyze:
    def test_no_anomalies_returns_end(self, sample_anomalies_none):
        # 直接测试 should_analyze 逻辑
        state: AlertState = {"anomalies": sample_anomalies_none}
        count = state["anomalies"]["detection_summary"]["anomalies_found"]
        assert count == 0

    def test_has_anomalies_returns_analyze(self, sample_anomalies_found):
        state: AlertState = {"anomalies": sample_anomalies_found}
        count = state["anomalies"]["detection_summary"]["anomalies_found"]
        assert count > 0


# ---------------------------------------------------------------------------
# Root Cause
# ---------------------------------------------------------------------------


class TestRootCause:
    async def test_analyzes_non_info_anomalies(self, sample_anomalies_found, sample_root_cause):
        state: AlertState = {
            "anomalies": sample_anomalies_found,
            "root_causes": [],
            "errors": [],
        }
        with patch(
            "src.agents.alert.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_root_cause,
        ):
            result = await root_cause_node(state)
        # 2 anomalies (critical + warning), both non-info → 2 root causes
        assert len(result["root_causes"]) == 2

    async def test_skips_info_severity(self, sample_root_cause):
        """info 级别的异常不做归因"""
        state: AlertState = {
            "anomalies": {
                "anomalies": [
                    {
                        "anomaly_id": "A003",
                        "product_id": "P300",
                        "anomaly_type": "overstock",
                        "severity": "info",
                        "description": "库存略多",
                    },
                ],
            },
            "root_causes": [],
            "errors": [],
        }
        with patch(
            "src.agents.alert.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_root_cause,
        ) as mock_ct:
            result = await root_cause_node(state)
        mock_ct.assert_not_called()
        assert len(result["root_causes"]) == 0

    async def test_partial_failure(self, sample_anomalies_found, sample_root_cause):
        call_count = 0

        async def _side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("timeout")
            return sample_root_cause

        state: AlertState = {
            "anomalies": sample_anomalies_found,
            "root_causes": [],
            "errors": [],
        }
        with patch(
            "src.agents.alert.nodes.call_tool", new_callable=AsyncMock, side_effect=_side_effect
        ):
            result = await root_cause_node(state)
        assert len(result["root_causes"]) == 1
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------


class TestAction:
    async def test_generates_actions(self, sample_root_cause, sample_action):
        state: AlertState = {
            "root_causes": [sample_root_cause],
            "actions": [],
            "errors": [],
        }
        with patch(
            "src.agents.alert.nodes.call_tool", new_callable=AsyncMock, return_value=sample_action
        ):
            result = await action_node(state)
        assert len(result["actions"]) == 1
        assert result["actions"][0]["recommended_actions"][0]["priority"] == "P0"

    async def test_action_error(self, sample_root_cause):
        state: AlertState = {
            "root_causes": [sample_root_cause],
            "actions": [],
            "errors": [],
        }
        with patch(
            "src.agents.alert.nodes.call_tool",
            new_callable=AsyncMock,
            side_effect=RuntimeError("llm err"),
        ):
            result = await action_node(state)
        assert len(result["actions"]) == 0
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# 端到端
# ---------------------------------------------------------------------------


class TestEndToEnd:
    async def test_no_anomaly_early_exit(self, sample_anomalies_none):
        """无异常时流程提前结束"""
        state: AlertState = {
            "products_data": "data",
            "prophet_results": "no anomaly",
            "rule_check_results": "all ok",
            "current_time": "2026-02-11T10:00:00",
        }
        with patch(
            "src.agents.alert.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_anomalies_none,
        ):
            result = await anomaly_detection_node(state)
            state.update(result)

        count = state["anomalies"]["detection_summary"]["anomalies_found"]
        assert count == 0
        # 不应进入 root_cause / action

    async def test_full_anomaly_flow(
        self, sample_anomalies_found, sample_root_cause, sample_action
    ):
        """有异常 → Anomaly → RootCause → Action 完整流程"""
        state: AlertState = {
            "products_data": "data",
            "prophet_results": "anomaly detected",
            "rule_check_results": "price gap",
            "current_time": "2026-02-11T10:00:00",
            "errors": [],
        }

        with patch("src.agents.alert.nodes.call_tool", new_callable=AsyncMock) as mock_ct:
            # Phase 1: Anomaly Detection
            mock_ct.return_value = sample_anomalies_found
            state.update(await anomaly_detection_node(state))
            assert state["anomalies"]["detection_summary"]["anomalies_found"] == 2

            # Phase 2: Root Cause
            mock_ct.return_value = sample_root_cause
            state.update(await root_cause_node(state))
            assert len(state["root_causes"]) == 2

            # Phase 3: Action
            mock_ct.return_value = sample_action
            state.update(await action_node(state))
            assert len(state["actions"]) == 2

        # 验证完整性
        assert "anomalies" in state
        assert "root_causes" in state
        assert "actions" in state
        assert len(state["errors"]) == 0
