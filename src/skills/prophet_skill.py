"""Prophet Skill — 时序预测 + 异常检测。"""

from __future__ import annotations

import io
import json
import pickle
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, Field


# ── Pydantic Models ──────────────────────────────────────────────────────────

class TrainResult(BaseModel):
    status: str = "trained"
    product_id: str
    samples: int
    trained_at: datetime = Field(default_factory=datetime.now)

class AnomalyResult(BaseModel):
    is_anomaly: bool
    type: Optional[str] = None  # drop/spike
    expected: Optional[float] = None
    actual: Optional[int] = None
    bounds: Optional[List[float]] = None
    deviation_pct: Optional[float] = None
    severity: Optional[str] = None  # critical/warning/info
    reason: str = ""


# ── Chinese holidays ─────────────────────────────────────────────────────────

def _get_chinese_holidays() -> pd.DataFrame:
    """中国主要节假日（Prophet holidays 格式）。"""
    holidays = []
    for year in range(2023, 2028):
        holidays.extend([
            {"holiday": "spring_festival", "ds": f"{year}-01-22", "lower_window": -1, "upper_window": 6},
            {"holiday": "qingming", "ds": f"{year}-04-05", "lower_window": 0, "upper_window": 2},
            {"holiday": "labor_day", "ds": f"{year}-05-01", "lower_window": 0, "upper_window": 4},
            {"holiday": "dragon_boat", "ds": f"{year}-06-22", "lower_window": 0, "upper_window": 2},
            {"holiday": "mid_autumn", "ds": f"{year}-09-17", "lower_window": 0, "upper_window": 2},
            {"holiday": "national_day", "ds": f"{year}-10-01", "lower_window": 0, "upper_window": 6},
            {"holiday": "double_eleven", "ds": f"{year}-11-11", "lower_window": -3, "upper_window": 0},
            {"holiday": "double_twelve", "ds": f"{year}-12-12", "lower_window": -1, "upper_window": 0},
        ])
    return pd.DataFrame(holidays)


# ── Severity config (from SPEC anomaly.yaml) ────────────────────────────────

_CRITICAL_DEVIATION = 0.70
_WARNING_DEVIATION = 0.40


class ProphetSkill:
    """Prophet 时序预测技能。"""

    def __init__(
        self,
        pool: Any = None,
        interval_width: float = 0.95,
        min_training_days: int = 14,
    ):
        """
        Args:
            pool: asyncpg.Pool for model persistence.
            interval_width: Prophet confidence interval.
            min_training_days: Minimum samples for training.
        """
        self._pool = pool
        self._interval_width = interval_width
        self._min_training_days = min_training_days

    # ── Train ────────────────────────────────────────────────────────────

    async def train_model(
        self,
        product_id: str,
        sales_data: pd.DataFrame,
    ) -> TrainResult:
        """训练 Prophet 模型。

        Args:
            product_id: 商品 ID。
            sales_data: DataFrame with columns ['ds', 'y']。
        """
        if len(sales_data) < self._min_training_days:
            raise ValueError(
                f"Need at least {self._min_training_days} data points, got {len(sales_data)}"
            )

        from prophet import Prophet

        model = Prophet(
            yearly_seasonality=False,
            weekly_seasonality=True,
            daily_seasonality=False,
            holidays=_get_chinese_holidays(),
            interval_width=self._interval_width,
            changepoint_prior_scale=0.05,
        )
        model.fit(sales_data)

        await self._save_model(product_id, model)

        return TrainResult(product_id=product_id, samples=len(sales_data))

    # ── Detect ───────────────────────────────────────────────────────────

    async def detect_anomaly(
        self,
        product_id: str,
        date: str,
        actual_sales: int,
    ) -> AnomalyResult:
        """检测销量异常。"""
        model = await self._load_model(product_id)
        if model is None:
            return AnomalyResult(is_anomaly=False, reason="no_model")

        forecast = model.predict(pd.DataFrame({"ds": [date]}))
        yhat = forecast["yhat"].iloc[0]
        lower = forecast["yhat_lower"].iloc[0]
        upper = forecast["yhat_upper"].iloc[0]

        if yhat == 0:
            return AnomalyResult(is_anomaly=False, reason="zero_forecast")

        deviation_pct = abs(actual_sales - yhat) / max(abs(yhat), 1)

        if actual_sales < lower:
            severity = "critical" if deviation_pct >= _CRITICAL_DEVIATION else "warning"
            return AnomalyResult(
                is_anomaly=True, type="drop",
                expected=round(yhat, 1), actual=actual_sales,
                bounds=[round(lower, 1), round(upper, 1)],
                deviation_pct=round(deviation_pct, 3),
                severity=severity,
            )
        elif actual_sales > upper:
            severity = "critical" if deviation_pct >= _CRITICAL_DEVIATION else "warning"
            return AnomalyResult(
                is_anomaly=True, type="spike",
                expected=round(yhat, 1), actual=actual_sales,
                bounds=[round(lower, 1), round(upper, 1)],
                deviation_pct=round(deviation_pct, 3),
                severity=severity,
            )

        return AnomalyResult(is_anomaly=False, reason="within_bounds")

    # ── Model persistence (PostgreSQL) ───────────────────────────────────

    async def _save_model(self, product_id: str, model: Any) -> None:
        if self._pool is None:
            return
        buf = io.BytesIO()
        pickle.dump(model, buf)
        model_bytes = buf.getvalue()

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO prophet_models (product_id, model_data, trained_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (product_id)
                DO UPDATE SET model_data = $2, trained_at = NOW()
                """,
                product_id, model_bytes,
            )

    async def _load_model(self, product_id: str) -> Any:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT model_data FROM prophet_models WHERE product_id = $1",
                product_id,
            )
        if not row:
            return None
        return pickle.loads(row["model_data"])
