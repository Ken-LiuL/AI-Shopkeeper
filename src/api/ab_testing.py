"""A/B 测试 API 路由。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.ab_testing.experiment import ExperimentConfig, get_experiment_manager
from src.ab_testing.stats import (
    calculate_confidence_interval,
    calculate_sample_size,
    t_test,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ab", tags=["ab-testing"])


# ──────────────────────────────────────────────────────────────
# Request / Response schemas
# ──────────────────────────────────────────────────────────────


class CreateExperimentRequest(BaseModel):
    name: str
    variants: list[str] = Field(..., min_length=2)
    traffic_split: dict[str, float] | None = None
    metrics: list[str] = Field(default_factory=list)
    description: str = ""


class CreateExperimentResponse(BaseModel):
    experiment_id: str
    name: str
    status: str


class RecordOutcomeRequest(BaseModel):
    variant: str
    metric_name: str
    value: float
    metadata: dict[str, Any] | None = None


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────


@router.post("/experiments", response_model=CreateExperimentResponse, status_code=201)
async def create_experiment(req: CreateExperimentRequest) -> CreateExperimentResponse:
    """创建一个新的 A/B 实验。"""
    try:
        config = ExperimentConfig(
            name=req.name,
            variants=req.variants,
            traffic_split=req.traffic_split,
            metrics=req.metrics,
            description=req.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    mgr = get_experiment_manager()
    exp_id = mgr.create_experiment(config)
    exp = mgr.get_experiment(exp_id)
    return CreateExperimentResponse(
        experiment_id=exp_id,
        name=exp["name"],
        status=exp["status"],
    )


@router.get("/experiments")
async def list_experiments() -> dict[str, Any]:
    """列出所有实验。"""
    mgr = get_experiment_manager()
    return {"experiments": mgr.list_experiments()}


@router.get("/experiments/{experiment_id}")
async def get_experiment_results(experiment_id: str) -> dict[str, Any]:
    """查看实验结果（含统计显著性）。"""
    mgr = get_experiment_manager()
    try:
        results = mgr.get_results(experiment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")

    # 为每对变体的每个指标计算统计显著性
    variants_list = results["variants"]
    metrics_data = results["metrics"]

    significance: dict[str, Any] = {}
    if len(variants_list) >= 2:
        control_name = variants_list[0]
        for treatment_name in variants_list[1:]:
            pair_key = f"{control_name}_vs_{treatment_name}"
            significance[pair_key] = {}

            control_metrics = metrics_data.get(control_name, {})
            treatment_metrics = metrics_data.get(treatment_name, {})

            all_metric_names = set(control_metrics) | set(treatment_metrics)
            for metric in all_metric_names:
                ctrl_vals = control_metrics.get(metric, {}).get("values", [])
                trt_vals = treatment_metrics.get(metric, {}).get("values", [])
                if len(ctrl_vals) >= 2 and len(trt_vals) >= 2:
                    p_value, significant = t_test(ctrl_vals, trt_vals)
                    ctrl_ci = calculate_confidence_interval(ctrl_vals)
                    trt_ci = calculate_confidence_interval(trt_vals)
                    significance[pair_key][metric] = {
                        "p_value": round(p_value, 6),
                        "significant": significant,
                        "control_ci": [round(ctrl_ci[0], 6), round(ctrl_ci[1], 6)],
                        "treatment_ci": [round(trt_ci[0], 6), round(trt_ci[1], 6)],
                    }
                else:
                    significance[pair_key][metric] = {
                        "p_value": None,
                        "significant": None,
                        "note": "Insufficient data for significance test",
                    }

    results["significance"] = significance
    return results


@router.post("/experiments/{experiment_id}/stop")
async def stop_experiment(experiment_id: str) -> dict[str, str]:
    """停止实验。"""
    mgr = get_experiment_manager()
    try:
        mgr.stop_experiment(experiment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    return {"status": "stopped", "experiment_id": experiment_id}


@router.get("/experiments/{experiment_id}/report")
async def get_experiment_report(experiment_id: str) -> dict[str, Any]:
    """生成实验对比报告。"""
    mgr = get_experiment_manager()
    try:
        results = mgr.get_results(experiment_id)
        exp = mgr.get_experiment(experiment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")

    variants_list = results["variants"]
    metrics_data = results["metrics"]

    # 构建报告
    report: dict[str, Any] = {
        "experiment_id": experiment_id,
        "name": exp["name"],
        "description": exp.get("description", ""),
        "status": exp["status"],
        "variants": variants_list,
        "assignment_counts": results["assignment_counts"],
        "comparisons": [],
        "recommendations": [],
    }

    if len(variants_list) >= 2:
        control_name = variants_list[0]
        for treatment_name in variants_list[1:]:
            control_metrics = metrics_data.get(control_name, {})
            treatment_metrics = metrics_data.get(treatment_name, {})

            comparison: dict[str, Any] = {
                "control": control_name,
                "treatment": treatment_name,
                "metrics": {},
            }

            all_metric_names = set(control_metrics) | set(treatment_metrics)
            wins = 0
            losses = 0

            for metric in all_metric_names:
                ctrl_data = control_metrics.get(metric, {})
                trt_data = treatment_metrics.get(metric, {})

                ctrl_mean = ctrl_data.get("mean", 0.0)
                trt_mean = trt_data.get("mean", 0.0)
                ctrl_vals = ctrl_data.get("values", [])
                trt_vals = trt_data.get("values", [])

                relative_change = (
                    (trt_mean - ctrl_mean) / ctrl_mean * 100 if ctrl_mean != 0 else 0.0
                )

                metric_report: dict[str, Any] = {
                    "control_mean": round(ctrl_mean, 6),
                    "treatment_mean": round(trt_mean, 6),
                    "relative_change_pct": round(relative_change, 2),
                    "control_n": ctrl_data.get("n", 0),
                    "treatment_n": trt_data.get("n", 0),
                }

                if len(ctrl_vals) >= 2 and len(trt_vals) >= 2:
                    p_value, significant = t_test(ctrl_vals, trt_vals)
                    metric_report["p_value"] = round(p_value, 6)
                    metric_report["significant"] = significant
                    if significant:
                        if trt_mean > ctrl_mean:
                            wins += 1
                        else:
                            losses += 1

                comparison["metrics"][metric] = metric_report

            comparison["significant_wins"] = wins
            comparison["significant_losses"] = losses

            # 推荐
            if wins > losses:
                rec = f"推荐选用 {treatment_name}：在 {wins} 个指标上显著优于 {control_name}"
            elif losses > wins:
                rec = f"建议保留 {control_name}：{treatment_name} 在 {losses} 个指标上显著劣于对照组"
            else:
                rec = f"{treatment_name} 与 {control_name} 无显著差异，可继续收集数据"
            report["recommendations"].append(rec)
            report["comparisons"].append(comparison)

    # 样本量建议（对 latency 等数值指标）
    report["sample_size_guidance"] = {
        "note": "如需检测 5% 的转化率提升（baseline=0.3, mde=0.015），每组约需样本量：",
        "example_n": calculate_sample_size(0.3, 0.015),
    }

    return report


@router.post("/experiments/{experiment_id}/outcomes")
async def record_outcome(experiment_id: str, req: RecordOutcomeRequest) -> dict[str, str]:
    """记录一次实验指标结果（供内部或测试调用）。"""
    mgr = get_experiment_manager()
    try:
        mgr.record_outcome(
            experiment_id,
            req.variant,
            req.metric_name,
            req.value,
            req.metadata,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    return {"status": "recorded"}
