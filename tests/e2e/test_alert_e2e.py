"""E2E tests for Alert Agent flow."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    pool.execute = AsyncMock(return_value="INSERT 0 1")
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    return pool


@pytest.fixture
def mock_orch():
    orch = AsyncMock()
    orch.run_alert = AsyncMock(return_value={
        "anomalies": {
            "detection_summary": {"total_products_checked": 50, "anomalies_found": 1, "critical_count": 1},
            "anomalies": [{"anomaly_id": "A001", "product_id": "P100", "severity": "critical"}],
        },
        "actions": {"recommended_actions": [{"action_type": "price_adjust", "priority": "P0"}]},
    })
    return orch


@pytest.fixture
def alert_client(mock_pool, mock_orch):
    import src.db.postgres
    import src.api.deps
    import src.api.alerts

    with patch.object(src.db.postgres, "get_pool", return_value=mock_pool), \
         patch.object(src.api.deps, "get_orchestrator", return_value=mock_orch):
        from src.api.errors import register_error_handlers
        app = FastAPI()
        app.include_router(src.api.alerts.router)
        register_error_handlers(app)
        yield TestClient(app)


class TestAlertE2E:

    def test_trigger_alert_scan(self, alert_client):
        """Trigger an alert scan returns task_id."""
        res = alert_client.post("/api/alerts/scan")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["task_id"].startswith("scan_")

    def test_list_alerts_empty(self, alert_client):
        """List alerts when none exist."""
        res = alert_client.get("/api/alerts")
        assert res.status_code == 200
        assert res.json()["data"] == []

    def test_list_alerts_with_filter(self, alert_client, mock_pool):
        """Filter alerts by severity."""
        mock_pool.fetch = AsyncMock(return_value=[
            {"alert_id": "A001", "severity": "critical", "status": "open",
             "product_id": "P100", "created_at": "2026-01-01"},
        ])
        res = alert_client.get("/api/alerts?severity=critical")
        assert res.status_code == 200
        assert len(res.json()["data"]) == 1

    def test_get_alert_not_found(self, alert_client):
        """Get non-existent alert returns 404."""
        res = alert_client.get("/api/alerts/nonexistent")
        assert res.status_code == 404

    def test_update_alert_status(self, alert_client, mock_pool):
        """Acknowledge an alert."""
        mock_pool.fetchrow = AsyncMock(return_value={
            "alert_id": "A001", "status": "acknowledged",
        })
        res = alert_client.patch("/api/alerts/A001", json={"status": "acknowledged"})
        assert res.status_code == 200

    def test_update_alert_resolve(self, alert_client, mock_pool):
        """Resolve an alert."""
        mock_pool.fetchrow = AsyncMock(return_value={
            "alert_id": "A001", "status": "resolved",
        })
        res = alert_client.patch("/api/alerts/A001", json={"status": "resolved"})
        assert res.status_code == 200
        assert res.json()["data"]["status"] == "resolved"

    def test_update_alert_invalid_status(self, alert_client):
        """Invalid status should fail validation."""
        res = alert_client.patch("/api/alerts/A001", json={"status": "invalid"})
        assert res.status_code == 422
