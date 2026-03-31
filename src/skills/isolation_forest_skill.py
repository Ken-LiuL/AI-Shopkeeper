"""Isolation Forest Skill — 多维度异常检测。

补全 SPEC 双引擎方案：Prophet 擅长单时序趋势，Isolation Forest 擅长多指标联合异常。
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)

# 默认检测指标（来自 qnh_daily_metrics）
_DEFAULT_METRICS = ["order_count", "gmv", "avg_order_value"]


class IsolationForestSkill:
    """多维度异常检测 — 适用于多指标联合异常（Prophet 擅长单时序）。

    使用场景：
    - 多个指标同时出现异常组合（如订单量↑但 GMV↓ 表明客单价异常下降）
    - 商品级特征矩阵异常（销量、库存、价格、趋势斜率联合异常）
    """

    def __init__(self, contamination: float = 0.05):
        """
        Args:
            contamination: 预期异常比例（0.0~0.5），默认 5%。
        """
        self.model = IsolationForest(
            contamination=contamination,
            random_state=42,
            n_estimators=100,
        )
        self._contamination = contamination

    # ── Store-level: 门店整体指标多维异常 ─────────────────────────────────

    async def detect_anomalies(
        self,
        pool,
        metrics: list[str] | None = None,
        days: int = 30,
    ) -> list[dict]:
        """从 qnh_daily_metrics 读取最近 N 天数据，用 Isolation Forest 检测多维异常点。

        Args:
            pool: asyncpg.Pool。
            metrics: 要检测的指标列名，默认 order_count / gmv / avg_order_value。
            days: 回溯天数，默认 30。

        Returns:
            [{"date": ..., "anomaly_score": ..., "is_anomaly": ..., "metrics": {...}}]
        """
        if metrics is None:
            metrics = _DEFAULT_METRICS

        if not pool:
            logger.warning("IsolationForestSkill.detect_anomalies: no pool provided")
            return []

        try:
            # 动态构建 SELECT 子句（只选取存在的指标列）
            col_select = ", ".join(metrics)
            rows = await pool.fetch(
                f"""
                SELECT metric_date, {col_select}
                FROM qnh_daily_metrics
                WHERE metric_date >= CURRENT_DATE - $1 * INTERVAL '1 day'
                ORDER BY metric_date ASC
                """,
                days,
            )
        except Exception as e:
            logger.warning(f"IsolationForestSkill: failed to fetch qnh_daily_metrics: {e}")
            return []

        if len(rows) < 10:
            logger.info(
                f"IsolationForestSkill.detect_anomalies: insufficient data ({len(rows)} rows < 10), skip"
            )
            return []

        # 构建特征矩阵
        dates = [row["metric_date"] for row in rows]
        feature_matrix = []
        for row in rows:
            feature_matrix.append([float(row[m] or 0) for m in metrics])

        X = np.array(feature_matrix)  # noqa: N806

        # 标准化（防止量纲差异影响）
        X_scaled = _standardize(X)  # noqa: N806

        # 训练并预测（-1=异常, 1=正常）
        predictions = self.model.fit_predict(X_scaled)
        scores = self.model.score_samples(X_scaled)  # 越负越异常

        results = []
        for i, row in enumerate(rows):
            is_anomaly = bool(predictions[i] == -1)
            metric_snapshot = {m: float(row[m] or 0) for m in metrics}
            results.append(
                {
                    "date": str(dates[i]),
                    "anomaly_score": round(float(scores[i]), 4),
                    "is_anomaly": is_anomaly,
                    "metrics": metric_snapshot,
                }
            )

        anomaly_count = sum(1 for r in results if r["is_anomaly"])
        logger.info(
            f"IsolationForestSkill.detect_anomalies: {anomaly_count}/{len(results)} anomalies detected"
        )
        return results

    # ── Product-level: 商品级特征矩阵异常 ────────────────────────────────

    async def detect_product_anomalies(
        self,
        pool,
        days: int = 30,
    ) -> list[dict]:
        """检测商品级异常。

        特征矩阵：日均销量、库存、价格、销售趋势斜率（近 N 天线性回归）。

        Args:
            pool: asyncpg.Pool。
            days: 用于计算均值/斜率的回溯天数。

        Returns:
            异常商品列表：
            [{"product_id": ..., "product_name": ..., "anomaly_score": ...,
              "is_anomaly": ..., "features": {...}}]
        """
        if not pool:
            logger.warning("IsolationForestSkill.detect_product_anomalies: no pool provided")
            return []

        try:
            # 从 product_sales + qnh_inventory 联合查询
            rows = await pool.fetch(
                """
                WITH sales_stats AS (
                    SELECT
                        spu_id,
                        AVG(quantity_sold)::float AS avg_daily_sales,
                        -- 趋势斜率：用 row_number 做简单线性回归
                        REGR_SLOPE(quantity_sold, ROW_NUMBER() OVER (PARTITION BY spu_id ORDER BY date))::float AS sales_slope
                    FROM qnh_sales_history
                    WHERE date >= CURRENT_DATE - $1 * INTERVAL '1 day'
                    GROUP BY spu_id
                    HAVING COUNT(*) >= 7
                ),
                latest_inventory AS (
                    SELECT DISTINCT ON (spu_id)
                        spu_id,
                        COALESCE(current_stock, available_stock, 0)::float AS current_stock
                    FROM qnh_inventory
                    ORDER BY spu_id, snapshot_time DESC
                ),
                product_price AS (
                    SELECT spu_id, COALESCE(retail_price, 0)::float AS price
                    FROM qnh_products
                    WHERE status = 'active'
                )
                SELECT
                    s.spu_id AS product_id,
                    p_name.name AS product_name,
                    s.avg_daily_sales,
                    COALESCE(i.current_stock, 0) AS current_stock,
                    COALESCE(pr.price, 0) AS price,
                    COALESCE(s.sales_slope, 0) AS sales_slope
                FROM sales_stats s
                JOIN qnh_products p_name ON p_name.spu_id = s.spu_id
                LEFT JOIN latest_inventory i ON i.spu_id = s.spu_id
                LEFT JOIN product_price pr ON pr.spu_id = s.spu_id
                ORDER BY s.spu_id
                """,
                days,
            )
        except Exception as e:
            logger.warning(f"IsolationForestSkill: failed to fetch product features: {e}")
            return []

        if len(rows) < 5:
            logger.info(
                f"IsolationForestSkill.detect_product_anomalies: insufficient products ({len(rows)} < 5), skip"
            )
            return []

        feature_names = ["avg_daily_sales", "current_stock", "price", "sales_slope"]
        product_ids = [row["product_id"] for row in rows]
        product_names = [row["product_name"] for row in rows]

        feature_matrix = []
        for row in rows:
            feature_matrix.append([
                float(row["avg_daily_sales"] or 0),
                float(row["current_stock"] or 0),
                float(row["price"] or 0),
                float(row["sales_slope"] or 0),
            ])

        X = np.array(feature_matrix)  # noqa: N806
        X_scaled = _standardize(X)  # noqa: N806

        # 为商品级检测使用独立模型实例（避免覆盖已 fit 的 store-level 模型）
        product_model = IsolationForest(
            contamination=self._contamination,
            random_state=42,
            n_estimators=100,
        )
        predictions = product_model.fit_predict(X_scaled)
        scores = product_model.score_samples(X_scaled)

        results = []
        for i in range(len(rows)):
            is_anomaly = bool(predictions[i] == -1)
            if not is_anomaly:
                continue  # 只返回异常商品
            features_snapshot = {name: feature_matrix[i][j] for j, name in enumerate(feature_names)}
            results.append(
                {
                    "product_id": str(product_ids[i]),
                    "product_name": str(product_names[i]),
                    "anomaly_score": round(float(scores[i]), 4),
                    "is_anomaly": True,
                    "features": features_snapshot,
                    "detection_method": "isolation_forest",
                    "detected_at": datetime.utcnow().isoformat(),
                }
            )

        logger.info(
            f"IsolationForestSkill.detect_product_anomalies: {len(results)}/{len(rows)} anomaly products"
        )
        return results


# ── Helpers ───────────────────────────────────────────────────────────────────


def _standardize(X: np.ndarray) -> np.ndarray:  # noqa: N803
    """逐列 Z-score 标准化，std=0 的列置 0 避免 NaN。"""
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0] = 1.0
    return (X - mean) / std
