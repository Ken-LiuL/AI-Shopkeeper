"""Calculator Skill — 评分/毛利/RRF 计算。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Pydantic Models ──────────────────────────────────────────────────────────


class HeatScoreResult(BaseModel):
    keyword: str
    search_volume: int
    growth_rate: float
    conversion_rate: float
    heat_score: float
    trend: str = "stable"  # rising/stable/declining


class SupplierScoreResult(BaseModel):
    source: str  # alibaba/pdd
    total_score: float
    breakdown: dict[str, float]


class MarginResult(BaseModel):
    cost: float
    suggested_price: float
    gross_margin: float
    margin_grade: str  # excellent/good/fair/poor


class ComprehensiveScore(BaseModel):
    keyword: str
    final_score: float
    breakdown: dict[str, float] = Field(default_factory=dict)
    recommendation: str = ""  # strong_recommend/recommend/optional/not_recommend


class RRFResult(BaseModel):
    id: str
    score: float
    data: dict[str, Any] = Field(default_factory=dict)


# ── Config (from scoring.yaml) ──────────────────────────────────────────────

_VOLUME_THRESHOLDS = [1000, 5000, 10000, 50000]
_VOLUME_SCORES = [0.2, 0.4, 0.6, 0.8, 1.0]
_GROWTH_CAP = 0.5
_CONVERSION_BASELINE = 0.1

_DIMENSION_WEIGHTS = {
    "market_heat": 0.25,
    "competition_gap": 0.20,
    "supply_chain": 0.20,
    "profit_margin": 0.20,
    "category_synergy": 0.10,
    "seasonal_fit": 0.05,
}

_THRESHOLDS = {
    "strong_recommend": 80,
    "recommend": 70,
    "optional": 60,
}

_MARGIN_GRADES = [
    (0.50, "excellent"),
    (0.40, "good"),
    (0.30, "fair"),
    (0.0, "poor"),
]

_COST_MULTIPLIER = 2.5
_MIN_MARGIN = 0.25


class CalculatorSkill:
    """评分与计算技能。"""

    def __init__(self, weights: dict[str, float] | None = None):
        self._weights = weights or _DIMENSION_WEIGHTS

    # ── 热度评分 ─────────────────────────────────────────────────────────

    def heat_score(
        self,
        keyword: str,
        search_volume: int,
        growth_rate: float,
        conversion_rate: float = 0.0,
    ) -> HeatScoreResult:
        """计算关键词热度评分（满分100）。"""
        # 搜索量归一化
        normalized = _VOLUME_SCORES[-1]
        for i, threshold in enumerate(_VOLUME_THRESHOLDS):
            if search_volume < threshold:
                normalized = _VOLUME_SCORES[i]
                break

        # 增长率因子
        growth_factor = 1 + min(growth_rate, _GROWTH_CAP)

        # 转化率因子
        conv_factor = (
            min(conversion_rate / _CONVERSION_BASELINE, 1.0) if _CONVERSION_BASELINE > 0 else 1.0
        )

        score = round(normalized * growth_factor * conv_factor * 100, 1)
        score = min(score, 100.0)

        # 趋势
        if growth_rate > 0.15:
            trend = "rising"
        elif growth_rate < -0.05:
            trend = "declining"
        else:
            trend = "stable"

        return HeatScoreResult(
            keyword=keyword,
            search_volume=search_volume,
            growth_rate=growth_rate,
            conversion_rate=conversion_rate,
            heat_score=score,
            trend=trend,
        )

    # ── 供应商评分（1688） ───────────────────────────────────────────────

    def alibaba_supplier_score(
        self,
        is_power_seller: bool = False,
        years: int = 0,
        shop_score: float = 0.0,
        trade_level: str = "",
        return_rate: float = 0.0,
        product_match: str = "similar",  # exact/similar/marginal
        price_rank: str = "average",  # lowest/second/average
    ) -> SupplierScoreResult:
        """1688 供应商评分（满分100）。"""
        breakdown: dict[str, float] = {}

        # 实力商家 (20)
        breakdown["qualification"] = 20.0 if is_power_seller else 0.0

        # 经营年限 (15)
        if years >= 5:
            breakdown["years"] = 15.0
        elif years >= 3:
            breakdown["years"] = 10.0
        elif years >= 1:
            breakdown["years"] = 5.0
        else:
            breakdown["years"] = 0.0

        # 店铺评分 (15)
        if shop_score >= 4.8:
            breakdown["shop_score"] = 15.0
        elif shop_score >= 4.5:
            breakdown["shop_score"] = 10.0
        else:
            breakdown["shop_score"] = 5.0

        # 交易等级 (10)
        level_map = {"gold": 10.0, "silver": 7.0, "bronze": 4.0}
        breakdown["trade_level"] = level_map.get(trade_level, 0.0)

        # 回头率 (10)
        if return_rate >= 0.30:
            breakdown["return_rate"] = 10.0
        elif return_rate >= 0.20:
            breakdown["return_rate"] = 7.0
        else:
            breakdown["return_rate"] = 4.0

        # 商品匹配 (15)
        match_map = {"exact": 15.0, "similar": 10.0, "marginal": 5.0}
        breakdown["product_match"] = match_map.get(product_match, 5.0)

        # 价格竞争力 (15)
        price_map = {"lowest": 15.0, "second": 10.0, "average": 5.0}
        breakdown["price"] = price_map.get(price_rank, 5.0)

        total = sum(breakdown.values())
        return SupplierScoreResult(source="alibaba", total_score=total, breakdown=breakdown)

    # ── 供应商评分（拼多多） ─────────────────────────────────────────────

    def pdd_product_score(
        self,
        shop_score: float = 0.0,
        sales_count: int = 0,
        price_rank: str = "average",  # lowest/second/average
        review_count: int = 0,
    ) -> SupplierScoreResult:
        """拼多多商品评分（满分100）。"""
        breakdown: dict[str, float] = {}

        # 店铺评分 (25)
        if shop_score >= 4.8:
            breakdown["shop_score"] = 25.0
        elif shop_score >= 4.5:
            breakdown["shop_score"] = 20.0
        else:
            breakdown["shop_score"] = 10.0

        # 销量 (25)
        if sales_count > 1000:
            breakdown["sales"] = 25.0
        elif sales_count > 500:
            breakdown["sales"] = 20.0
        elif sales_count > 100:
            breakdown["sales"] = 15.0
        else:
            breakdown["sales"] = 10.0

        # 价格 (30)
        price_map = {"lowest": 30.0, "second": 20.0, "average": 10.0}
        breakdown["price"] = price_map.get(price_rank, 10.0)

        # 评价数 (20)
        if review_count > 500:
            breakdown["reviews"] = 20.0
        elif review_count > 100:
            breakdown["reviews"] = 15.0
        else:
            breakdown["reviews"] = 10.0

        total = sum(breakdown.values())
        return SupplierScoreResult(source="pdd", total_score=total, breakdown=breakdown)

    # ── 毛利计算 ─────────────────────────────────────────────────────────

    def calculate_margin(
        self,
        cost: float,
        market_price: float = 0.0,
        source: str = "alibaba",
        weight_kg: float = 0.0,
    ) -> MarginResult:
        """毛利计算。

        1688: 综合成本 = 单价 + 物流费(重量×1.5) + 损耗(2%)
        拼多多: 综合成本 = 单价（通常包邮）
        """
        if source == "alibaba":
            shipping = weight_kg * 1.5
            total_cost = (cost + shipping) * 1.02  # 2% 损耗
        else:
            total_cost = cost

        suggested_price = (
            max(total_cost * _COST_MULTIPLIER, market_price * 0.95)
            if market_price > 0
            else total_cost * _COST_MULTIPLIER
        )

        if suggested_price > 0:
            gross_margin = (suggested_price - total_cost) / suggested_price
        else:
            gross_margin = 0.0

        grade = "poor"
        for threshold, g in _MARGIN_GRADES:
            if gross_margin >= threshold:
                grade = g
                break

        return MarginResult(
            cost=round(total_cost, 2),
            suggested_price=round(suggested_price, 2),
            gross_margin=round(gross_margin, 4),
            margin_grade=grade,
        )

    # ── 6维度综合评分 ────────────────────────────────────────────────────

    def comprehensive_score(
        self,
        keyword: str,
        scores: dict[str, float],
    ) -> ComprehensiveScore:
        """6维度加权综合评分。

        Args:
            keyword: 关键词。
            scores: 各维度分数 (0-100)，key 须为 market_heat / competition_gap /
                    supply_chain / profit_margin / category_synergy / seasonal_fit。
        """
        weighted_sum = 0.0
        breakdown: dict[str, float] = {}
        for dim, weight in self._weights.items():
            raw = scores.get(dim, 0.0)
            weighted = raw * weight
            breakdown[dim] = round(weighted, 2)
            weighted_sum += weighted

        final = round(weighted_sum, 1)

        if final >= _THRESHOLDS["strong_recommend"]:
            rec = "strong_recommend"
        elif final >= _THRESHOLDS["recommend"]:
            rec = "recommend"
        elif final >= _THRESHOLDS["optional"]:
            rec = "optional"
        else:
            rec = "not_recommend"

        return ComprehensiveScore(
            keyword=keyword,
            final_score=final,
            breakdown=breakdown,
            recommendation=rec,
        )

    # ── RRF 融合 ─────────────────────────────────────────────────────────

    @staticmethod
    def rrf_merge(
        *result_lists: list[dict[str, Any]],
        id_field: str = "id",
        k: int = 60,
    ) -> list[RRFResult]:
        """Reciprocal Rank Fusion 融合多路排序结果。"""
        scores: dict[str, float] = {}
        data_map: dict[str, dict[str, Any]] = {}

        for result_list in result_lists:
            for rank, item in enumerate(result_list, start=1):
                item_id = str(item.get(id_field, rank))
                scores[item_id] = scores.get(item_id, 0) + 1.0 / (k + rank)
                if item_id not in data_map:
                    data_map[item_id] = item

        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        return [
            RRFResult(id=sid, score=round(scores[sid], 6), data=data_map[sid]) for sid in sorted_ids
        ]
