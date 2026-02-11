"""
参数版本管理器
管理和追踪参数变更历史，支持回滚
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import StrEnum

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ParameterType(StrEnum):
    WEIGHTS = "weights"
    THRESHOLDS = "thresholds"
    CONFIG = "config"


class ParameterVersion(BaseModel):
    """参数版本"""
    version_id: str
    param_type: ParameterType
    values: Dict[str, Any]
    description: str = ""
    created_at: datetime = None
    created_by: str = "system"  # system/manual/learning
    is_active: bool = False
    performance_score: Optional[float] = None
    
    def __init__(self, **data):
        super().__init__(**data)
        if self.created_at is None:
            self.created_at = datetime.now()


class ParameterVersionManager:
    """
    参数版本管理器
    
    功能：
    - 保存参数版本历史
    - 支持回滚到历史版本
    - 追踪各版本的表现
    - A/B 测试支持
    """
    
    def __init__(self, pool: Any = None):
        self._pool = pool
        self._versions: Dict[ParameterType, List[ParameterVersion]] = {
            ParameterType.WEIGHTS: [],
            ParameterType.THRESHOLDS: [],
            ParameterType.CONFIG: [],
        }
        self._active_versions: Dict[ParameterType, Optional[str]] = {
            ParameterType.WEIGHTS: None,
            ParameterType.THRESHOLDS: None,
            ParameterType.CONFIG: None,
        }
    
    async def create_version(
        self,
        param_type: ParameterType,
        values: Dict[str, Any],
        description: str = "",
        created_by: str = "system",
        activate: bool = True,
    ) -> ParameterVersion:
        """
        创建新参数版本
        
        Args:
            param_type: 参数类型
            values: 参数值
            description: 版本描述
            created_by: 创建者 (system/manual/learning)
            activate: 是否立即激活
        """
        # 生成版本ID
        import uuid
        version_id = f"{param_type.value}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        
        version = ParameterVersion(
            version_id=version_id,
            param_type=param_type,
            values=values,
            description=description,
            created_by=created_by,
            is_active=activate,
        )
        
        # 如果激活，先停用当前版本
        if activate:
            for v in self._versions[param_type]:
                v.is_active = False
            self._active_versions[param_type] = version_id
        
        self._versions[param_type].append(version)
        
        # 持久化
        await self._save_version(version)
        
        logger.info(f"Created parameter version: {version_id} ({description})")
        
        return version
    
    async def activate_version(self, version_id: str) -> bool:
        """激活指定版本"""
        for param_type, versions in self._versions.items():
            for v in versions:
                if v.version_id == version_id:
                    # 停用同类型的其他版本
                    for other in versions:
                        other.is_active = False
                    v.is_active = True
                    self._active_versions[param_type] = version_id
                    
                    await self._update_version_status(version_id, True)
                    logger.info(f"Activated version: {version_id}")
                    return True
        
        logger.warning(f"Version not found: {version_id}")
        return False
    
    async def rollback(self, param_type: ParameterType, steps: int = 1) -> Optional[ParameterVersion]:
        """
        回滚到之前的版本
        
        Args:
            param_type: 参数类型
            steps: 回滚步数
        """
        versions = self._versions.get(param_type, [])
        if len(versions) <= steps:
            logger.warning(f"Not enough versions to rollback {steps} steps")
            return None
        
        # 找到要回滚到的版本
        sorted_versions = sorted(versions, key=lambda v: v.created_at, reverse=True)
        target_version = sorted_versions[steps]
        
        await self.activate_version(target_version.version_id)
        logger.info(f"Rolled back {param_type} to version: {target_version.version_id}")
        
        return target_version
    
    def get_active_version(self, param_type: ParameterType) -> Optional[ParameterVersion]:
        """获取当前激活的版本"""
        for v in self._versions.get(param_type, []):
            if v.is_active:
                return v
        return None
    
    def get_active_values(self, param_type: ParameterType) -> Dict[str, Any]:
        """获取当前激活版本的参数值"""
        version = self.get_active_version(param_type)
        if version:
            return version.values.copy()
        return {}
    
    async def update_performance_score(
        self,
        version_id: str,
        score: float,
    ) -> bool:
        """更新版本的表现评分"""
        for param_type, versions in self._versions.items():
            for v in versions:
                if v.version_id == version_id:
                    v.performance_score = score
                    await self._update_version_score(version_id, score)
                    logger.info(f"Updated performance score for {version_id}: {score:.2f}")
                    return True
        return False
    
    def get_version_history(
        self,
        param_type: ParameterType,
        limit: int = 10,
    ) -> List[ParameterVersion]:
        """获取版本历史"""
        versions = self._versions.get(param_type, [])
        sorted_versions = sorted(versions, key=lambda v: v.created_at, reverse=True)
        return sorted_versions[:limit]
    
    def get_best_performing_version(
        self,
        param_type: ParameterType,
    ) -> Optional[ParameterVersion]:
        """获取表现最好的版本"""
        versions = [v for v in self._versions.get(param_type, []) if v.performance_score is not None]
        if not versions:
            return None
        return max(versions, key=lambda v: v.performance_score)
    
    async def compare_versions(
        self,
        version_id_a: str,
        version_id_b: str,
    ) -> Dict[str, Any]:
        """比较两个版本的差异"""
        version_a = None
        version_b = None
        
        for versions in self._versions.values():
            for v in versions:
                if v.version_id == version_id_a:
                    version_a = v
                if v.version_id == version_id_b:
                    version_b = v
        
        if not version_a or not version_b:
            return {"error": "Version not found"}
        
        diff = {
            "version_a": version_id_a,
            "version_b": version_id_b,
            "changes": {},
            "performance_diff": None,
        }
        
        # 比较参数值
        all_keys = set(version_a.values.keys()) | set(version_b.values.keys())
        for key in all_keys:
            val_a = version_a.values.get(key)
            val_b = version_b.values.get(key)
            if val_a != val_b:
                diff["changes"][key] = {"a": val_a, "b": val_b}
        
        # 比较表现
        if version_a.performance_score is not None and version_b.performance_score is not None:
            diff["performance_diff"] = version_b.performance_score - version_a.performance_score
        
        return diff
    
    # ── 持久化方法 ──────────────────────────────────────────────────────────
    
    async def _save_version(self, version: ParameterVersion) -> None:
        """保存版本到数据库"""
        if self._pool is None:
            return
        
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO parameter_versions 
                   (version_id, param_type, values, description, created_by, is_active, created_at)
                   VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7)""",
                version.version_id, version.param_type, json.dumps(version.values),
                version.description, version.created_by, version.is_active, version.created_at,
            )
    
    async def _update_version_status(self, version_id: str, is_active: bool) -> None:
        """更新版本激活状态"""
        if self._pool is None:
            return
        
        async with self._pool.acquire() as conn:
            # 先停用同类型的所有版本
            await conn.execute(
                """UPDATE parameter_versions SET is_active = FALSE
                   WHERE param_type = (SELECT param_type FROM parameter_versions WHERE version_id = $1)""",
                version_id,
            )
            # 激活指定版本
            await conn.execute(
                "UPDATE parameter_versions SET is_active = $1 WHERE version_id = $2",
                is_active, version_id,
            )
    
    async def _update_version_score(self, version_id: str, score: float) -> None:
        """更新版本表现评分"""
        if self._pool is None:
            return
        
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE parameter_versions SET performance_score = $1 WHERE version_id = $2",
                score, version_id,
            )
    
    async def load_versions(self) -> None:
        """从数据库加载所有版本"""
        if self._pool is None:
            return
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT version_id, param_type, values, description, created_by, 
                          is_active, performance_score, created_at
                   FROM parameter_versions ORDER BY created_at DESC"""
            )
        
        for row in rows:
            values = json.loads(row["values"]) if isinstance(row["values"], str) else row["values"]
            version = ParameterVersion(
                version_id=row["version_id"],
                param_type=row["param_type"],
                values=values,
                description=row["description"],
                created_by=row["created_by"],
                is_active=row["is_active"],
                performance_score=row["performance_score"],
                created_at=row["created_at"],
            )
            
            param_type = ParameterType(row["param_type"])
            self._versions[param_type].append(version)
            
            if version.is_active:
                self._active_versions[param_type] = version.version_id
        
        logger.info(f"Loaded {sum(len(v) for v in self._versions.values())} parameter versions")
