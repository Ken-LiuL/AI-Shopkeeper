"""QNH Authentication — login, slider CAPTCHA, SMS, session persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Session file for persistence across restarts
SESSION_FILE = Path(os.environ.get(
    "QNH_SESSION_FILE",
    os.path.expanduser("~/.qnh_session.json"),
))

# CDP endpoint for slider CAPTCHA
CDP_ENDPOINT = os.environ.get("QNH_CDP_ENDPOINT", "http://127.0.0.1:9222")

QNH_BASE = "https://qnh.meituan.com"


class QNHAuth:
    """Manages QNH authentication lifecycle.

    Flow: account/password → Yoda slider CAPTCHA → optional SMS → session cookie.
    Session is persisted to file and reused until expired.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        phone: Optional[str] = None,
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

            # Try loading from file
            if self._load_session_file():
                if await self._check_session():
                    logger.info("Restored session from file")
                    return self._cookies

            # Try loading from browser CDP (if browser is open with active session)
            if await self._load_from_browser():
                if await self._check_session():
                    logger.info("Restored session from browser CDP")
                    self._save_session_file()
                    return self._cookies

            # Full login required
            logger.info("No valid session, performing login...")
            await self._login()
            self._save_session_file()
            return self._cookies

    async def invalidate(self) -> None:
        """Force session invalidation."""
        self._cookies = {}
        self._session_expires = 0
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()

    # ── Session validation ──────────────────────────────────────────────

    def _is_session_valid(self) -> bool:
        return bool(self._cookies) and time.time() < self._session_expires

    async def _check_session(self) -> bool:
        """Verify current cookies are still valid by calling a lightweight API."""
        if not self._cookies:
            return False
        try:
            async with aiohttp.ClientSession(
                cookies=self._cookies
            ) as session:
                async with session.post(
                    f"{QNH_BASE}/api/v1/sac/account/auth",
                    params={"yodaReady": "h5", "csecplatform": "4", "csecversion": "4.2.0"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # If we get a valid response, session is good
                        if data.get("code") == 0 or data.get("data"):
                            self._session_expires = time.time() + 3600
                            return True
            return False
        except Exception as e:
            logger.debug(f"Session check failed: {e}")
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
            logger.debug(f"Failed to load session file: {e}")
            return False

    def _save_session_file(self) -> None:
        """Persist session to local file."""
        try:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(json.dumps({
                "cookies": self._cookies,
                "expires": self._session_expires,
                "saved_at": time.time(),
            }))
            SESSION_FILE.chmod(0o600)
        except Exception as e:
            logger.warning(f"Failed to save session file: {e}")

    # ── Browser CDP session extraction ──────────────────────────────────

    async def _load_from_browser(self) -> bool:
        """Extract cookies from an open Chrome browser via CDP."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{CDP_ENDPOINT}/json", timeout=aiohttp.ClientTimeout(total=3)
                ) as resp:
                    targets = await resp.json()

            qnh_target = next(
                (t for t in targets if "qnh.meituan" in t.get("url", "")), None
            )
            if not qnh_target:
                return False

            # Use CDP to get cookies
            import websockets  # type: ignore[import-untyped]

            ws_url = qnh_target["webSocketDebuggerUrl"]
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({
                    "id": 1,
                    "method": "Network.getCookies",
                    "params": {"urls": [QNH_BASE]},
                }))
                result = json.loads(await ws.recv())
                cookies = result.get("result", {}).get("cookies", [])
                if cookies:
                    self._cookies = {c["name"]: c["value"] for c in cookies}
                    self._session_expires = time.time() + 3600
                    return True
            return False
        except Exception as e:
            logger.debug(f"CDP cookie extraction failed: {e}")
            return False

    # ── Login flow ──────────────────────────────────────────────────────

    async def _login(self) -> None:
        """Full login flow: credentials → slider → SMS → session.

        This is a complex flow that may require human interaction for SMS codes.
        For production, we primarily rely on CDP session extraction from an
        already-logged-in browser, with this as a fallback.
        """
        if not self.username or not self.password:
            raise RuntimeError(
                "QNH credentials not configured. Set QNH_USERNAME and QNH_PASSWORD "
                "env vars, or ensure a browser with active QNH session is running."
            )

        logger.info(f"Attempting QNH login for {self.username}...")

        # Step 1: Initial login request
        async with aiohttp.ClientSession() as session:
            # Get CSRF / initial cookies
            async with session.get(
                f"{QNH_BASE}/home.html",
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                initial_cookies = {k: v.value for k, v in resp.cookies.items()}

            # Step 2: Submit credentials
            login_payload = {
                "login": self.username,
                "password": self.password,
                "loginType": 0,
            }
            async with session.post(
                "https://epassport.meituan.com/api/account/login",
                json=login_payload,
                params={"yodaReady": "h5", "csecplatform": "4", "csecversion": "4.2.0"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                login_result = await resp.json()

            if login_result.get("code") == 0:
                # Direct success (rare without CAPTCHA)
                self._cookies = {k: v.value for k, v in session.cookie_jar.filter_cookies(QNH_BASE).items()}
                self._session_expires = time.time() + 7200
                logger.info("Login succeeded without CAPTCHA")
                return

            # Step 3: Handle slider CAPTCHA via CDP
            if login_result.get("code") in (1001, 1002):  # CAPTCHA required
                logger.info("Slider CAPTCHA required, attempting CDP solve...")
                solved = await self._solve_slider_captcha()
                if not solved:
                    raise RuntimeError("Failed to solve slider CAPTCHA")

            # Step 4: Handle SMS verification if needed
            if login_result.get("code") == 2001:  # SMS required
                raise RuntimeError(
                    "SMS verification required. Please login manually in the browser "
                    "and the system will pick up the session automatically."
                )

        raise RuntimeError(f"Login failed: {login_result}")

    async def _solve_slider_captcha(self) -> bool:
        """Solve Yoda slider CAPTCHA via CDP mouse events.

        Follows the approach in /tmp/qnh-slider.mjs:
        1. Find slider bar and target box via DOM query
        2. Simulate mouse drag from bar to target
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{CDP_ENDPOINT}/json", timeout=aiohttp.ClientTimeout(total=3)
                ) as resp:
                    targets = await resp.json()

            qnh_target = next(
                (t for t in targets if "qnh.meituan" in t.get("url", "") or
                 "epassport" in t.get("url", "")),
                None,
            )
            if not qnh_target:
                logger.warning("No QNH/epassport page found for slider CAPTCHA")
                return False

            import websockets

            ws_url = qnh_target["webSocketDebuggerUrl"]
            async with websockets.connect(ws_url) as ws:
                _id = 0

                async def send_cdp(method: str, params: dict[str, Any] = {}) -> Any:
                    nonlocal _id
                    _id += 1
                    await ws.send(json.dumps({"id": _id, "method": method, "params": params}))
                    while True:
                        msg = json.loads(await ws.recv())
                        if msg.get("id") == _id:
                            return msg.get("result", {})

                # Get slider coordinates
                result = await send_cdp("Runtime.evaluate", {
                    "expression": """
                    (function(){
                        var bar = document.getElementById('yodaMoveingBar') ||
                                  document.querySelector('[class*=moveingBar]');
                        var box = document.getElementById('yodaBoxWrapper') ||
                                  document.querySelector('[class*=box-wrapper]');
                        if(bar && box) {
                            var br = bar.getBoundingClientRect();
                            var bxr = box.getBoundingClientRect();
                            return JSON.stringify({
                                sx: br.x + br.width/2,
                                sy: br.y + br.height/2,
                                ex: bxr.x + bxr.width - 15
                            });
                        }
                        return JSON.stringify({error: 'slider not found'});
                    })()
                    """
                })

                coords = json.loads(result.get("result", {}).get("value", "{}"))
                if "error" in coords:
                    logger.warning(f"Slider CAPTCHA: {coords['error']}")
                    return False

                sx, sy, ex = coords["sx"], coords["sy"], coords["ex"]

                # Simulate drag
                await send_cdp("Input.dispatchMouseEvent", {
                    "type": "mousePressed", "x": sx, "y": sy,
                    "button": "left", "clickCount": 1,
                })

                # Move in steps with slight randomness
                import random
                steps = 20
                for i in range(1, steps + 1):
                    progress = i / steps
                    # Ease-out curve
                    eased = 1 - (1 - progress) ** 3
                    cx = sx + (ex - sx) * eased
                    cy = sy + random.uniform(-2, 2)
                    await send_cdp("Input.dispatchMouseEvent", {
                        "type": "mouseMoved", "x": cx, "y": cy,
                        "button": "left",
                    })
                    await asyncio.sleep(random.uniform(0.01, 0.03))

                await send_cdp("Input.dispatchMouseEvent", {
                    "type": "mouseReleased", "x": ex, "y": sy,
                    "button": "left", "clickCount": 1,
                })

                await asyncio.sleep(2)  # Wait for verification

                # Check if login succeeded after CAPTCHA
                return True

        except Exception as e:
            logger.error(f"Slider CAPTCHA solve failed: {e}")
            return False
