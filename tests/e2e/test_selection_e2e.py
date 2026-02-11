"""E2E tests for Selection Agent flow."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

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
    orch.run_selection = AsyncMock(return_value={
        "scoring_summary": {"total_evaluated": 3, "recommended_count": 2},
        "recommendations": [
            {"rank": 1, "keyword": "血压计", "final_score": 87.5},
            {"rank": 2, "keyword": "制氧机", "final_score": 72.0},
        ],
    })
    return orch


@pytest.fixture
def selection_client(mock_pool, mock_orch):
    import src.db.postgres
    import src.api.deps
    import src.api.selection

    with patch.object(src.db.postgres, "get_pool", return_value=mock_pool), \
         patch.object(src.api.deps, "get_orchestrator", return_value=mock_orch):
        from src.api.errors import register_error_handlers
        app = FastAPI()
        app.include_router(src.api.selection.router)
        register_error_handlers(app)
        yield TestClient(app)


class TestSelectionE2E:

    def test_trigger_selection_run(self, selection_client, mock_pool):
        """Trigger a selection run and get task_id."""
        res = selection_client.post("/api/selection/run", json={
            "keywords": ["血压计", "体温计"],
        })
        assert res.status_code == 200
        data = res.json()
        assert data["task_id"].startswith("sel_")
        assert mock_pool.execute.called

    def test_trigger_selection_empty_params(self, selection_client):
        """Trigger selection with no keywords/categories."""
        res = selection_client.post("/api/selection/run", json={})
        assert res.status_code == 200
        assert res.json()["task_id"]

    def test_list_runs_empty(self, selection_client):
        """List runs when none exist."""
        res = selection_client.get("/api/selection/runs")
        assert res.status_code == 200
        assert res.json()["data"] == []

    def test_list_runs_with_data(self, selection_client, mock_pool):
        """List runs returns stored runs."""
        mock_pool.fetch = AsyncMock(return_value=[
            {"run_id": "sel_001", "status": "completed", "keywords": ["血压计"],
             "categories": [], "result_count": 2, "created_at": "2026-01-01T00:00:00"},
        ])
        res = selection_client.get("/api/selection/runs")
        assert res.status_code == 200
        assert len(res.json()["data"]) == 1

    def test_get_run_not_found(self, selection_client):
        """Get non-existent run returns 404."""
        res = selection_client.get("/api/selection/runs/nonexistent")
        assert res.status_code == 404

    def test_get_run_detail(self, selection_client, mock_pool):
        """Get a completed run with recommendations."""
        mock_pool.fetchrow = AsyncMock(return_value={
            "run_id": "sel_001", "status": "completed", "keywords": ["血压计"],
            "categories": [], "result_count": 2, "created_at": "2026-01-01T00:00:00",
            "result": {"recommendations": [{"rank": 1, "keyword": "血压计"}]},
        })
        res = selection_client.get("/api/selection/runs/sel_001")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["run_id"] == "sel_001"
        assert len(data["recommendations"]) == 1

    def test_get_recommendations_no_runs(self, selection_client, mock_pool):
        """Get recommendations when no completed runs exist."""
        mock_pool.fetchrow = AsyncMock(return_value=None)
        res = selection_client.get("/api/selection/recommendations")
        assert res.status_code == 200
        assert res.json()["data"] == []
