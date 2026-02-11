"""Configuration loader for AI Store Manager."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

_ENV_VAR_PATTERN = re.compile(r"\$\{(?P<name>[^:}]+)(?::(?P<default>[^}]*))?\}")


def _resolve_env_vars(value: Any) -> Any:
    """Recursively resolve ${VAR:default} patterns in config values."""
    if isinstance(value, str):
        def _replacer(match: re.Match[str]) -> str:
            env_name = match.group("name")
            default = match.group("default") or ""
            return os.environ.get(env_name, default)

        resolved = _ENV_VAR_PATTERN.sub(_replacer, value)
        # Try to cast pure-numeric strings back to int
        if resolved.isdigit():
            return int(resolved)
        return resolved
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def _load_yaml(filename: str) -> dict[str, Any]:
    """Load a YAML config file and resolve environment variables."""
    filepath = _CONFIG_DIR / filename
    with open(filepath, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    return _resolve_env_vars(raw)  # type: ignore[return-value]


class _ScoringConfig:
    """Scoring model parameters."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def weights(self) -> dict[str, float]:
        return self._data["selection_scoring"]["weights"]

    @property
    def thresholds(self) -> dict[str, int]:
        return self._data["selection_scoring"]["thresholds"]

    @property
    def heat_score(self) -> dict[str, Any]:
        return self._data["heat_score"]

    @property
    def supplier_scoring(self) -> dict[str, Any]:
        return self._data["supplier_scoring"]

    @property
    def margin(self) -> dict[str, Any]:
        return self._data["margin"]


class _AnomalyConfig:
    """Anomaly detection parameters."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def prophet(self) -> dict[str, Any]:
        return self._data["prophet"]

    @property
    def sales_anomaly(self) -> dict[str, Any]:
        return self._data["sales_anomaly"]

    @property
    def stockout(self) -> dict[str, Any]:
        return self._data["stockout"]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class _CustomerServiceConfig:
    """Customer service parameters."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def intent(self) -> dict[str, Any]:
        return self._data["intent"]

    @property
    def retrieval(self) -> dict[str, Any]:
        return self._data["retrieval"]

    @property
    def reply(self) -> dict[str, Any]:
        return self._data["reply"]

    @property
    def faq_templates(self) -> dict[str, Any]:
        return self._data.get("faq_templates", {})


class _SystemConfig:
    """System-wide parameters."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def llm(self) -> dict[str, Any]:
        return self._data["llm"]

    @property
    def concurrency(self) -> dict[str, int]:
        return self._data["concurrency"]

    @property
    def cache(self) -> dict[str, int]:
        return self._data["cache"]

    @property
    def scheduled_tasks(self) -> dict[str, str]:
        return self._data["scheduled_tasks"]

    @property
    def database(self) -> dict[str, Any]:
        return self._data["database"]

    @property
    def langfuse(self) -> dict[str, Any]:
        return self._data.get("langfuse", {})

    @property
    def prometheus(self) -> dict[str, Any]:
        return self._data.get("prometheus", {})


class Settings:
    """Unified settings facade for all configuration."""

    def __init__(self) -> None:
        self.scoring = _ScoringConfig(_load_yaml("scoring.yaml"))
        self.anomaly = _AnomalyConfig(_load_yaml("anomaly.yaml"))
        self.customer_service = _CustomerServiceConfig(_load_yaml("customer_service.yaml"))
        self.system = _SystemConfig(_load_yaml("system.yaml"))

    def reload(self) -> None:
        """Hot-reload all configuration files."""
        self.__init__()  # type: ignore[misc]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return Settings()
