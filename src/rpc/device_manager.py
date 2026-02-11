"""Android 设备管理器 — ADB 连接、虚拟机生命周期、设备池。

支持本地/远程 ADB 设备，虚拟机启停，多设备并行采集与账号轮换。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

MEITUAN_PACKAGE = "com.sankuai.meituan"
MEITUAN_ACTIVITY = "com.meituan.android.pt.homepage.activity.MainActivity"


class DeviceStatus(str, Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    COOLDOWN = "cooldown"
    ERROR = "error"


@dataclass
class DeviceInfo:
    """单个 Android 设备的状态信息。"""
    serial: str
    name: str = ""
    status: DeviceStatus = DeviceStatus.OFFLINE
    account_phone: str = ""
    last_used: float = 0.0
    cooldown_until: float = 0.0
    error_count: int = 0
    max_errors: int = 3
    # 虚拟机相关
    emulator_type: str = ""  # genymotion, leidian, nox, real
    emulator_cmd: str = ""   # 启动命令

    @property
    def is_available(self) -> bool:
        if self.status != DeviceStatus.ONLINE:
            return False
        if self.cooldown_until > time.time():
            return False
        if self.error_count >= self.max_errors:
            return False
        return True


@dataclass
class DevicePool:
    """设备池，支持轮换选择可用设备。"""
    devices: list[DeviceInfo] = field(default_factory=list)
    _index: int = 0

    def add(self, device: DeviceInfo) -> None:
        self.devices.append(device)

    def remove(self, serial: str) -> None:
        self.devices = [d for d in self.devices if d.serial != serial]

    def get(self, serial: str) -> Optional[DeviceInfo]:
        for d in self.devices:
            if d.serial == serial:
                return d
        return None

    def next_available(self) -> Optional[DeviceInfo]:
        """轮询获取下一个可用设备。"""
        if not self.devices:
            return None
        n = len(self.devices)
        for _ in range(n):
            device = self.devices[self._index % n]
            self._index = (self._index + 1) % n
            if device.is_available:
                return device
        return None

    @property
    def available_count(self) -> int:
        return sum(1 for d in self.devices if d.is_available)


class DeviceManager:
    """管理 Android 设备连接和虚拟机生命周期。

    Usage:
        mgr = DeviceManager()
        mgr.add_device("emulator-5554", name="emu1", emulator_type="genymotion")
        mgr.add_device("192.168.1.100:5555", name="remote1")

        await mgr.refresh_all()
        device = mgr.acquire_device()
        # ... 使用设备采集 ...
        mgr.release_device(device.serial)
    """

    def __init__(self, adb_path: str = "adb"):
        self.adb_path = adb_path
        self.pool = DevicePool()

    # ── Device Registration ──────────────────────────────────────────

    def add_device(
        self,
        serial: str,
        name: str = "",
        account_phone: str = "",
        emulator_type: str = "real",
        emulator_cmd: str = "",
    ) -> DeviceInfo:
        """注册一个设备到池中。"""
        device = DeviceInfo(
            serial=serial,
            name=name or serial,
            account_phone=account_phone,
            emulator_type=emulator_type,
            emulator_cmd=emulator_cmd,
        )
        self.pool.add(device)
        logger.info(f"Device registered: {serial} ({name})")
        return device

    def remove_device(self, serial: str) -> None:
        self.pool.remove(serial)
        logger.info(f"Device removed: {serial}")

    # ── ADB Operations ───────────────────────────────────────────────

    async def _adb(self, *args: str, serial: Optional[str] = None) -> tuple[int, str, str]:
        """执行 ADB 命令，返回 (returncode, stdout, stderr)。"""
        cmd = [self.adb_path]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(args)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace").strip(),
            stderr.decode("utf-8", errors="replace").strip(),
        )

    async def connect(self, serial: str) -> bool:
        """连接远程 ADB 设备（IP:port 格式）。"""
        if ":" in serial:
            rc, out, err = await self._adb("connect", serial)
            success = rc == 0 and "connected" in out.lower()
            if not success:
                logger.warning(f"ADB connect failed for {serial}: {err or out}")
            return success
        return True  # 本地设备无需 connect

    async def disconnect(self, serial: str) -> None:
        if ":" in serial:
            await self._adb("disconnect", serial)

    async def list_connected(self) -> list[str]:
        """列出当前 ADB 已连接的设备。"""
        rc, out, _ = await self._adb("devices")
        serials = []
        for line in out.splitlines()[1:]:  # skip "List of devices attached"
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        return serials

    async def refresh_status(self, serial: str) -> DeviceStatus:
        """刷新单个设备的状态。"""
        device = self.pool.get(serial)
        if not device:
            return DeviceStatus.OFFLINE

        connected = await self.list_connected()
        if serial not in connected:
            # 尝试连接
            if not await self.connect(serial):
                device.status = DeviceStatus.OFFLINE
                return DeviceStatus.OFFLINE

        device.status = DeviceStatus.ONLINE
        return DeviceStatus.ONLINE

    async def refresh_all(self) -> dict[str, DeviceStatus]:
        """刷新所有设备状态。"""
        results = {}
        for device in self.pool.devices:
            status = await self.refresh_status(device.serial)
            results[device.serial] = status
        return results

    # ── Emulator Lifecycle ───────────────────────────────────────────

    async def start_emulator(self, serial: str) -> bool:
        """启动虚拟机。"""
        device = self.pool.get(serial)
        if not device or not device.emulator_cmd:
            logger.warning(f"No emulator command for {serial}")
            return False

        logger.info(f"Starting emulator: {serial} ({device.emulator_type})")
        try:
            proc = await asyncio.create_subprocess_shell(
                device.emulator_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            # 等待虚拟机启动（最多 60 秒）
            for _ in range(30):
                await asyncio.sleep(2)
                connected = await self.list_connected()
                if serial in connected:
                    device.status = DeviceStatus.ONLINE
                    logger.info(f"Emulator started: {serial}")
                    return True
            logger.warning(f"Emulator start timeout: {serial}")
            return False
        except Exception as e:
            logger.error(f"Failed to start emulator {serial}: {e}")
            return False

    async def stop_emulator(self, serial: str) -> bool:
        """停止虚拟机。"""
        device = self.pool.get(serial)
        if not device:
            return False

        logger.info(f"Stopping emulator: {serial}")
        rc, _, _ = await self._adb("emu", "kill", serial=serial)
        device.status = DeviceStatus.OFFLINE
        return True

    async def restart_emulator(self, serial: str) -> bool:
        """重启虚拟机。"""
        await self.stop_emulator(serial)
        await asyncio.sleep(3)
        return await self.start_emulator(serial)

    # ── Device Acquisition (for task scheduling) ─────────────────────

    def acquire_device(self) -> Optional[DeviceInfo]:
        """从池中获取一个可用设备，标记为 BUSY。"""
        device = self.pool.next_available()
        if device:
            device.status = DeviceStatus.BUSY
            device.last_used = time.time()
            logger.info(f"Device acquired: {device.serial}")
        return device

    def release_device(self, serial: str, cooldown_seconds: int = 0) -> None:
        """释放设备，可选设置冷却时间。"""
        device = self.pool.get(serial)
        if device:
            device.status = DeviceStatus.ONLINE
            if cooldown_seconds > 0:
                device.cooldown_until = time.time() + cooldown_seconds
                device.status = DeviceStatus.COOLDOWN
            logger.info(f"Device released: {serial} (cooldown={cooldown_seconds}s)")

    def mark_error(self, serial: str) -> None:
        """标记设备错误（累积到 max_errors 后自动停用）。"""
        device = self.pool.get(serial)
        if device:
            device.error_count += 1
            if device.error_count >= device.max_errors:
                device.status = DeviceStatus.ERROR
                logger.warning(f"Device {serial} disabled after {device.error_count} errors")

    def reset_errors(self, serial: str) -> None:
        device = self.pool.get(serial)
        if device:
            device.error_count = 0
            if device.status == DeviceStatus.ERROR:
                device.status = DeviceStatus.ONLINE

    # ── App Checks ───────────────────────────────────────────────────

    async def is_meituan_installed(self, serial: str) -> bool:
        """检查美团 App 是否已安装。"""
        rc, out, _ = await self._adb("shell", "pm", "list", "packages", MEITUAN_PACKAGE, serial=serial)
        return MEITUAN_PACKAGE in out

    async def is_meituan_running(self, serial: str) -> bool:
        """检查美团 App 是否在前台运行。"""
        rc, out, _ = await self._adb(
            "shell", "dumpsys", "activity", "activities",
            serial=serial,
        )
        return MEITUAN_PACKAGE in out.split("\n")[0] if out else False

    async def get_meituan_version(self, serial: str) -> str:
        """获取美团 App 版本号。"""
        rc, out, _ = await self._adb(
            "shell", "dumpsys", "package", MEITUAN_PACKAGE,
            serial=serial,
        )
        for line in out.splitlines():
            if "versionName" in line:
                return line.split("=")[-1].strip()
        return ""

    async def check_device_health(self, serial: str) -> dict:
        """综合检查设备健康状态。"""
        connected = serial in await self.list_connected()
        meituan_installed = await self.is_meituan_installed(serial) if connected else False
        meituan_version = await self.get_meituan_version(serial) if meituan_installed else ""

        return {
            "serial": serial,
            "connected": connected,
            "meituan_installed": meituan_installed,
            "meituan_version": meituan_version,
        }

    # ── Proxy Setup ──────────────────────────────────────────────────

    async def set_proxy(self, serial: str, host: str, port: int) -> bool:
        """为设备设置 HTTP 代理（用于 mitmproxy）。"""
        rc, _, err = await self._adb(
            "shell", "settings", "put", "global", "http_proxy", f"{host}:{port}",
            serial=serial,
        )
        if rc != 0:
            logger.warning(f"Failed to set proxy on {serial}: {err}")
            return False
        logger.info(f"Proxy set on {serial}: {host}:{port}")
        return True

    async def clear_proxy(self, serial: str) -> bool:
        """清除设备代理设置。"""
        rc, _, _ = await self._adb(
            "shell", "settings", "put", "global", "http_proxy", ":0",
            serial=serial,
        )
        return rc == 0
