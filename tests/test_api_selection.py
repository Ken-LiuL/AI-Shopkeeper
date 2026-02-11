"""Tests for Selection API schemas and utilities."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Schema Tests
# ---------------------------------------------------------------------------

class TestSelectionRunRequest:
    """Tests for SelectionRunRequest schema."""

    def test_request_with_keywords(self):
        """Request accepts keywords."""
        from src.api.schemas import SelectionRunRequest
        
        request = SelectionRunRequest(keywords=["血压计", "体温计"])
        assert request.keywords == ["血压计", "体温计"]

    def test_request_with_categories(self):
        """Request accepts categories."""
        from src.api.schemas import SelectionRunRequest
        
        request = SelectionRunRequest(categories=["医疗器械"])
        assert request.categories == ["医疗器械"]

    def test_request_all_optional(self):
        """All request fields are optional."""
        from src.api.schemas import SelectionRunRequest
        
        request = SelectionRunRequest()
        assert request.keywords is None
        assert request.categories is None


class TestSelectionRunSummary:
    """Tests for SelectionRunSummary schema."""

    def test_summary_creation(self):
        """Summary can be created with required fields."""
        from src.api.schemas import SelectionRunSummary
        
        summary = SelectionRunSummary(
            run_id="sel_001",
            status="running",
        )
        assert summary.run_id == "sel_001"
        assert summary.status == "running"
        assert summary.result_count == 0

    def test_summary_with_all_fields(self):
        """Summary accepts all fields."""
        from datetime import datetime
        from src.api.schemas import SelectionRunSummary
        
        summary = SelectionRunSummary(
            run_id="sel_001",
            status="completed",
            keywords=["血压计"],
            categories=["医疗器械"],
            result_count=5,
            created_at=datetime.now(),
        )
        assert summary.result_count == 5


class TestSelectionRunDetail:
    """Tests for SelectionRunDetail schema."""

    def test_detail_extends_summary(self):
        """Detail includes summary fields plus recommendations."""
        from src.api.schemas import SelectionRunDetail
        
        detail = SelectionRunDetail(
            run_id="sel_001",
            status="completed",
            recommendations=[
                {"rank": 1, "keyword": "制氧机", "final_score": 87.5},
            ],
        )
        assert len(detail.recommendations) == 1
        assert detail.run_id == "sel_001"


class TestGenId:
    """Tests for gen_id utility function."""

    def test_gen_id_with_prefix(self):
        """Generated ID includes prefix."""
        from src.api.deps import gen_id
        
        id1 = gen_id("sel_")
        assert id1.startswith("sel_")
        assert len(id1) == 16  # sel_ + 12 chars

    def test_gen_id_without_prefix(self):
        """Generated ID works without prefix."""
        from src.api.deps import gen_id
        
        id1 = gen_id()
        assert len(id1) == 12

    def test_gen_id_unique(self):
        """Generated IDs are unique."""
        from src.api.deps import gen_id
        
        ids = [gen_id("test_") for _ in range(100)]
        assert len(set(ids)) == 100


class TestTaskCreatedResponse:
    """Tests for TaskCreatedResponse schema."""

    def test_response_creation(self):
        """Response includes task_id and message."""
        from src.api.schemas import TaskCreatedResponse
        
        response = TaskCreatedResponse(task_id="sel_001", message="Task started")
        assert response.success is True
        assert response.task_id == "sel_001"


class TestAPIResponse:
    """Tests for generic APIResponse."""

    def test_response_with_data(self):
        """Response wraps data correctly."""
        from src.api.schemas import APIResponse
        
        response = APIResponse(data={"key": "value"})
        assert response.success is True
        assert response.data == {"key": "value"}

    def test_response_with_list_data(self):
        """Response wraps list data."""
        from src.api.schemas import APIResponse
        
        response = APIResponse(data=[1, 2, 3])
        assert response.data == [1, 2, 3]

    def test_response_default_message(self):
        """Response has default empty message."""
        from src.api.schemas import APIResponse
        
        response = APIResponse()
        assert response.message == ""
