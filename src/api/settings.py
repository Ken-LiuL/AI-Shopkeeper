"""
参数自学习 API 端点

GET  /api/settings/learning-status   — 返回当前权重、阈值、上次学习时间
POST /api/settings/trigger-learning  — 手动触发一次完整学习
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = logging.getLogger(__name__)


@router.get("/learning-status", response_model=APIResponse[dict])
async def get_learning_status() -> APIResponse[dict]:
    """返回当前生效的权重、阈值，以及最近一次参数版本的时间。"""
    try:
        import yaml
        from src.services.parameter_learning import SCORING_YAML, ANOMALY_YAML

        # 当前权重
        with open(SCORING_YAML, encoding="utf-8") as f:
            scoring = yaml.safe_load(f)
        weights = scoring.get("selection_scoring", {}).get("weights", {})

        # 当前阈值（关键字段）
        with open(ANOMALY_YAML, encoding="utf-8") as f:
            anomaly = yaml.safe_load(f)

        key_thresholds = {
            "sales_anomaly_critical": anomaly.get("sales_anomaly", {})
                .get("severity", {}).get("critical_deviation"),
            "sales_anomaly_warning": anomaly.get("sales_anomaly", {})
                .get("severity", {}).get("warning_deviation"),
            "competitor_price_drop": anomaly.get("competitor_price", {})
                .get("drop_threshold"),
            "margin_warning": anomaly.get("margin_warning", {})
                .get("warning_threshold"),
            "margin_critical": anomaly.get("margin_warning", {})
                .get("critical_threshold"),
        }

        # 最近两次学习记录
        pool = pg.get_pool()
        rows = await pool.fetch(
            """
            SELECT param_type, version, feedback_stats, created_at
            FROM parameter_versions
            ORDER BY created_at DESC
            LIMIT 10
            """
        )
        history = [
            {
                "param_type": r["param_type"],
                "version": r["version"],
                "feedback_stats": r["feedback_stats"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

        # 上次权重/阈值学习时间
        last_weight = next((h for h in history if h["param_type"] == "scoring_weights"), None)
        last_threshold = next((h for h in history if h["param_type"] == "anomaly_thresholds"), None)

        return APIResponse(
            data={
                "current_weights": weights,
                "current_thresholds": key_thresholds,
                "last_weight_learning": last_weight["created_at"] if last_weight else None,
                "last_threshold_adaptation": last_threshold["created_at"] if last_threshold else None,
                "recent_versions": history,
            }
        )

    except Exception as exc:
        logger.exception("get_learning_status failed")
        return APIResponse(success=False, message=str(exc), data={})


@router.post("/trigger-learning", response_model=APIResponse[dict])
async def trigger_learning() -> APIResponse[dict]:
    """手动触发一次完整的参数学习（权重 + 阈值）。"""
    try:
        from src.services.parameter_learning import (
            AnomalyThresholdAdapter,
            SelectionWeightLearner,
        )

        pool = pg.get_pool()

        weight_result = await SelectionWeightLearner().update_weights(pool)
        threshold_result = await AnomalyThresholdAdapter().adapt_thresholds(pool)

        return APIResponse(
            data={
                "weight_learning": weight_result,
                "threshold_adaptation": threshold_result,
            },
            message="参数学习触发完成",
        )

    except Exception as exc:
        logger.exception("trigger_learning failed")
        return APIResponse(success=False, message=str(exc), data={})
