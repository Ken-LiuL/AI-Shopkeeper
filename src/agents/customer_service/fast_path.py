"""Fast-path 秒回模块 — 拦截确定性高频简单消息，无需调 LLM。"""

from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# ── 快速匹配集合 ──────────────────────────────────────────────────────────

FAST_PATH_GREETINGS = frozenset({
    "你好", "您好", "在吗", "在不在", "有人吗", "hi", "hello",
    "你好啊", "您好啊", "嗨", "hey", "ni hao",
})

FAST_PATH_THANKS = frozenset({
    "谢谢", "谢谢你", "谢谢您", "感谢", "多谢", "thank you",
    "thanks", "非常感谢", "太感谢了", "感谢您",
})

FAST_PATH_ACKS = frozenset({
    "好的", "嗯嗯", "嗯", "知道了", "收到", "好哒", "ok", "okay",
})

GREETING_REPLIES = [
    "亲，您好！😊 欢迎光临，请问有什么可以帮您的呢？",
    "您好亲！🌟 我是AI客服小康，随时为您服务，请问有什么需要帮忙吗？",
    "亲好！😊 很高兴为您服务，请问想了解哪方面的商品或问题呢？",
]
THANKS_REPLIES = [
    "亲，不客气！😊 还有其他需要帮忙的吗？",
    "应该的亲！🌟 如有任何问题随时告诉我哦~",
    "不用谢亲！😊 祝您购物愉快，有需要随时来找我~",
]
ACK_REPLIES = [
    "亲，好的！😊 有其他问题随时告诉我哦~",
    "好的亲！🌟 如还有需要帮忙的随时找我~",
]

FAST_GREETING_COOLDOWN_SECONDS = 10 * 60

# 记录最近 fast-path 回复时间
_fast_path_timestamps: dict[str, float] = {}


def new_ai_reply_id() -> str:
    return f"csr-{uuid.uuid4().hex}"


def is_non_actionable_placeholder(message: str) -> bool:
    """检测平台占位消息（图片、卡片等非文本内容）。"""
    placeholder_patterns = [
        "[图片]", "[语音]", "[视频]", "[动画表情]", "[位置]", "[名片]",
        "[链接]", "[文件]", "[红包]", "[转账]", "[商品卡片]", "[小程序]",
    ]
    stripped = message.strip()
    if not stripped:
        return True
    for pat in placeholder_patterns:
        if stripped == pat:
            return True
    if stripped.startswith("[") and stripped.endswith("]") and len(stripped) < 20:
        return True
    return False


def has_recent_fast_greeting(
    session_id: str,
    cooldown: float = FAST_GREETING_COOLDOWN_SECONDS,
) -> bool:
    """检查是否在冷却期内已发过快速回复。"""
    last_ts = _fast_path_timestamps.get(session_id)
    if last_ts and (time.time() - last_ts) < cooldown:
        return True
    return False


def try_fast_path(
    session_id: str,
    message: str,
    *,
    ai_reply_id: str | None = None,
    conversation_history: list[dict] | None = None,
) -> dict[str, Any] | None:
    """尝试快速路径回复。返回 None 表示不匹配，需要走完整管线。"""
    if ai_reply_id is None:
        ai_reply_id = new_ai_reply_id()

    normalized = message.strip().lower().rstrip("!！~～。.?？")

    def _make_response(reply: str, intent: str) -> dict[str, Any]:
        _fast_path_timestamps[session_id] = time.time()
        return {
            "session_id": session_id,
            "reply": reply,
            "ai_reply_id": ai_reply_id,
            "intent": intent,
            "sources": [],
            "needs_human": False,
            "action": {"type": "none"},
            "product_cards": [],
        }

    # 问候语
    if normalized in FAST_PATH_GREETINGS:
        if has_recent_fast_greeting(session_id):
            return None  # 冷却期内不秒回，走完整管线
        return _make_response(random.choice(GREETING_REPLIES), "greeting")

    # 感谢
    if normalized in FAST_PATH_THANKS:
        return _make_response(random.choice(THANKS_REPLIES), "thanks")

    # 确认
    if normalized in FAST_PATH_ACKS:
        return _make_response(random.choice(ACK_REPLIES), "acknowledgement")

    return None
