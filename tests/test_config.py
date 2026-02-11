"""Tests for configuration loading."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.config import _load_yaml, _resolve_env_vars, Settings


# ── _resolve_env_vars ────────────────────────────────────────────────────────

class TestResolveEnvVars:
    def test_simple_string(self):
        assert _resolve_env_vars("hello") == "hello"

    def test_env_var_with_default(self):
        result = _resolve_env_vars("${NONEXISTENT_VAR_XYZ:fallback}")
        assert result == "fallback"

    def test_env_var_set(self):
        with patch.dict(os.environ, {"TEST_CFG_VAR": "myval"}):
            assert _resolve_env_vars("${TEST_CFG_VAR:default}") == "myval"

    def test_env_var_no_default(self):
        result = _resolve_env_vars("${NONEXISTENT_VAR_ABC}")
        assert result == ""

    def test_numeric_cast(self):
        with patch.dict(os.environ, {"TEST_PORT": "5432"}):
            result = _resolve_env_vars("${TEST_PORT:3306}")
            assert result == 5432
            assert isinstance(result, int)

    def test_nested_dict(self):
        data = {"host": "${TEST_H:localhost}", "port": "${TEST_P:5432}"}
        result = _resolve_env_vars(data)
        assert result == {"host": "localhost", "port": 5432}

    def test_nested_list(self):
        data = ["${V1:a}", "${V2:b}"]
        result = _resolve_env_vars(data)
        assert result == ["a", "b"]

    def test_non_string_passthrough(self):
        assert _resolve_env_vars(42) == 42
        assert _resolve_env_vars(True) is True
        assert _resolve_env_vars(None) is None


# ── _load_yaml ───────────────────────────────────────────────────────────────

class TestLoadYaml:
    def test_scoring_yaml_loads(self):
        data = _load_yaml("scoring.yaml")
        assert "selection_scoring" in data
        assert "weights" in data["selection_scoring"]
        weights = data["selection_scoring"]["weights"]
        assert pytest.approx(sum(weights.values()), abs=0.001) == 1.0

    def test_anomaly_yaml_loads(self):
        data = _load_yaml("anomaly.yaml")
        assert "prophet" in data
        assert data["prophet"]["interval_width"] == 0.95

    def test_system_yaml_defaults(self):
        """When env vars are not set, defaults should be used."""
        data = _load_yaml("system.yaml")
        db = data["database"]["postgres"]
        assert db["host"] == "localhost"
        assert db["port"] == 5432

    def test_system_yaml_env_override(self):
        with patch.dict(os.environ, {"POSTGRES_HOST": "db.example.com", "POSTGRES_PORT": "15432"}):
            data = _load_yaml("system.yaml")
            db = data["database"]["postgres"]
            assert db["host"] == "db.example.com"
            assert db["port"] == 15432

    def test_customer_service_yaml_loads(self):
        data = _load_yaml("customer_service.yaml")
        assert "intent" in data
        assert "retrieval" in data
        assert data["retrieval"]["rrf_k"] == 60

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            _load_yaml("nonexistent.yaml")


# ── Settings ─────────────────────────────────────────────────────────────────

class TestSettings:
    def test_settings_loads(self):
        s = Settings()
        assert s.scoring.weights["market_heat"] == 0.25
        assert s.anomaly.prophet["interval_width"] == 0.95
        assert s.system.llm["temperature"] == 0
        assert "intent" in s.customer_service._data

    def test_scoring_thresholds(self):
        s = Settings()
        assert s.scoring.thresholds["strong_recommend"] == 80
        assert s.scoring.thresholds["recommend"] == 70

    def test_reload(self):
        s = Settings()
        s.reload()  # should not raise
        assert s.scoring.weights["market_heat"] == 0.25
