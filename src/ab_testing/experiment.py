"""A/B 实验管理 — ExperimentConfig + ExperimentManager."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExperimentConfig:
    """实验配置。"""

    name: str
    variants: list[str]  # e.g. ["control", "treatment"]
    traffic_split: dict[str, float] | None = None  # {"control": 0.5, "treatment": 0.5}
    metrics: list[str] = field(default_factory=list)
    description: str = ""
    start_time: float | None = None
    end_time: float | None = None

    def __post_init__(self) -> None:
        if not self.variants:
            raise ValueError("Must provide at least one variant.")
        if self.traffic_split is None:
            # Equal split by default
            equal = 1.0 / len(self.variants)
            self.traffic_split = {v: equal for v in self.variants}
        total = sum(self.traffic_split.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"traffic_split must sum to 1.0, got {total}")


class ExperimentManager:
    """内存 + 可选 DB 的 A/B 实验管理器。

    设计为轻量独立运行（无 DB 时退化到纯内存），也可通过 ``db_pool``
    传入 asyncpg pool 实现持久化。
    """

    def __init__(self, db_pool: Any = None) -> None:
        self._pool = db_pool
        # 内存存储（始终维护，作为缓存层）
        self._experiments: dict[str, dict[str, Any]] = {}
        self._assignments: dict[str, dict[str, str]] = {}  # exp_id -> {user_id: variant}
        self._outcomes: dict[str, list[dict[str, Any]]] = {}  # exp_id -> [outcome]

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    def create_experiment(self, config: ExperimentConfig) -> str:
        """创建实验，返回 experiment_id。"""
        exp_id = str(uuid.uuid4())[:12]
        record = {
            "experiment_id": exp_id,
            "name": config.name,
            "description": config.description,
            "variants": config.variants,
            "traffic_split": config.traffic_split,
            "metrics": config.metrics,
            "status": "running",
            "created_at": time.time(),
            "stopped_at": None,
        }
        self._experiments[exp_id] = record
        self._assignments[exp_id] = {}
        self._outcomes[exp_id] = []
        logger.info("Experiment created: %s (%s)", exp_id, config.name)
        return exp_id

    def get_variant(self, experiment_id: str, user_id: str) -> str:
        """一致性哈希：同一 user 永远返回同一变体。"""
        exp = self._get_experiment(experiment_id)
        if exp["status"] != "running":
            raise RuntimeError(f"Experiment {experiment_id} is not running (status={exp['status']})")

        # 如果已有分配，直接返回
        if user_id in self._assignments[experiment_id]:
            return self._assignments[experiment_id][user_id]

        # 一致性哈希决定变体
        variant = self._consistent_hash(experiment_id, user_id, exp["traffic_split"])
        self._assignments[experiment_id][user_id] = variant
        return variant

    def record_outcome(
        self,
        experiment_id: str,
        variant: str,
        metric_name: str,
        value: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记录一次实验指标。"""
        self._get_experiment(experiment_id)  # validate exists
        self._outcomes[experiment_id].append(
            {
                "variant": variant,
                "metric_name": metric_name,
                "metric_value": value,
                "metadata": metadata or {},
                "recorded_at": time.time(),
            }
        )

    def get_results(self, experiment_id: str) -> dict[str, Any]:
        """返回各变体的指标对比（含均值、样本量）。"""
        exp = self._get_experiment(experiment_id)
        outcomes = self._outcomes.get(experiment_id, [])

        # 按 variant × metric 聚合
        agg: dict[str, dict[str, list[float]]] = {}
        for o in outcomes:
            v = o["variant"]
            m = o["metric_name"]
            agg.setdefault(v, {}).setdefault(m, []).append(o["metric_value"])

        summary: dict[str, Any] = {}
        for variant, metrics in agg.items():
            summary[variant] = {}
            for metric, values in metrics.items():
                n = len(values)
                mean = sum(values) / n if n else 0.0
                summary[variant][metric] = {
                    "mean": mean,
                    "n": n,
                    "values": values,
                }

        # 分配数
        assignments = self._assignments.get(experiment_id, {})
        assignment_counts = {}
        for v in exp["variants"]:
            assignment_counts[v] = sum(1 for av in assignments.values() if av == v)

        return {
            "experiment_id": experiment_id,
            "name": exp["name"],
            "status": exp["status"],
            "variants": exp["variants"],
            "assignment_counts": assignment_counts,
            "metrics": summary,
        }

    def list_experiments(self) -> list[dict[str, Any]]:
        """列出所有实验（摘要）。"""
        return [
            {
                "experiment_id": e["experiment_id"],
                "name": e["name"],
                "status": e["status"],
                "variants": e["variants"],
                "created_at": e["created_at"],
            }
            for e in self._experiments.values()
        ]

    def stop_experiment(self, experiment_id: str) -> None:
        """停止实验。"""
        exp = self._get_experiment(experiment_id)
        exp["status"] = "stopped"
        exp["stopped_at"] = time.time()
        logger.info("Experiment stopped: %s", experiment_id)

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        """获取实验详情（public 方法，供 API 层使用）。"""
        return self._get_experiment(experiment_id)

    # ──────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────

    def _get_experiment(self, experiment_id: str) -> dict[str, Any]:
        if experiment_id not in self._experiments:
            raise KeyError(f"Experiment not found: {experiment_id}")
        return self._experiments[experiment_id]

    @staticmethod
    def _consistent_hash(
        experiment_id: str,
        user_id: str,
        traffic_split: dict[str, float],
    ) -> str:
        """用 MD5 哈希决定变体，确保分配比例符合 traffic_split。"""
        key = f"{experiment_id}:{user_id}"
        digest = hashlib.md5(key.encode()).hexdigest()
        # 取前 8 位 hex → 归一化到 [0, 1)
        bucket = int(digest[:8], 16) / 0xFFFFFFFF

        cumulative = 0.0
        for variant, pct in traffic_split.items():
            cumulative += pct
            if bucket < cumulative:
                return variant
        # 浮点边界保护：返回最后一个变体
        return list(traffic_split.keys())[-1]


# 全局单例（懒加载，供 API 层调用）
_manager: ExperimentManager | None = None


def get_experiment_manager() -> ExperimentManager:
    global _manager
    if _manager is None:
        _manager = ExperimentManager()
    return _manager
