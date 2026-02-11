"""Alert data model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AlertSeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertStatus(StrEnum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class Alert(BaseModel):
    """Anomaly alert entity."""

    alert_id: str = Field(..., max_length=50)
    product_id: str | None = Field(None, max_length=32)
    alert_type: str = Field(..., max_length=50)
    severity: AlertSeverity
    detection_method: str | None = Field(None, max_length=30)
    metrics: dict[str, Any] = Field(default_factory=dict)
    root_cause: str | None = None
    recommended_action: str | None = None
    status: AlertStatus = AlertStatus.PENDING
    created_at: datetime | None = None
    resolved_at: datetime | None = None
