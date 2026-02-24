"""行为模拟 — 鼠标轨迹、滚动、输入、页面停留等人类行为模拟。"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BehaviorConfig:
    """行为模拟参数配置。"""

    typing_speed_ms: tuple[int, int] = (50, 200)
    scroll_pause_ms: tuple[int, int] = (1000, 5000)
    page_stay_ms: tuple[int, int] = (3000, 30000)
    click_offset_px: int = 3
    mouse_steps: int = 20
    scroll_speed_variation: float = 0.4  # ±40% 速度变化
    typo_probability: float = 0.05  # 5% 概率打错字


def _bezier_point(t: float, p0: float, p1: float, p2: float, p3: float) -> float:
    """三次贝塞尔曲线插值。"""
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3


def generate_mouse_path(
    start: tuple[float, float],
    end: tuple[float, float],
    steps: int = 20,
    jitter: float = 3.0,
) -> list[tuple[float, float]]:
    """生成贝塞尔曲线鼠标轨迹 + 随机抖动。

    Args:
        start: 起点 (x, y)
        end: 终点 (x, y)
        steps: 轨迹点数量
        jitter: 随机抖动幅度 (px)

    Returns:
        轨迹点列表 [(x, y), ...]
    """
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    dist = math.sqrt(dx * dx + dy * dy)

    # 控制点：偏离直线方向，模拟手腕弧度
    offset = dist * random.uniform(0.1, 0.4)
    angle = random.uniform(-math.pi / 3, math.pi / 3)

    mid_x = (sx + ex) / 2 + offset * math.cos(angle)
    mid_y = (sy + ey) / 2 + offset * math.sin(angle)

    # 两个控制点
    cp1x = sx + (mid_x - sx) * random.uniform(0.3, 0.7)
    cp1y = sy + (mid_y - sy) * random.uniform(0.3, 0.7)
    cp2x = mid_x + (ex - mid_x) * random.uniform(0.3, 0.7)
    cp2y = mid_y + (ey - mid_y) * random.uniform(0.3, 0.7)

    path = []
    for i in range(steps + 1):
        t = i / steps
        # 非匀速：加入缓动效果（开始慢-中间快-结束慢）
        t_eased = t * t * (3 - 2 * t)  # smoothstep
        x = _bezier_point(t_eased, sx, cp1x, cp2x, ex)
        y = _bezier_point(t_eased, sy, cp1y, cp2y, ey)

        # 加入微小抖动（越接近终点抖动越小）
        remaining = 1 - t
        jit = jitter * remaining
        x += random.gauss(0, jit * 0.3)
        y += random.gauss(0, jit * 0.3)

        path.append((round(x, 1), round(y, 1)))

    return path


def generate_slider_path(
    start_x: float,
    distance: float,
    steps: int = 30,
) -> list[tuple[float, float, int]]:
    """生成滑块验证码拖动轨迹 (x_offset, y_offset, time_ms)。

    模拟：快速启动 → 减速 → 微调。
    """
    path: list[tuple[float, float, int]] = [(0, 0, 0)]
    total_time = 0
    current_x = 0.0

    for i in range(1, steps + 1):
        progress = i / steps

        # 加速-减速模型：前30%加速，中间40%匀速，后30%减速+微调
        if progress < 0.3:
            speed_factor = progress / 0.3 * 1.5
        elif progress < 0.7:
            speed_factor = 1.5
        else:
            # 减速 + 偶尔超过目标再回来
            decel = (progress - 0.7) / 0.3
            speed_factor = 1.5 * (1 - decel * 0.9)

        step_dist = (distance / steps) * speed_factor
        current_x += step_dist

        # 时间间隔：快的部分间隔短，慢的部分间隔长
        dt = random.randint(8, 25) if speed_factor > 1.0 else random.randint(20, 60)
        total_time += dt

        # y 轴微小偏移
        y_offset = random.gauss(0, 1.5)

        path.append((round(current_x, 1), round(y_offset, 1), total_time))

    # 最后微调到精确位置
    overshoot = current_x - distance
    if abs(overshoot) > 1:
        total_time += random.randint(50, 150)
        path.append(
            (
                round(distance + random.uniform(-0.5, 0.5), 1),
                round(random.gauss(0, 0.5), 1),
                total_time,
            )
        )

    total_time += random.randint(30, 80)
    path.append((round(distance, 1), 0, total_time))

    return path


class BehaviorSimulator:
    """行为模拟器 — 生成 JS 代码注入或直接通过 CDP 执行。"""

    def __init__(self, config: BehaviorConfig | None = None):
        self.config = config or BehaviorConfig()

    async def random_delay(self, min_ms: int | None = None, max_ms: int | None = None) -> None:
        """基于行为模型的随机延迟。"""
        lo = min_ms or self.config.page_stay_ms[0]
        hi = max_ms or self.config.page_stay_ms[1]
        # 使用对数正态分布，更像人类
        mean = (lo + hi) / 2
        sigma = (hi - lo) / 4
        delay = max(lo, min(hi, random.gauss(mean, sigma)))
        await asyncio.sleep(delay / 1000)

    async def typing_delay(self) -> None:
        """单个按键间延迟。"""
        lo, hi = self.config.typing_speed_ms
        # 偶尔有长停顿（思考）
        if random.random() < 0.05:
            await asyncio.sleep(random.uniform(0.3, 0.8))
        else:
            await asyncio.sleep(random.uniform(lo / 1000, hi / 1000))

    def generate_typing_sequence(self, text: str) -> list[dict]:
        """生成打字序列，包括偶尔的退格修正。

        Returns:
            [{"action": "type", "char": "x", "delay_ms": 120}, ...]
        """
        sequence = []
        rng = random.Random()

        for _i, char in enumerate(text):
            # 偶尔打错字再退格
            if rng.random() < self.config.typo_probability and char.isalpha():
                wrong_char = chr(ord(char) + rng.choice([-1, 1]))
                sequence.append(
                    {
                        "action": "type",
                        "char": wrong_char,
                        "delay_ms": rng.randint(*self.config.typing_speed_ms),
                    }
                )
                sequence.append(
                    {
                        "action": "type",
                        "char": "Backspace",
                        "delay_ms": rng.randint(50, 150),
                    }
                )

            delay = rng.randint(*self.config.typing_speed_ms)
            # 空格/标点后偶尔长停顿
            if char in " ,.;!?" and rng.random() < 0.2:
                delay += rng.randint(200, 500)

            sequence.append(
                {
                    "action": "type",
                    "char": char,
                    "delay_ms": delay,
                }
            )

        return sequence

    def generate_scroll_js(
        self,
        total_distance: int = 2000,
        viewport_height: int = 800,
    ) -> str:
        """生成模拟人类滚动的 JS 代码。"""
        segments = []
        current = 0
        while current < total_distance:
            # 每次滚动距离：100-400px
            scroll_amount = random.randint(100, 400)
            scroll_amount = min(scroll_amount, total_distance - current)

            # 速度变化
            speed_var = 1 + random.uniform(
                -self.config.scroll_speed_variation, self.config.scroll_speed_variation
            )
            duration = int(300 * speed_var)

            # 滚动后停顿
            pause = random.randint(*self.config.scroll_pause_ms)

            segments.append({"amount": scroll_amount, "duration": duration, "pause": pause})
            current += scroll_amount

            # 5% 概率回滚一点（模拟回看）
            if random.random() < 0.05 and current > 200:
                back = random.randint(50, 200)
                segments.append(
                    {
                        "amount": -back,
                        "duration": random.randint(200, 400),
                        "pause": random.randint(500, 1500),
                    }
                )
                current -= back

            # 10% 概率长停顿（模拟阅读）
            if random.random() < 0.1:
                segments[-1]["pause"] += random.randint(2000, 5000)

        return f"""(async () => {{
    const segments = {json.dumps(segments)};
    for (const seg of segments) {{
        await new Promise(r => {{
            const start = performance.now();
            const startY = window.scrollY;
            const step = (ts) => {{
                const elapsed = ts - start;
                const progress = Math.min(elapsed / seg.duration, 1);
                const eased = progress * (2 - progress); // easeOut
                window.scrollTo(0, startY + seg.amount * eased);
                if (progress < 1) requestAnimationFrame(step);
                else r();
            }};
            requestAnimationFrame(step);
        }});
        await new Promise(r => setTimeout(r, seg.pause));
    }}
}})()"""

    def generate_click_offset(self) -> tuple[int, int]:
        """生成不精确的点击偏移。"""
        px = self.config.click_offset_px
        return (
            round(random.gauss(0, px * 0.5)),
            round(random.gauss(0, px * 0.5)),
        )

    def generate_mouse_move_js(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> str:
        """生成鼠标移动的 JS（触发 mousemove 事件）。"""
        path = generate_mouse_path(start, end, steps=self.config.mouse_steps)
        # 每步间隔
        intervals = [random.randint(5, 20) for _ in path]

        return f"""(async () => {{
    const path = {json.dumps(path)};
    const intervals = {json.dumps(intervals)};
    for (let i = 0; i < path.length; i++) {{
        const [x, y] = path[i];
        const evt = new MouseEvent('mousemove', {{
            clientX: x, clientY: y, bubbles: true
        }});
        document.elementFromPoint(x, y)?.dispatchEvent(evt);
        await new Promise(r => setTimeout(r, intervals[i]));
    }}
}})()"""

    def estimate_page_stay(self, content_length: int = 0) -> int:
        """根据内容长度估算合理的页面停留时间 (ms)。"""
        lo, hi = self.config.page_stay_ms
        if content_length > 0:
            # 假设阅读速度 ~500字/分钟
            read_time = (content_length / 500) * 60 * 1000
            return int(max(lo, min(hi, read_time * random.uniform(0.3, 0.7))))
        return random.randint(lo, hi)


# 需要 import json 用于 JS 生成
