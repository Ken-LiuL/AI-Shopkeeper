"""
权重自学习模块
根据推荐结果的实际表现调整评分权重
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


@dataclass
class RecommendationOutcome:
    """推荐结果实际表现"""

    keyword: str
    predicted_score: float
    actual_monthly_sales: int
    actual_margin: float
    conversion_rate: float
    days_since_listed: int


class WeightUpdate(BaseModel):
    """权重更新记录"""

    dimension: str
    old_weight: float
    new_weight: float
    reason: str
    timestamp: datetime = None

    def __init__(self, **data):
        super().__init__(**data)
        if self.timestamp is None:
            self.timestamp = datetime.now()


class WeightLearner:
    """
    选品评分权重自学习器

    通过分析推荐商品的实际销售表现，动态调整6维度权重：
    - 如果高分推荐的商品实际表现好 → 当前权重合理
    - 如果高分推荐表现差，但某个维度分数低 → 该维度权重应提高
    - 如果低分商品意外表现好 → 分析哪些维度被低估
    """

    DEFAULT_WEIGHTS = {
        "market_heat": 0.25,
        "competition_gap": 0.20,
        "supply_chain": 0.20,
        "profit_margin": 0.20,
        "category_synergy": 0.10,
        "seasonal_fit": 0.05,
    }

    # 权重调整范围限制
    WEIGHT_RANGES = {
        "market_heat": (0.15, 0.35),
        "competition_gap": (0.10, 0.30),
        "supply_chain": (0.10, 0.30),
        "profit_margin": (0.15, 0.30),
        "category_synergy": (0.05, 0.20),
        "seasonal_fit": (0.00, 0.15),
    }

    def __init__(
        self,
        pool: Any = None,
        initial_weights: dict[str, float] | None = None,
        learning_rate: float = 0.1,
        min_samples: int = 20,
    ):
        self._pool = pool
        self._weights = initial_weights or self.DEFAULT_WEIGHTS.copy()
        self._learning_rate = learning_rate
        self._min_samples = min_samples
        self._history: list[WeightUpdate] = []

    @property
    def weights(self) -> dict[str, float]:
        return self._weights.copy()

    async def learn_from_outcomes(
        self,
        outcomes: list[RecommendationOutcome],
    ) -> list[WeightUpdate]:
        """
        从推荐结果的实际表现中学习

        Args:
            outcomes: 推荐商品的实际销售表现列表

        Returns:
            权重更新列表
        """
        if len(outcomes) < self._min_samples:
            logger.info(f"Not enough samples for learning: {len(outcomes)} < {self._min_samples}")
            return []

        updates: list[WeightUpdate] = []

        # 计算实际表现评分
        actual_scores = self._calculate_actual_scores(outcomes)

        # 分析预测 vs 实际的差异
        for outcome in outcomes:
            predicted = outcome.predicted_score
            actual = actual_scores.get(outcome.keyword, 0)

            if predicted > 80 and actual < 50:
                # 高分推荐但表现差 → 分析哪些维度被高估
                dimension_updates = self._analyze_overestimation(outcome)
                updates.extend(dimension_updates)

            elif predicted < 60 and actual > 70:
                # 低分但表现好 → 分析哪些维度被低估
                dimension_updates = self._analyze_underestimation(outcome)
                updates.extend(dimension_updates)

        # 应用更新
        for update in updates:
            self._apply_update(update)

        # 归一化权重
        self._normalize_weights()

        # 保存历史
        self._history.extend(updates)

        # 持久化
        await self._save_weights()

        return updates

    def _calculate_actual_scores(
        self,
        outcomes: list[RecommendationOutcome],
    ) -> dict[str, float]:
        """根据实际表现计算分数"""
        scores = {}

        for o in outcomes:
            # 基于实际销量、毛利、转化率计算综合分数
            sales_score = min(o.actual_monthly_sales / 100 * 50, 50)  # 最高50分
            margin_score = o.actual_margin * 30  # 最高30分 (100% margin)
            conversion_score = o.conversion_rate * 200  # 最高20分 (10% conversion)

            scores[o.keyword] = sales_score + margin_score + conversion_score

        return scores

    def _analyze_overestimation(
        self,
        outcome: RecommendationOutcome,
    ) -> list[WeightUpdate]:
        """分析高估情况，降低相关维度权重"""
        updates = []

        # 如果实际毛利低，降低 profit_margin 权重
        if outcome.actual_margin < 0.25:
            old = self._weights["profit_margin"]
            new = max(old - self._learning_rate * 0.5, self.WEIGHT_RANGES["profit_margin"][0])
            if abs(new - old) > 0.01:
                updates.append(
                    WeightUpdate(
                        dimension="profit_margin",
                        old_weight=old,
                        new_weight=new,
                        reason=f"实际毛利{outcome.actual_margin:.1%}低于预期",
                    )
                )

        # 如果转化率低，降低 market_heat 权重
        if outcome.conversion_rate < 0.05:
            old = self._weights["market_heat"]
            new = max(old - self._learning_rate * 0.3, self.WEIGHT_RANGES["market_heat"][0])
            if abs(new - old) > 0.01:
                updates.append(
                    WeightUpdate(
                        dimension="market_heat",
                        old_weight=old,
                        new_weight=new,
                        reason=f"转化率{outcome.conversion_rate:.1%}低于预期",
                    )
                )

        return updates

    def _analyze_underestimation(
        self,
        outcome: RecommendationOutcome,
    ) -> list[WeightUpdate]:
        """分析低估情况，提高相关维度权重"""
        updates = []

        # 如果实际销量好，提高 competition_gap 权重
        if outcome.actual_monthly_sales > 100:
            old = self._weights["competition_gap"]
            new = min(old + self._learning_rate * 0.3, self.WEIGHT_RANGES["competition_gap"][1])
            if abs(new - old) > 0.01:
                updates.append(
                    WeightUpdate(
                        dimension="competition_gap",
                        old_weight=old,
                        new_weight=new,
                        reason=f"实际月销{outcome.actual_monthly_sales}超预期",
                    )
                )

        return updates

    def _apply_update(self, update: WeightUpdate) -> None:
        """应用单个权重更新"""
        self._weights[update.dimension] = update.new_weight
        logger.info(
            f"Weight updated: {update.dimension} {update.old_weight:.3f} → {update.new_weight:.3f}"
            f" ({update.reason})"
        )

    def _normalize_weights(self) -> None:
        """归一化权重使总和为1"""
        total = sum(self._weights.values())
        if total > 0:
            for dim in self._weights:
                self._weights[dim] /= total

    async def _save_weights(self) -> None:
        """持久化权重到数据库"""
        if self._pool is None:
            return

        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO learning_weights (weights, updated_at)
                   VALUES ($1::jsonb, NOW())""",
                json.dumps(self._weights),
            )

    async def load_weights(self) -> dict[str, float]:
        """从数据库加载最新权重"""
        if self._pool is None:
            return self._weights

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT weights FROM learning_weights ORDER BY updated_at DESC LIMIT 1"
            )

        if row and row["weights"]:
            loaded = (
                json.loads(row["weights"]) if isinstance(row["weights"], str) else row["weights"]
            )
            self._weights = {**self.DEFAULT_WEIGHTS, **loaded}

        return self._weights
