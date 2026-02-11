"""RPC 设备采集模块 — 通过 Android 虚拟机 + mitmproxy 采集美团竞品数据。

架构：uiautomator2 控制美团 App UI → mitmproxy 拦截 API 响应 → 解析存库

Usage:
    from src.rpc import DeviceManager, MeituanClient, DataExtractor, MeituanProxy, CollectionScheduler
"""

from src.rpc.device_manager import DeviceManager
from src.rpc.meituan_client import MeituanClient
from src.rpc.data_extractor import DataExtractor
from src.rpc.proxy import MeituanProxy
from src.rpc.scheduler import CollectionScheduler

__all__ = [
    "DeviceManager",
    "MeituanClient",
    "DataExtractor",
    "MeituanProxy",
    "CollectionScheduler",
]
