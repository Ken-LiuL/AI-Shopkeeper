"""
eval_metrics.py — AI Agent 评估指标工具类

提供：
  - 分类指标：accuracy, precision, recall, f1
  - 幻觉率 (hallucination rate)
  - 响应时间统计
  - 输出格式一致性检查
  - 评分汇总

使用示例：
    metrics = EvalMetrics()
    metrics.record_prediction(predicted="product_inquiry", expected="product_inquiry")
    print(metrics.classification_report())
"""

from __future__ import annotations

import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# 分类指标
# ---------------------------------------------------------------------------


@dataclass
class ClassificationRecord:
    predicted: str
    expected: str
    confidence: float = 1.0


class ClassificationMetrics:
    """计算 accuracy / precision / recall / F1（多分类宏平均）。"""

    def __init__(self) -> None:
        self._records: list[ClassificationRecord] = []

    def record(self, predicted: str, expected: str, confidence: float = 1.0) -> None:
        self._records.append(ClassificationRecord(predicted, expected, confidence))

    def accuracy(self) -> float:
        if not self._records:
            return 0.0
        correct = sum(1 for r in self._records if r.predicted == r.expected)
        return correct / len(self._records)

    def precision_recall_f1(self) -> dict[str, float]:
        """宏平均 precision / recall / F1。"""
        labels = list({r.expected for r in self._records})
        precisions, recalls, f1s = [], [], []

        for label in labels:
            tp = sum(1 for r in self._records if r.predicted == label and r.expected == label)
            fp = sum(1 for r in self._records if r.predicted == label and r.expected != label)
            fn = sum(1 for r in self._records if r.predicted != label and r.expected == label)

            p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0

            precisions.append(p)
            recalls.append(r)
            f1s.append(f)

        return {
            "precision_macro": statistics.mean(precisions) if precisions else 0.0,
            "recall_macro": statistics.mean(recalls) if recalls else 0.0,
            "f1_macro": statistics.mean(f1s) if f1s else 0.0,
        }

    def classification_report(self) -> dict[str, Any]:
        prf = self.precision_recall_f1()
        return {
            "total": len(self._records),
            "accuracy": self.accuracy(),
            **prf,
        }

    def reset(self) -> None:
        self._records.clear()


# ---------------------------------------------------------------------------
# 幻觉检测
# ---------------------------------------------------------------------------


class HallucinationTracker:
    """
    检测 Agent 回复中是否包含数据库中不存在的信息（幻觉）。

    用法：
        tracker = HallucinationTracker(known_products={"P100", "P200"})
        tracker.check_reply("推荐 P100 和 P999", mentioned_ids=["P100", "P999"])
        print(tracker.hallucination_rate())
    """

    def __init__(self, known_products: set[str] | None = None) -> None:
        self._known_products: set[str] = known_products or set()
        self._total_checks = 0
        self._hallucination_count = 0
        self._details: list[dict[str, Any]] = []

    def check_reply(
        self,
        reply_text: str,
        mentioned_ids: list[str] | None = None,
        mentioned_names: list[str] | None = None,
        known_names: set[str] | None = None,
    ) -> dict[str, Any]:
        """
        检查一条回复，返回幻觉检测结果。

        Args:
            reply_text: Agent 回复文本
            mentioned_ids: 回复中提及的商品 ID 列表
            mentioned_names: 回复中提及的商品名称列表
            known_names: 已知的真实商品名称集合
        """
        self._total_checks += 1
        hallucinated_ids = []
        hallucinated_names = []

        if mentioned_ids:
            hallucinated_ids = [pid for pid in mentioned_ids if pid not in self._known_products]

        if mentioned_names and known_names:
            hallucinated_names = [name for name in mentioned_names if name not in known_names]

        has_hallucination = bool(hallucinated_ids or hallucinated_names)
        if has_hallucination:
            self._hallucination_count += 1

        result = {
            "has_hallucination": has_hallucination,
            "hallucinated_ids": hallucinated_ids,
            "hallucinated_names": hallucinated_names,
            "reply_excerpt": reply_text[:120],
        }
        self._details.append(result)
        return result

    def hallucination_rate(self) -> float:
        if self._total_checks == 0:
            return 0.0
        return self._hallucination_count / self._total_checks

    def report(self) -> dict[str, Any]:
        return {
            "total_checks": self._total_checks,
            "hallucination_count": self._hallucination_count,
            "hallucination_rate": self.hallucination_rate(),
            "details": self._details,
        }


# ---------------------------------------------------------------------------
# 响应时间统计
# ---------------------------------------------------------------------------


class LatencyTracker:
    """记录 Agent 响应时间（毫秒）。"""

    def __init__(self) -> None:
        self._samples: list[float] = []

    @contextmanager
    def measure(self):
        """上下文管理器：自动记录代码块耗时。"""
        start = time.perf_counter()
        yield
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._samples.append(elapsed_ms)

    def record(self, ms: float) -> None:
        self._samples.append(ms)

    def stats(self) -> dict[str, float]:
        if not self._samples:
            return {"count": 0, "mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
        sorted_s = sorted(self._samples)
        n = len(sorted_s)
        return {
            "count": n,
            "mean_ms": statistics.mean(self._samples),
            "p50_ms": sorted_s[n // 2],
            "p95_ms": sorted_s[int(n * 0.95)],
            "max_ms": sorted_s[-1],
        }


# ---------------------------------------------------------------------------
# 输出格式一致性检查
# ---------------------------------------------------------------------------


def check_output_format(output: Any, required_keys: list[str]) -> dict[str, Any]:
    """
    检查 Agent 输出是否包含所有必要字段。

    Args:
        output: Agent 返回的 dict
        required_keys: 必须存在的 key 列表（支持嵌套，用 '.' 分隔）

    Returns:
        {"valid": bool, "missing_keys": [...], "present_keys": [...]}
    """
    if not isinstance(output, dict):
        return {"valid": False, "missing_keys": required_keys, "present_keys": [], "error": "output is not a dict"}

    missing = []
    present = []

    for key_path in required_keys:
        parts = key_path.split(".")
        cur = output
        found = True
        for part in parts:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                found = False
                break
        (present if found else missing).append(key_path)

    return {"valid": len(missing) == 0, "missing_keys": missing, "present_keys": present}


def check_value_in_range(value: float, min_val: float, max_val: float, label: str = "") -> dict[str, Any]:
    """检查数值是否在合理范围内。"""
    in_range = min_val <= value <= max_val
    return {
        "valid": in_range,
        "label": label,
        "value": value,
        "min": min_val,
        "max": max_val,
        "message": f"{label}={value} {'✓' if in_range else f'✗ 超出范围 [{min_val}, {max_val}]'}",
    }


def check_text_constraints(
    text: str,
    min_len: int = 0,
    max_len: int = 9999,
    required_keywords: list[str] | None = None,
    forbidden_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """
    检查文本约束：长度、必含关键词、禁止词。

    Returns:
        {"valid": bool, "issues": [...], "stats": {...}}
    """
    issues = []
    text_len = len(text)

    if text_len < min_len:
        issues.append(f"文本过短：{text_len} < {min_len}")
    if text_len > max_len:
        issues.append(f"文本过长：{text_len} > {max_len}")

    if required_keywords:
        for kw in required_keywords:
            if kw not in text:
                issues.append(f"缺少必要关键词：{kw!r}")

    if forbidden_keywords:
        for kw in forbidden_keywords:
            if kw in text:
                issues.append(f"包含禁止词：{kw!r}")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "stats": {"length": text_len, "min_len": min_len, "max_len": max_len},
    }


# ---------------------------------------------------------------------------
# 主聚合类
# ---------------------------------------------------------------------------


class EvalMetrics:
    """
    评估指标综合类。

    封装 classification / hallucination / latency 三大维度，
    提供统一的 summary() 接口。
    """

    def __init__(self) -> None:
        self.classification = ClassificationMetrics()
        self.hallucination = HallucinationTracker()
        self.latency = LatencyTracker()
        self._custom: dict[str, list[float]] = {}

    def record_prediction(self, predicted: str, expected: str, confidence: float = 1.0) -> None:
        self.classification.record(predicted, expected, confidence)

    def record_hallucination(self, reply: str, mentioned_ids: list[str], known_ids: set[str]) -> dict:
        self.hallucination._known_products = known_ids
        return self.hallucination.check_reply(reply, mentioned_ids=mentioned_ids)

    def record_custom(self, name: str, value: float) -> None:
        self._custom.setdefault(name, []).append(value)

    def summary(self) -> dict[str, Any]:
        custom_stats = {
            k: {"mean": statistics.mean(v), "min": min(v), "max": max(v)}
            for k, v in self._custom.items()
        }
        return {
            "classification": self.classification.classification_report(),
            "hallucination": self.hallucination.report(),
            "latency": self.latency.stats(),
            "custom": custom_stats,
        }
