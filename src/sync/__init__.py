"""数据同步模块 — ETL 数据处理 + Chrome 扩展/手动上传接收。

数据采集已迁移至 Chrome 扩展 + 手动上传模式，
此模块仅保留 ETL 数据处理和基础工具。
"""

from .base import BaseSyncer, SyncMode, SyncResult
from .utils import RateLimitedSession

__all__ = [
    "BaseSyncer",
    "SyncResult",
    "SyncMode",
    "RateLimitedSession",
]
