"""
自适应阈值模块
根据历史数据动态调整异常检测阈值
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ThresholdConfig(BaseModel):
    """阈值配置"""
    name: str
    current_value: float
    min_value: float
    max_value: float
    last_updated: datetime = None
    update_reason: str = ""


class AdaptiveThresholds:
    """
    自适应阈值管理器
    
    根据历史预警的准确性动态调整阈值：
    - 误报率高 → 提高阈值
    - 漏报率高 → 降低阈值
    """
    
    DEFAULT_THRESHOLDS = {
        "sales_drop_critical": {"value": 70.0, "min": 50.0, "max": 90.0},
        "sales_drop_warning": {"value": 40.0, "min": 25.0, "max": 60.0},
        "price_gap_threshold": {"value": 15.0, "min": 10.0, "max": 25.0},
        "stockout_urgent_days": {"value": 1.0, "min": 0.5, "max": 2.0},
        "stockout_warning_days": {"value": 3.0, "min": 2.0, "max": 7.0},
        "margin_warning": {"value": 20.0, "min": 15.0, "max": 30.0},
        "margin_critical": {"value": 10.0, "min": 5.0, "max": 15.0},
        "zero_sales_days_warning": {"value": 3.0, "min": 2.0, "max": 5.0},
        "zero_sales_days_critical": {"value": 5.0, "min": 3.0, "max": 7.0},
    }
    
    def __init__(
        self,
        pool: Any = None,
        learning_rate: float = 0.05,
        min_feedback_samples: int = 50,
    ):
        self._pool = pool
        self._learning_rate = learning_rate
        self._min_feedback_samples = min_feedback_samples
        self._thresholds: Dict[str, ThresholdConfig] = {}
        
        # 初始化默认阈值
        for name, cfg in self.DEFAULT_THRESHOLDS.items():
            self._thresholds[name] = ThresholdConfig(
                name=name,
                current_value=cfg["value"],
                min_value=cfg["min"],
                max_value=cfg["max"],
            )
    
    def get_threshold(self, name: str) -> float:
        """获取指定阈值的当前值"""
        if name in self._thresholds:
            return self._thresholds[name].current_value
        raise KeyError(f"Unknown threshold: {name}")
    
    def get_all_thresholds(self) -> Dict[str, float]:
        """获取所有阈值"""
        return {name: cfg.current_value for name, cfg in self._thresholds.items()}
    
    async def update_from_feedback(
        self,
        threshold_name: str,
        false_positive_count: int,
        false_negative_count: int,
        true_positive_count: int,
        true_negative_count: int,
    ) -> Optional[ThresholdConfig]:
        """
        根据反馈更新阈值
        
        Args:
            threshold_name: 阈值名称
            false_positive_count: 误报数量
            false_negative_count: 漏报数量
            true_positive_count: 正确报警数量
            true_negative_count: 正确不报警数量
        """
        if threshold_name not in self._thresholds:
            logger.warning(f"Unknown threshold: {threshold_name}")
            return None
        
        total = false_positive_count + false_negative_count + true_positive_count + true_negative_count
        if total < self._min_feedback_samples:
            logger.info(f"Not enough feedback samples: {total} < {self._min_feedback_samples}")
            return None
        
        config = self._thresholds[threshold_name]
        old_value = config.current_value
        
        # 计算误报率和漏报率
        false_positive_rate = false_positive_count / (false_positive_count + true_negative_count + 0.001)
        false_negative_rate = false_negative_count / (false_negative_count + true_positive_count + 0.001)
        
        # 调整逻辑
        adjustment = 0.0
        reason = ""
        
        if false_positive_rate > 0.3:
            # 误报率高 → 提高阈值
            adjustment = self._learning_rate * (false_positive_rate - 0.2)
            reason = f"误报率{false_positive_rate:.1%}过高，提高阈值"
        elif false_negative_rate > 0.2:
            # 漏报率高 → 降低阈值
            adjustment = -self._learning_rate * (false_negative_rate - 0.1)
            reason = f"漏报率{false_negative_rate:.1%}过高，降低阈值"
        else:
            logger.info(f"Threshold {threshold_name} is well balanced")
            return None
        
        # 计算新值并限制范围
        new_value = old_value + adjustment * (config.max_value - config.min_value)
        new_value = max(config.min_value, min(config.max_value, new_value))
        
        if abs(new_value - old_value) < 0.01:
            return None
        
        # 更新
        config.current_value = new_value
        config.last_updated = datetime.now()
        config.update_reason = reason
        
        logger.info(f"Threshold {threshold_name} updated: {old_value:.2f} → {new_value:.2f} ({reason})")
        
        # 持久化
        await self._save_threshold(config)
        
        return config
    
    async def _save_threshold(self, config: ThresholdConfig) -> None:
        """持久化阈值到数据库"""
        if self._pool is None:
            return
        
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO adaptive_thresholds 
                   (name, current_value, min_value, max_value, update_reason, updated_at)
                   VALUES ($1, $2, $3, $4, $5, NOW())
                   ON CONFLICT (name) DO UPDATE SET
                   current_value = $2, update_reason = $5, updated_at = NOW()""",
                config.name, config.current_value, config.min_value, config.max_value, config.update_reason,
            )
    
    async def load_thresholds(self) -> Dict[str, float]:
        """从数据库加载阈值"""
        if self._pool is None:
            return self.get_all_thresholds()
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name, current_value, min_value, max_value FROM adaptive_thresholds"
            )
        
        for row in rows:
            name = row["name"]
            if name in self._thresholds:
                self._thresholds[name].current_value = row["current_value"]
                self._thresholds[name].min_value = row["min_value"]
                self._thresholds[name].max_value = row["max_value"]
        
        return self.get_all_thresholds()
    
    def calculate_dynamic_threshold(
        self,
        base_threshold: str,
        recent_volatility: float,
        seasonality_factor: float = 1.0,
    ) -> float:
        """
        计算动态阈值，考虑近期波动性和季节性
        
        Args:
            base_threshold: 基础阈值名称
            recent_volatility: 近期波动率 (0-1)
            seasonality_factor: 季节性因子 (0.5-2.0)
        """
        base = self.get_threshold(base_threshold)
        
        # 波动性调整：波动大时放宽阈值
        volatility_adjustment = 1 + recent_volatility * 0.3
        
        # 季节性调整：旺季时放宽阈值
        seasonal_adjustment = 1 + (seasonality_factor - 1) * 0.2
        
        dynamic = base * volatility_adjustment * seasonal_adjustment
        
        # 限制在合理范围内
        config = self._thresholds.get(base_threshold)
        if config:
            dynamic = max(config.min_value * 0.8, min(config.max_value * 1.2, dynamic))
        
        return dynamic
