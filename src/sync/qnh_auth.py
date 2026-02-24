"""QNH Authentication — cookie-based auth from config file or environment variable."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

# Cookie config file path (relative to project root)
COOKIE_CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "qnh_cookies.json"

# Session file for persistence across restarts
SESSION_FILE = Path(
    os.environ.get(
        "QNH_SESSION_FILE",
        os.path.expanduser("~/.qnh_session.json"),
    )
)

QNH_BASE = "https://qnh.meituan.com"


class QNHAuth:
    """Manages QNH authentication via pre-configured cookies.

    Cookie loading priority:
    1. config/qnh_cookies.json (local file, for development)
    2. QNH_COOKIES_JSON environment variable (for Render/production)
    3. Fallback to session file (~/.qnh_session.json)
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        phone: str | None = None,
    ) -> None:
        self.username = username or os.environ.get("QNH_USERNAME", "")
        self.password = password or os.environ.get("QNH_PASSWORD", "")
        self.phone = phone or os.environ.get("QNH_PHONE", "")
        self._cookies: dict[str, str] = {}
        self._session_expires: float = 0
        self._lock = asyncio.Lock()

    # ── Public API ──────────────────────────────────────────────────────

    async def get_cookies(self) -> dict[str, str]:
        """Get valid session cookies, refreshing if needed."""
        async with self._lock:
            if self._is_session_valid():
                return self._cookies

            # 1. Try loading from config file
            cookies = self._load_from_config_file()
            if cookies:
                self._cookies = cookies
                self._session_expires = time.time() + 7200  # 2 hours
                if await self._check_session():
                    logger.info("Loaded cookies from config file (%s)", COOKIE_CONFIG_FILE)
                    return self._cookies
                else:
                    logger.warning(
                        "Config file cookies failed session check, but using them anyway"
                    )
                    # Still use them — the check endpoint might not be reliable
                    return self._cookies

            # 2. Try loading from environment variable
            cookies = self._load_from_env()
            if cookies:
                self._cookies = cookies
                self._session_expires = time.time() + 7200
                logger.info("Loaded cookies from QNH_COOKIES_JSON env var")
                return self._cookies

            # 3. Try loading from session file
            if self._load_session_file() and await self._check_session():
                logger.info("Restored session from file")
                return self._cookies

            # No valid cookies found
            raise RuntimeError(
                "No QNH cookies available. Either:\n"
                "  1. Create config/qnh_cookies.json with cookie values, or\n"
                "  2. Set QNH_COOKIES_JSON environment variable with JSON cookie dict"
            )

    async def invalidate(self) -> None:
        """Force session invalidation."""
        self._cookies = {}
        self._session_expires = 0
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()

    # ── Cookie loading methods ──────────────────────────────────────────

    def _load_from_config_file(self) -> dict[str, str]:
        """Load cookies from config/qnh_cookies.json."""
        try:
            if not COOKIE_CONFIG_FILE.exists():
                return {}
            data = json.loads(COOKIE_CONFIG_FILE.read_text())
            if isinstance(data, dict) and data:
                logger.debug("Found %d cookies in config file", len(data))
                return {str(k): str(v) for k, v in data.items()}
            return {}
        except Exception as e:
            logger.warning("Failed to load config file cookies: %s", e)
            return {}

    def _load_from_env(self) -> dict[str, str]:
        """Load cookies from QNH_COOKIES_JSON environment variable."""
        env_val = os.environ.get("QNH_COOKIES_JSON", "").strip()
        if not env_val:
            return {}
        try:
            data = json.loads(env_val)
            if isinstance(data, dict) and data:
                logger.debug("Found %d cookies in QNH_COOKIES_JSON env", len(data))
                return {str(k): str(v) for k, v in data.items()}
            return {}
        except Exception as e:
            logger.warning("Failed to parse QNH_COOKIES_JSON: %s", e)
            return {}

    # ── Session validation ──────────────────────────────────────────────

    def _is_session_valid(self) -> bool:
        return bool(self._cookies) and time.time() < self._session_expires

    async def _check_session(self) -> bool:
        """Verify current cookies are still valid by calling a lightweight API."""
        if not self._cookies:
            return False
        try:
            async with (
                aiohttp.ClientSession(cookies=self._cookies) as session,
                session.post(
                    f"{QNH_BASE}/api/v1/sac/account/auth",
                    params={"yodaReady": "h5", "csecplatform": "4", "csecversion": "4.2.0"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp,
            ):
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 0 or data.get("data"):
                        self._session_expires = time.time() + 7200
                        return True
            return False
        except Exception as e:
            logger.debug("Session check failed: %s", e)
            return False

    # ── Session persistence ─────────────────────────────────────────────

    def _load_session_file(self) -> bool:
        """Load session from local file."""
        try:
            if not SESSION_FILE.exists():
                return False
            data = json.loads(SESSION_FILE.read_text())
            if data.get("expires", 0) < time.time():
                return False
            self._cookies = data.get("cookies", {})
            self._session_expires = data["expires"]
            return bool(self._cookies)
        except Exception as e:
            logger.debug("Failed to load session file: %s", e)
            return False

    def _save_session_file(self) -> None:
        """Persist session to local file."""
        try:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(
                json.dumps(
                    {
                        "cookies": self._cookies,
                        "expires": self._session_expires,
                        "saved_at": time.time(),
                    }
                )
            )
            SESSION_FILE.chmod(0o600)
        except Exception as e:
            logger.warning("Failed to save session file: %s", e)
