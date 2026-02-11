"""浏览器指纹管理 — 生成一致的浏览器指纹配置，防止指纹检测。"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 常见分辨率池 ─────────────────────────────────────────────────────────────
DEFAULT_RESOLUTIONS: List[Tuple[int, int]] = [
    (1920, 1080), (1440, 900), (1366, 768), (1536, 864),
    (1280, 720), (1600, 900), (1280, 800), (2560, 1440),
]

# ── 常见 User-Agent 池 ──────────────────────────────────────────────────────
_CHROME_VERSIONS = [
    "120.0.6099.109", "120.0.6099.130", "121.0.6167.85",
    "121.0.6167.140", "122.0.6261.57", "122.0.6261.94",
    "123.0.6312.58", "123.0.6312.86", "124.0.6367.91",
]

_PLATFORMS = [
    ("Win32", "Windows NT 10.0; Win64; x64"),
    ("MacIntel", "Macintosh; Intel Mac OS X 10_15_7"),
    ("MacIntel", "Macintosh; Intel Mac OS X 14_3_1"),
    ("Linux x86_64", "X11; Linux x86_64"),
]

_LANGUAGES_POOL = [
    ["zh-CN", "zh", "en-US", "en"],
    ["zh-CN", "zh"],
    ["zh-CN", "zh", "en"],
    ["en-US", "en", "zh-CN", "zh"],
]

# ── WebGL 渲染器 ─────────────────────────────────────────────────────────────
_WEBGL_RENDERERS = [
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1060 Direct3D11 vs_5_0 ps_5_0)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)"),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0)"),
    ("Google Inc. (Apple)", "ANGLE (Apple, Apple M1 Pro, OpenGL 4.1)"),
    ("Google Inc. (Apple)", "ANGLE (Apple, Apple M2, OpenGL 4.1)"),
]

# ── 时区映射 ─────────────────────────────────────────────────────────────────
_TIMEZONE_MAP = {
    "zh-CN": ("Asia/Shanghai", 480),   # UTC+8
    "en-US": ("America/New_York", -300),
    "ja-JP": ("Asia/Tokyo", 540),
}


@dataclass
class BrowserFingerprint:
    """一个完整的浏览器指纹配置。"""
    session_id: str
    user_agent: str
    platform: str
    screen_width: int
    screen_height: int
    color_depth: int = 24
    pixel_ratio: float = 1.0
    languages: List[str] = field(default_factory=lambda: ["zh-CN", "zh", "en-US", "en"])
    timezone: str = "Asia/Shanghai"
    timezone_offset: int = -480  # getTimezoneOffset() 返回负值
    webgl_vendor: str = ""
    webgl_renderer: str = ""
    canvas_noise_seed: int = 0
    plugins_count: int = 5
    hardware_concurrency: int = 8
    device_memory: int = 8
    max_touch_points: int = 0
    do_not_track: Optional[str] = "1"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_agent": self.user_agent,
            "platform": self.platform,
            "screen": {"width": self.screen_width, "height": self.screen_height},
            "color_depth": self.color_depth,
            "pixel_ratio": self.pixel_ratio,
            "languages": self.languages,
            "timezone": self.timezone,
            "timezone_offset": self.timezone_offset,
            "webgl": {"vendor": self.webgl_vendor, "renderer": self.webgl_renderer},
            "canvas_noise_seed": self.canvas_noise_seed,
            "plugins_count": self.plugins_count,
            "hardware_concurrency": self.hardware_concurrency,
            "device_memory": self.device_memory,
            "max_touch_points": self.max_touch_points,
            "do_not_track": self.do_not_track,
        }

    def generate_inject_js(self) -> str:
        """生成注入到页面的 JS 代码，覆盖浏览器指纹。"""
        fp = self.to_dict()
        return f"""(() => {{
    if (window.__fp_injected) return;
    window.__fp_injected = true;
    const fp = {json.dumps(fp)};

    // Override navigator properties
    const navProps = {{
        platform: fp.platform,
        languages: fp.languages,
        language: fp.languages[0],
        hardwareConcurrency: fp.hardware_concurrency,
        deviceMemory: fp.device_memory,
        maxTouchPoints: fp.max_touch_points,
        doNotTrack: fp.do_not_track,
        userAgent: fp.user_agent,
    }};
    for (const [key, val] of Object.entries(navProps)) {{
        try {{
            Object.defineProperty(navigator, key, {{
                get: () => val, configurable: true
            }});
        }} catch(e) {{}}
    }}

    // Override screen
    const screenProps = {{
        width: fp.screen.width, height: fp.screen.height,
        availWidth: fp.screen.width, availHeight: fp.screen.height - 40,
        colorDepth: fp.color_depth, pixelDepth: fp.color_depth,
    }};
    for (const [key, val] of Object.entries(screenProps)) {{
        try {{
            Object.defineProperty(screen, key, {{
                get: () => val, configurable: true
            }});
        }} catch(e) {{}}
    }}

    // Override devicePixelRatio
    try {{
        Object.defineProperty(window, 'devicePixelRatio', {{
            get: () => fp.pixel_ratio, configurable: true
        }});
    }} catch(e) {{}}

    // Canvas fingerprint noise
    const seed = fp.canvas_noise_seed;
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    const origToBlob = HTMLCanvasElement.prototype.toBlob;
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;

    function addNoise(imageData) {{
        const d = imageData.data;
        let s = seed;
        for (let i = 0; i < d.length; i += 4) {{
            s = (s * 16807 + 0) % 2147483647;
            const n = ((s / 2147483647) - 0.5) * 2;
            d[i] = Math.max(0, Math.min(255, d[i] + n));
        }}
        return imageData;
    }}

    CanvasRenderingContext2D.prototype.getImageData = function() {{
        const imageData = origGetImageData.apply(this, arguments);
        return addNoise(imageData);
    }};

    HTMLCanvasElement.prototype.toDataURL = function() {{
        const ctx = this.getContext('2d');
        if (ctx) {{
            const imageData = origGetImageData.call(ctx, 0, 0, this.width, this.height);
            addNoise(imageData);
            ctx.putImageData(imageData, 0, 0);
        }}
        return origToDataURL.apply(this, arguments);
    }};

    // WebGL fingerprint
    const origGetParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {{
        const UNMASKED_VENDOR = 0x9245;
        const UNMASKED_RENDERER = 0x9246;
        if (param === UNMASKED_VENDOR) return fp.webgl.vendor;
        if (param === UNMASKED_RENDERER) return fp.webgl.renderer;
        return origGetParam.apply(this, arguments);
    }};
    if (typeof WebGL2RenderingContext !== 'undefined') {{
        const origGetParam2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(param) {{
            const UNMASKED_VENDOR = 0x9245;
            const UNMASKED_RENDERER = 0x9246;
            if (param === UNMASKED_VENDOR) return fp.webgl.vendor;
            if (param === UNMASKED_RENDERER) return fp.webgl.renderer;
            return origGetParam2.apply(this, arguments);
        }};
    }}

    // Timezone
    try {{
        const origDTF = Intl.DateTimeFormat;
        const origResolvedOptions = Intl.DateTimeFormat.prototype.resolvedOptions;
        Intl.DateTimeFormat.prototype.resolvedOptions = function() {{
            const opts = origResolvedOptions.call(this);
            opts.timeZone = fp.timezone;
            return opts;
        }};
        Date.prototype.getTimezoneOffset = function() {{
            return fp.timezone_offset;
        }};
    }} catch(e) {{}}
}})()"""


class FingerprintManager:
    """管理浏览器指纹的生命周期：生成、缓存、轮换。"""

    def __init__(
        self,
        rotate_every: int = 3600,
        resolution_pool: Optional[List[Tuple[int, int]]] = None,
        cache_dir: Optional[Path] = None,
    ):
        self._rotate_every = rotate_every
        self._resolution_pool = resolution_pool or DEFAULT_RESOLUTIONS
        self._cache_dir = cache_dir
        self._cache: Dict[str, BrowserFingerprint] = {}

    def get_fingerprint(self, session_key: str = "default") -> BrowserFingerprint:
        """获取指纹，过期自动轮换。

        Args:
            session_key: 会话标识，同一 key 在有效期内返回同一指纹

        Returns:
            BrowserFingerprint 实例
        """
        fp = self._cache.get(session_key)
        if fp and (time.time() - fp.created_at) < self._rotate_every:
            return fp

        fp = self._generate(session_key)
        self._cache[session_key] = fp
        logger.info(f"Generated new fingerprint for session '{session_key}'")

        if self._cache_dir:
            self._save_to_disk(session_key, fp)

        return fp

    def invalidate(self, session_key: str = "default") -> None:
        """强制失效某个 session 的指纹。"""
        self._cache.pop(session_key, None)

    def _generate(self, session_key: str) -> BrowserFingerprint:
        """基于 session_key 生成一致的指纹（同 key 同参数 → 相同指纹）。"""
        # 用 session_key + 当前时间窗口做种子，保证同一时间窗口内一致
        time_window = int(time.time()) // self._rotate_every
        seed_str = f"{session_key}:{time_window}"
        seed = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        platform_name, platform_str = rng.choice(_PLATFORMS)
        chrome_ver = rng.choice(_CHROME_VERSIONS)
        ua = f"Mozilla/5.0 ({platform_str}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_ver} Safari/537.36"

        width, height = rng.choice(self._resolution_pool)
        webgl_vendor, webgl_renderer = rng.choice(_WEBGL_RENDERERS)
        languages = rng.choice(_LANGUAGES_POOL)

        tz_info = _TIMEZONE_MAP.get(languages[0], ("Asia/Shanghai", 480))

        # 根据平台调整
        pixel_ratio = rng.choice([1.0, 1.25, 1.5, 2.0]) if "Mac" in platform_str else rng.choice([1.0, 1.25, 1.5])
        hw_concurrency = rng.choice([4, 8, 12, 16])
        dev_memory = rng.choice([4, 8, 16])
        touch_points = 0 if "Win" in platform_str or "Mac" in platform_str else rng.choice([0, 1, 5])

        return BrowserFingerprint(
            session_id=hashlib.md5(seed_str.encode()).hexdigest()[:12],
            user_agent=ua,
            platform=platform_name,
            screen_width=width,
            screen_height=height,
            pixel_ratio=pixel_ratio,
            languages=languages,
            timezone=tz_info[0],
            timezone_offset=-tz_info[1],
            webgl_vendor=webgl_vendor,
            webgl_renderer=webgl_renderer,
            canvas_noise_seed=rng.randint(1, 2**31 - 1),
            hardware_concurrency=hw_concurrency,
            device_memory=dev_memory,
            max_touch_points=touch_points,
            plugins_count=rng.randint(3, 7),
        )

    def _save_to_disk(self, session_key: str, fp: BrowserFingerprint) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._cache_dir / f"fp_{session_key}.json"
            path.write_text(json.dumps(fp.to_dict(), indent=2))
        except Exception as e:
            logger.warning(f"Failed to save fingerprint to disk: {e}")
