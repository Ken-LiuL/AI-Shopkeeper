"""
参数自学习系统
SPEC V6.0 — 选品评分权重 + 异常检测阈值自动调整

A. SelectionWeightLearner  — 基于采纳/忽略反馈调整6维度权重
B. AnomalyThresholdAdapter — 基于误报/漏报统计自适应调整阈值
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 配置文件路径（相对于项目根）
_REPO_ROOT = Path(__file__).parent.parent.parent
SCORING_YAML = _REPO_ROOT / "config" / "scoring.yaml"
ANOMALY_YAML = _REPO_ROOT / "config" / "anomaly.yaml"

# 学习超参数
WEIGHT_DELTA = 0.02          # 每次反馈的权重调整步长
MIN_FEEDBACK_ROWS = 10       # 触发学习所需的最少反馈条数
FP_HIGH_THRESHOLD = 0.30     # 误报率高水位 → 提高阈值
FP_LOW_THRESHOLD = 0.10      # 误报率低水位 → 降低阈值
THRESHOLD_STEP_UP = 0.2      # 提高阈值时的步长（绝对值）
THRESHOLD_STEP_DOWN = 0.1    # 降低阈值时的步长（绝对值）

# 权重范围约束
WEIGHT_RANGES: dict[str, tuple[float, float]] = {
    "market_heat":      (0.15, 0.35),
    "competition_gap":  (0.10, 0.30),
    "supply_chain":     (0.10, 0.30),
    "profit_margin":    (0.15, 0.30),
    "category_synergy": (0.05, 0.20),
    "seasonal_fit":     (0.00, 0.15),
}


# ─────────────────────────────────────────────────────────────
# A. 选品权重学习
# ─────────────────────────────────────────────────────────────

class SelectionWeightLearner:
    """基于选品反馈（采纳/忽略）自动调整维度权重。"""

    def __init__(self, delta: float = WEIGHT_DELTA):
        self.delta = delta

    # ── 数据收集 ──────────────────────────────────────────────

    async def collect_feedback(self, pool) -> list[dict[str, Any]]:
        """
        从 selection_feedback 表收集最近反馈。
        返回记录列表，每条包含 action / scores。
        """
        rows = await pool.fetch(
            """
            SELECT id, recommendation_id, product_id, action, scores, created_at
            FROM selection_feedback
            ORDER BY created_at DESC
            LIMIT 500
            """
        )
        return [dict(r) for r in rows]

    # ── 权重更新 ──────────────────────────────────────────────

    async def update_weights(self, pool) -> dict[str, Any]:
        """
        核心逻辑：
        1. 收集反馈
        2. 被采纳的推荐 → 高分维度权重 +δ
           被忽略/拒绝的推荐 → 高分维度权重 −δ
        3. clip 到范围 + 归一化
        4. 写入 config/scoring.yaml 和 parameter_versions 表
        返回摘要 dict。
        """
        feedback = await self.collect_feedback(pool)
        if len(feedback) < MIN_FEEDBACK_ROWS:
            logger.info(
                "SelectionWeightLearner: 反馈条数 %d < %d，跳过本次学习",
                len(feedback), MIN_FEEDBACK_ROWS,
            )
            return {"status": "skipped", "reason": "insufficient_feedback", "count": len(feedback)}

        # 加载当前权重
        weights = _load_scoring_weights()
        dimensions = list(WEIGHT_RANGES.keys())

        adopted_count = 0
        ignored_count = 0

        for row in feedback:
            action: str = row.get("action", "")
            scores: dict = row.get("scores") or {}
            if not scores:
                continue

            # 找出该推荐中得分最高的维度
            top_dims = _top_dimensions(scores, dimensions, top_n=2)

            if action == "adopted":
                adopted_count += 1
                for dim in top_dims:
                    if dim in weights:
                        weights[dim] = min(
                            weights[dim] + self.delta,
                            WEIGHT_RANGES[dim][1],
                        )
            elif action in ("ignored", "rejected"):
                ignored_count += 1
                for dim in top_dims:
                    if dim in weights:
                        weights[dim] = max(
                            weights[dim] - self.delta,
                            WEIGHT_RANGES[dim][0],
                        )

        # 归一化
        weights = _normalize(weights)

        # 统计信息
        feedback_stats = {
            "total": len(feedback),
            "adopted": adopted_count,
            "ignored": ignored_count,
            "learned_at": datetime.utcnow().isoformat(),
        }

        # 写入 scoring.yaml
        _save_scoring_weights(weights)

        # 写入 parameter_versions 表（版本追踪）
        version_num = await _next_param_version(pool, "scoring_weights")
        await pool.execute(
            """
            INSERT INTO parameter_versions (param_type, version, params, feedback_stats, created_at)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, NOW())
            """,
            "scoring_weights",
            version_num,
            _to_jsonb(weights),
            _to_jsonb(feedback_stats),
        )

        logger.info(
            "SelectionWeightLearner: 权重已更新 — adopted=%d ignored=%d weights=%s",
            adopted_count, ignored_count, weights,
        )
        return {
            "status": "updated",
            "weights": weights,
            "feedback_stats": feedback_stats,
            "version": version_num,
        }


# ─────────────────────────────────────────────────────────────
# B. 异常检测阈值自适应
# ─────────────────────────────────────────────────────────────

class AnomalyThresholdAdapter:
    """基于误报/漏报反馈调整异常检测阈值。"""

    # 可自适应的阈值字段（anomaly.yaml 路径 → yaml key）
    ADAPTABLE: dict[str, tuple[str, ...]] = {
        # yaml_dot_path: (section, key)
        "sales_anomaly.severity.critical_deviation": ("sales_anomaly", "severity", "critical_deviation"),
        "sales_anomaly.severity.warning_deviation":  ("sales_anomaly", "severity", "warning_deviation"),
        "competitor_price.drop_threshold":            ("competitor_price", "drop_threshold"),
        "margin_warning.warning_threshold":           ("margin_warning", "warning_threshold"),
        "margin_warning.critical_threshold":          ("margin_warning", "critical_threshold"),
    }

    # 各阈值的合法范围 [min, max]
    RANGES: dict[str, tuple[float, float]] = {
        "sales_anomaly.severity.critical_deviation": (50.0, 90.0),
        "sales_anomaly.severity.warning_deviation":  (20.0, 60.0),
        "competitor_price.drop_threshold":            (0.05, 0.25),
        "margin_warning.warning_threshold":           (0.10, 0.35),
        "margin_warning.critical_threshold":          (0.05, 0.20),
    }

    async def adapt_thresholds(self, pool) -> dict[str, Any]:
        """
        从 alerts 表统计最近 30 天的误报情况，按比例调整阈值。
        返回调整摘要。
        """
        # 统计已确认预警（真阳性）与被忽略/关闭预警（误报）
        row = await pool.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status IN ('confirmed', 'resolved')) AS true_positive,
                COUNT(*) FILTER (WHERE status IN ('ignored', 'dismissed', 'closed')) AS false_positive,
                COUNT(*) AS total
            FROM alerts
            WHERE created_at >= NOW() - INTERVAL '30 days'
            """
        )

        total = int(row["total"] or 0)
        true_pos = int(row["true_positive"] or 0)
        false_pos = int(row["false_positive"] or 0)

        if total < 5:
            logger.info("AnomalyThresholdAdapter: 30天内预警数 %d 太少，跳过", total)
            return {"status": "skipped", "reason": "insufficient_alerts", "total": total}

        fp_rate = false_pos / total

        # 加载当前阈值配置
        cfg = _load_anomaly_config()

        changes: dict[str, dict] = {}

        for dot_path, path_keys in self.ADAPTABLE.items():
            old_val = _get_nested(cfg, path_keys)
            if old_val is None:
                continue
            old_val = float(old_val)
            lo, hi = self.RANGES[dot_path]

            if fp_rate > FP_HIGH_THRESHOLD:
                # 误报太多 → 提高阈值（更难触发预警）
                new_val = min(old_val + THRESHOLD_STEP_UP, hi)
                reason = f"误报率{fp_rate:.1%}>{FP_HIGH_THRESHOLD:.0%}，提高阈值"
            elif fp_rate < FP_LOW_THRESHOLD:
                # 误报很少 → 降低阈值（捕获更多异常）
                new_val = max(old_val - THRESHOLD_STEP_DOWN, lo)
                reason = f"误报率{fp_rate:.1%}<{FP_LOW_THRESHOLD:.0%}，降低阈值"
            else:
                # 处于合理范围，不调整
                continue

            if abs(new_val - old_val) < 1e-4:
                continue

            _set_nested(cfg, path_keys, round(new_val, 4))
            changes[dot_path] = {"old": old_val, "new": new_val, "reason": reason}
            logger.info("AnomalyThresholdAdapter: %s %.4f → %.4f (%s)", dot_path, old_val, new_val, reason)

        if not changes:
            logger.info("AnomalyThresholdAdapter: 误报率%.1f%%处于正常区间，无需调整", fp_rate * 100)
            return {
                "status": "no_change",
                "fp_rate": fp_rate,
                "total_alerts": total,
            }

        # 写回 anomaly.yaml
        _save_anomaly_config(cfg)

        # 写入 parameter_versions 表
        feedback_stats = {
            "fp_rate": fp_rate,
            "true_positive": true_pos,
            "false_positive": false_pos,
            "total": total,
            "learned_at": datetime.utcnow().isoformat(),
        }
        version_num = await _next_param_version(pool, "anomaly_thresholds")
        # 序列化 changes（确保可 JSON 化）
        changes_serializable = {k: {"old": v["old"], "new": v["new"], "reason": v["reason"]} for k, v in changes.items()}
        await pool.execute(
            """
            INSERT INTO parameter_versions (param_type, version, params, feedback_stats, created_at)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, NOW())
            """,
            "anomaly_thresholds",
            version_num,
            _to_jsonb(changes_serializable),
            _to_jsonb(feedback_stats),
        )

        return {
            "status": "updated",
            "fp_rate": fp_rate,
            "total_alerts": total,
            "changes": changes_serializable,
            "version": version_num,
        }


# ─────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────

def _load_scoring_weights() -> dict[str, float]:
    """读 scoring.yaml → selection_scoring.weights"""
    with open(SCORING_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return dict(data["selection_scoring"]["weights"])


def _save_scoring_weights(weights: dict[str, float]) -> None:
    """将更新后的权重写回 scoring.yaml（保留其余字段）。"""
    with open(SCORING_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["selection_scoring"]["weights"] = {k: round(v, 4) for k, v in weights.items()}
    with open(SCORING_YAML, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _load_anomaly_config() -> dict:
    with open(ANOMALY_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_anomaly_config(cfg: dict) -> None:
    with open(ANOMALY_YAML, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _get_nested(d: dict, keys: tuple) -> Any:
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _set_nested(d: dict, keys: tuple, value: Any) -> None:
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def _top_dimensions(scores: dict, dimensions: list[str], top_n: int = 2) -> list[str]:
    """返回 scores 中最高的 top_n 个维度名称。"""
    relevant = {k: v for k, v in scores.items() if k in dimensions}
    sorted_dims = sorted(relevant, key=lambda k: relevant[k], reverse=True)
    return sorted_dims[:top_n]


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {k: round(v / total, 6) for k, v in weights.items()}


async def _next_param_version(pool, param_type: str) -> int:
    """获取该 param_type 的下一个版本号。"""
    row = await pool.fetchrow(
        "SELECT COALESCE(MAX(version), 0) AS max_ver FROM parameter_versions WHERE param_type = $1",
        param_type,
    )
    return int(row["max_ver"]) + 1


def _to_jsonb(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


# ─────────────────────────────────────────────────────────────
# 顶层任务函数（供 scheduler 调用）
# ─────────────────────────────────────────────────────────────

async def run_weight_learning_task() -> None:
    """每周日凌晨 3:00 执行权重学习。"""
    logger.info("参数自学习：开始权重学习任务")
    try:
        from src.db import postgres as pg

        pool = pg.get_pool()
        learner = SelectionWeightLearner()
        result = await learner.update_weights(pool)
        logger.info("参数自学习：权重学习完成 → %s", result)
    except Exception:
        logger.exception("参数自学习：权重学习任务失败")


async def run_threshold_adaptation_task() -> None:
    """每周日凌晨 4:00 执行阈值自适应。"""
    logger.info("参数自学习：开始阈值自适应任务")
    try:
        from src.db import postgres as pg

        pool = pg.get_pool()
        adapter = AnomalyThresholdAdapter()
        result = await adapter.adapt_thresholds(pool)
        logger.info("参数自学习：阈值自适应完成 → %s", result)
    except Exception:
        logger.exception("参数自学习：阈值自适应任务失败")
