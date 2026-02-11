"""Cookie 智能管理 — 持久化、自动刷新、指纹一致性。"""

from __future__ import annotations

import json
import logging
import time
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CookieManager:
    """Cookie 智能管理器。

    Features:
    - 按域名/账号持久化 Cookie
    - 自动检测并刷新过期 Cookie
    - 与 FingerprintManager 配合保持一致性
    - 支持从浏览器导入 Cookie
    """

    def __init__(self, storage_dir: Optional[str] = None):
        self._storage_dir = Path(storage_dir or "data/cookies")
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._cookies: Dict[str, Dict[str, CookieEntry]] = {}  # domain -> {name: entry}

    def get_cookies(self, domain: str, account: str = "default") -> Dict[str, str]:
        """获取指定域名的 Cookie。

        Args:
            domain: 域名（如 meituan.com）
            account: 账号标识

        Returns:
            {cookie_name: cookie_value}
        """
        key = f"{domain}:{account}"

        # 尝试从内存缓存
        if key in self._cookies:
            return self._get_valid_cookies(key)

        # 尝试从磁盘加载
        loaded = self._load_from_disk(key)
        if loaded:
            self._cookies[key] = loaded
            return self._get_valid_cookies(key)

        return {}

    def set_cookies(
        self,
        domain: str,
        cookies: Dict[str, str],
        account: str = "default",
        ttl: int = 86400,
    ) -> None:
        """设置 Cookie。

        Args:
            domain: 域名
            cookies: {name: value}
            account: 账号标识
            ttl: 过期时间（秒），默认24小时
        """
        key = f"{domain}:{account}"
        now = time.time()

        if key not in self._cookies:
            self._cookies[key] = {}

        for name, value in cookies.items():
            self._cookies[key][name] = CookieEntry(
                name=name,
                value=value,
                domain=domain,
                expires=now + ttl,
                created=now,
            )

        self._save_to_disk(key)
        logger.debug(f"Set {len(cookies)} cookies for {key}")

    def import_browser_cookies(
        self,
        cookies: List[Dict[str, Any]],
        account: str = "default",
    ) -> int:
        """从浏览器导出的 Cookie 列表导入。

        Args:
            cookies: [{name, value, domain, expirationDate, ...}, ...]
            account: 账号标识

        Returns:
            导入数量
        """
        count = 0
        by_domain: Dict[str, Dict[str, str]] = {}

        for c in cookies:
            domain = c.get("domain", "").lstrip(".")
            name = c.get("name", "")
            value = c.get("value", "")
            if not domain or not name:
                continue

            key = f"{domain}:{account}"
            if key not in self._cookies:
                self._cookies[key] = {}

            expires = c.get("expirationDate", time.time() + 86400)
            self._cookies[key][name] = CookieEntry(
                name=name,
                value=value,
                domain=domain,
                expires=float(expires),
                created=time.time(),
                path=c.get("path", "/"),
                secure=c.get("secure", False),
                http_only=c.get("httpOnly", False),
            )
            count += 1

        # 持久化
        for key in set(f"{c.get('domain', '').lstrip('.')}:{account}" for c in cookies if c.get("domain")):
            self._save_to_disk(key)

        logger.info(f"Imported {count} cookies")
        return count

    def import_from_file(self, path: str, account: str = "default") -> int:
        """从 JSON 文件导入 Cookie。"""
        p = Path(path)
        if not p.exists():
            logger.warning(f"Cookie file not found: {path}")
            return 0

        data = json.loads(p.read_text())
        if isinstance(data, list):
            return self.import_browser_cookies(data, account)
        elif isinstance(data, dict):
            # 简单 {name: value} 格式，需要 domain 信息
            logger.warning("Simple dict format requires domain info, skipping")
            return 0
        return 0

    def is_expired(self, domain: str, account: str = "default") -> bool:
        """检查指定域名的 Cookie 是否过期。"""
        key = f"{domain}:{account}"
        entries = self._cookies.get(key, {})
        if not entries:
            return True
        now = time.time()
        # 如果超过 50% 的 cookie 过期，认为需要刷新
        expired = sum(1 for e in entries.values() if e.expires < now)
        return expired > len(entries) * 0.5

    def clear(self, domain: Optional[str] = None, account: str = "default") -> None:
        """清除 Cookie。"""
        if domain:
            key = f"{domain}:{account}"
            self._cookies.pop(key, None)
            disk_path = self._disk_path(key)
            if disk_path.exists():
                disk_path.unlink()
        else:
            self._cookies.clear()

    def generate_cookie_header(self, domain: str, account: str = "default") -> str:
        """生成 Cookie 请求头字符串。"""
        cookies = self.get_cookies(domain, account)
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    def _get_valid_cookies(self, key: str) -> Dict[str, str]:
        now = time.time()
        entries = self._cookies.get(key, {})
        return {
            name: entry.value
            for name, entry in entries.items()
            if entry.expires > now
        }

    def _disk_path(self, key: str) -> Path:
        safe_name = key.replace(":", "_").replace("/", "_")
        return self._storage_dir / f"{safe_name}.json"

    def _save_to_disk(self, key: str) -> None:
        try:
            entries = self._cookies.get(key, {})
            data = [e.to_dict() for e in entries.values()]
            path = self._disk_path(key)
            path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save cookies to disk: {e}")

    def _load_from_disk(self, key: str) -> Optional[Dict[str, "CookieEntry"]]:
        path = self._disk_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            entries = {}
            for item in data:
                entry = CookieEntry.from_dict(item)
                entries[entry.name] = entry
            return entries
        except Exception as e:
            logger.warning(f"Failed to load cookies from disk: {e}")
            return None


class CookieEntry:
    """单个 Cookie 条目。"""

    def __init__(
        self,
        name: str,
        value: str,
        domain: str,
        expires: float,
        created: float = 0,
        path: str = "/",
        secure: bool = False,
        http_only: bool = False,
    ):
        self.name = name
        self.value = value
        self.domain = domain
        self.expires = expires
        self.created = created or time.time()
        self.path = path
        self.secure = secure
        self.http_only = http_only

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "expires": self.expires,
            "created": self.created,
            "path": self.path,
            "secure": self.secure,
            "httpOnly": self.http_only,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CookieEntry":
        return cls(
            name=data["name"],
            value=data["value"],
            domain=data.get("domain", ""),
            expires=data.get("expires", time.time() + 86400),
            created=data.get("created", time.time()),
            path=data.get("path", "/"),
            secure=data.get("secure", False),
            http_only=data.get("httpOnly", False),
        )
