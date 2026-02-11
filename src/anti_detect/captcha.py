"""验证码处理 — 滑块、点选、reCAPTCHA 检测与处理。"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.anti_detect.behavior import generate_slider_path

logger = logging.getLogger(__name__)


class CaptchaType(Enum):
    SLIDER = "slider"
    CLICK_SELECT = "click_select"
    RECAPTCHA = "recaptcha"
    MEITUAN_YODA = "meituan_yoda"
    UNKNOWN = "unknown"


class CaptchaResult:
    def __init__(self, success: bool, captcha_type: CaptchaType, message: str = ""):
        self.success = success
        self.captcha_type = captcha_type
        self.message = message


# ── 验证码检测 JS ─────────────────────────────────────────────────────────────

_JS_DETECT_CAPTCHA = """(() => {
    const indicators = {
        slider: [
            '[class*="slider"]', '[class*="Slider"]',
            '[class*="captcha-slider"]', '[class*="slide-verify"]',
            '#nc_1_wrapper', '.nc-container',
        ],
        click_select: [
            '[class*="click-captcha"]', '[class*="point-captcha"]',
            '[class*="verify-img-panel"]',
        ],
        recaptcha: [
            '.g-recaptcha', '[class*="recaptcha"]', '#recaptcha',
            'iframe[src*="recaptcha"]',
        ],
        meituan_yoda: [
            '[class*="yoda"]', '[class*="Yoda"]',
            '[class*="yoda-slider"]', '#yodaBox',
            'iframe[src*="verify"]',
        ],
    };
    for (const [type, selectors] of Object.entries(indicators)) {
        for (const sel of selectors) {
            if (document.querySelector(sel)) {
                return JSON.stringify({detected: true, type});
            }
        }
    }
    // 检查是否有验证页面的通用信号
    const bodyText = document.body?.innerText || '';
    if (bodyText.includes('验证') && bodyText.includes('滑动') && bodyText.length < 500) {
        return JSON.stringify({detected: true, type: 'slider'});
    }
    if (bodyText.includes('请完成安全验证') || bodyText.includes('人机验证')) {
        return JSON.stringify({detected: true, type: 'unknown'});
    }
    return JSON.stringify({detected: false, type: null});
})()"""

# ── 滑块验证码 JS ─────────────────────────────────────────────────────────────

_JS_GET_SLIDER_INFO = """(() => {
    // 尝试多种滑块选择器
    const sliderSelectors = [
        '.slider-btn', '[class*="slider-btn"]', '[class*="SliderBtn"]',
        '.nc_iconfont', '#nc_1_n1z',
        '[class*="yoda"] [class*="slider"]',
        '[class*="slide-btn"]',
    ];
    const trackSelectors = [
        '.slider-track', '[class*="slider-track"]', '[class*="SliderTrack"]',
        '.nc-lang-cnt', '#nc_1__scale_text',
        '[class*="yoda"] [class*="track"]',
        '[class*="slide-bar"]',
    ];
    let slider = null, track = null;
    for (const sel of sliderSelectors) {
        slider = document.querySelector(sel);
        if (slider) break;
    }
    for (const sel of trackSelectors) {
        track = document.querySelector(sel);
        if (track) break;
    }
    if (!slider || !track) {
        return JSON.stringify({found: false});
    }
    const sliderRect = slider.getBoundingClientRect();
    const trackRect = track.getBoundingClientRect();
    return JSON.stringify({
        found: true,
        slider: {x: sliderRect.x, y: sliderRect.y, w: sliderRect.width, h: sliderRect.height},
        track: {x: trackRect.x, y: trackRect.y, w: trackRect.width, h: trackRect.height},
        distance: trackRect.width - sliderRect.width,
    });
})()"""


def _generate_slider_drag_js(
    start_x: float, start_y: float, distance: float
) -> str:
    """生成模拟滑块拖动的 JS 代码（含贝塞尔曲线轨迹）。"""
    path = generate_slider_path(start_x, distance, steps=30)

    return f"""(async () => {{
    const startX = {start_x};
    const startY = {start_y};
    const path = {json.dumps(path)};

    // mousedown
    const slider = document.elementFromPoint(startX, startY);
    if (!slider) return 'no_slider';

    slider.dispatchEvent(new MouseEvent('mousedown', {{
        clientX: startX, clientY: startY, bubbles: true
    }}));

    // mousemove along path
    for (const [dx, dy, t] of path) {{
        await new Promise(r => setTimeout(r, Math.max(5, (path.indexOf(arguments[0]) > 0 ? t - path[path.indexOf(arguments[0])-1][2] : t))));
        const x = startX + dx;
        const y = startY + dy;
        document.dispatchEvent(new MouseEvent('mousemove', {{
            clientX: x, clientY: y, bubbles: true
        }}));
    }}

    // mouseup at final position
    const lastPoint = path[path.length - 1];
    document.dispatchEvent(new MouseEvent('mouseup', {{
        clientX: startX + lastPoint[0],
        clientY: startY + lastPoint[1],
        bubbles: true
    }}));

    await new Promise(r => setTimeout(r, 500));
    return 'done';
}})()"""


class CaptchaHandler:
    """验证码检测和处理。

    Capabilities:
    - 自动检测验证码类型
    - 滑块验证码：贝塞尔曲线轨迹拖动
    - 点选验证码：通知人工或调用 LLM Vision
    - reCAPTCHA：检测并暂停通知人工
    - 美团 Yoda 滑块：专门适配
    """

    def __init__(
        self,
        max_retries: int = 3,
        on_manual_needed: Optional[Callable] = None,
    ):
        self.max_retries = max_retries
        self.on_manual_needed = on_manual_needed  # 回调：需要人工介入时通知

    async def detect(self, browser_eval: Callable) -> Optional[CaptchaType]:
        """检测页面是否出现验证码。

        Args:
            browser_eval: 执行 JS 的函数（如 cli.browser_eval）

        Returns:
            CaptchaType 或 None（无验证码）
        """
        try:
            raw = await browser_eval(_JS_DETECT_CAPTCHA)
            if not raw:
                return None
            result = json.loads(raw)
            if result.get("detected"):
                ctype = result.get("type", "unknown")
                logger.warning(f"Captcha detected: {ctype}")
                return CaptchaType(ctype)
            return None
        except Exception as e:
            logger.debug(f"Captcha detection error: {e}")
            return None

    async def handle(
        self,
        captcha_type: CaptchaType,
        browser_eval: Callable,
    ) -> CaptchaResult:
        """处理验证码。

        Args:
            captcha_type: 验证码类型
            browser_eval: 执行 JS 的函数

        Returns:
            CaptchaResult
        """
        handlers = {
            CaptchaType.SLIDER: self._handle_slider,
            CaptchaType.MEITUAN_YODA: self._handle_slider,  # Yoda 也是滑块
            CaptchaType.CLICK_SELECT: self._handle_click_select,
            CaptchaType.RECAPTCHA: self._handle_recaptcha,
        }

        handler = handlers.get(captcha_type, self._handle_unknown)
        return await handler(browser_eval)

    async def detect_and_handle(self, browser_eval: Callable) -> Optional[CaptchaResult]:
        """检测并自动处理验证码。无验证码返回 None。"""
        captcha_type = await self.detect(browser_eval)
        if not captcha_type:
            return None

        for attempt in range(1, self.max_retries + 1):
            result = await self.handle(captcha_type, browser_eval)
            if result.success:
                logger.info(f"Captcha solved on attempt {attempt}")
                return result
            logger.warning(f"Captcha attempt {attempt} failed: {result.message}")
            await asyncio.sleep(random.uniform(1, 3))

        logger.error(f"Failed to solve captcha after {self.max_retries} attempts")
        if self.on_manual_needed:
            self.on_manual_needed(captcha_type)
        return CaptchaResult(False, captcha_type, "Max retries exceeded")

    async def _handle_slider(self, browser_eval: Callable) -> CaptchaResult:
        """处理滑块验证码。"""
        try:
            raw = await browser_eval(_JS_GET_SLIDER_INFO)
            if not raw:
                return CaptchaResult(False, CaptchaType.SLIDER, "Cannot find slider")

            info = json.loads(raw)
            if not info.get("found"):
                return CaptchaResult(False, CaptchaType.SLIDER, "Slider not found")

            slider = info["slider"]
            distance = info["distance"]

            start_x = slider["x"] + slider["w"] / 2
            start_y = slider["y"] + slider["h"] / 2

            js = _generate_slider_drag_js(start_x, start_y, distance)
            result = await browser_eval(js)

            # 等待验证结果
            await asyncio.sleep(1.5)

            # 检查是否还有验证码
            still_present = await self.detect(browser_eval)
            if still_present:
                return CaptchaResult(False, CaptchaType.SLIDER, "Slider still present after drag")

            return CaptchaResult(True, CaptchaType.SLIDER, "Slider solved")

        except Exception as e:
            return CaptchaResult(False, CaptchaType.SLIDER, str(e))

    async def _handle_click_select(self, browser_eval: Callable) -> CaptchaResult:
        """处理点选验证码 — 需要 LLM Vision 或人工。"""
        logger.warning("Click-select captcha requires manual intervention or LLM Vision")
        if self.on_manual_needed:
            self.on_manual_needed(CaptchaType.CLICK_SELECT)
        return CaptchaResult(False, CaptchaType.CLICK_SELECT, "Needs manual/LLM intervention")

    async def _handle_recaptcha(self, browser_eval: Callable) -> CaptchaResult:
        """处理 reCAPTCHA — 通知人工。"""
        logger.warning("reCAPTCHA detected — requires manual intervention")
        if self.on_manual_needed:
            self.on_manual_needed(CaptchaType.RECAPTCHA)
        return CaptchaResult(False, CaptchaType.RECAPTCHA, "Needs manual intervention")

    async def _handle_unknown(self, browser_eval: Callable) -> CaptchaResult:
        """未知验证码类型。"""
        logger.warning("Unknown captcha type")
        if self.on_manual_needed:
            self.on_manual_needed(CaptchaType.UNKNOWN)
        return CaptchaResult(False, CaptchaType.UNKNOWN, "Unknown captcha type")
