"""意图识别模块 — 快速规则意图 + 可选 LLM 意图精分。

对应 SPEC 4.2 Intent Sub-Agent：
- 快速路径：规则匹配 → 确定性分流
- LLM 路径（可选）：复杂消息的意图识别 + 实体提取
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── 意图常量 ──────────────────────────────────────────────────────────────

PRODUCT_INTENTS = {"product_inquiry", "recommendation", "usage_question"}
ORDER_INTENTS = {"logistics", "after_sales", "refund"}
PROFILE_INTENTS = {"recommendation", "product_inquiry"}
POLICY_INTENTS = {"after_sales", "complaint", "refund", "return_exchange"}
PROMPT_ENHANCER_INTENTS = {"product_inquiry", "recommendation", "usage_question"}
HUMAN_HANDOFF_INTENTS = {"complaint", "after_sales"}

# ── 规则匹配关键词 ──────────────────────────────────────────────────────────

_PRODUCT_KEYWORDS = re.compile(
    r"推荐|有没有|什么.*好|哪个.*好|哪款|适合|怎么选|选什么|有啥|想买|要买|"
    r"血压计|体温计|雾化器|血糖仪|制氧机|轮椅|拐杖|护具|"
    r"多少钱|价格|便宜|贵|优惠|折扣|促销"
)

_ORDER_KEYWORDS = re.compile(
    r"快递|物流|配送|到了吗|什么时候到|到哪了|发货|送达|骑手|"
    r"退货|退款|换货|退回|售后|维修|保修|质量问题"
)

_USAGE_KEYWORDS = re.compile(
    r"怎么用|使用方法|用法|操作|说明书|注意事项|副作用|禁忌|"
    r"充电|安装|清洗|消毒|校准"
)

_COMPLAINT_KEYWORDS = re.compile(
    r"投诉|差评|太慢|态度|骗|假|差劲|垃圾|不满|生气|愤怒|"
    r"消协|12315|举报|工商"
)


def quick_intent_guess(
    message: str,
    conversation_history: list[dict] | None = None,
) -> str:
    """快速规则意图识别（零延迟，用于预加载分流）。"""
    text = message.strip().lower()

    # 投诉优先判定（需要转人工）
    if _COMPLAINT_KEYWORDS.search(text):
        return "complaint"

    # 订单/物流
    if _ORDER_KEYWORDS.search(text):
        if "退" in text or "售后" in text or "换" in text:
            return "after_sales"
        return "logistics"

    # 使用问题
    if _USAGE_KEYWORDS.search(text):
        return "usage_question"

    # 商品咨询/推荐
    if _PRODUCT_KEYWORDS.search(text):
        if "推荐" in text or "哪" in text or "适合" in text:
            return "recommendation"
        return "product_inquiry"

    # 历史上下文分析
    if conversation_history:
        recent_messages = conversation_history[-4:]
        for msg in recent_messages:
            content = str(msg.get("content", "")).lower()
            if _PRODUCT_KEYWORDS.search(content):
                return "product_inquiry"
            if _ORDER_KEYWORDS.search(content):
                return "logistics"

    return "other"


def should_run_product_pipeline(quick_intent: str, conversation_history: list[dict] | None) -> bool:
    """判断是否需要运行商品检索管线。"""
    return quick_intent in PRODUCT_INTENTS or bool(
        conversation_history and _history_has_product_signals(conversation_history)
    )


def _history_has_product_signals(conversation_history: list[dict]) -> bool:
    """检查对话历史中是否有商品相关信号。"""
    for msg in (conversation_history or [])[-4:]:
        content = str(msg.get("content", "")).lower()
        if _PRODUCT_KEYWORDS.search(content):
            return True
    return False


def select_context_by_intent(intent: str, has_product_history: bool = False) -> set[str]:
    """根据意图决定需要加载哪些上下文。"""
    contexts: set[str] = {"faq"}

    if intent in PRODUCT_INTENTS or has_product_history:
        contexts.add("products")

    if intent in ORDER_INTENTS:
        contexts.add("orders")

    if intent in PROFILE_INTENTS:
        contexts.add("profile")

    if intent in POLICY_INTENTS:
        contexts.add("policy")

    if intent in PROMPT_ENHANCER_INTENTS:
        contexts.update({"few_shot", "negative_examples"})

    return contexts
