"""
医疗器械通用合规规则（跨模块共享）

本模块被以下模块共享使用：
  - src.agents.customer_service.compliance  (客服硬拦截/软替换)
  - src.agents.listing.nodes                (上架合规后处理)

设计原则：
  - 本模块只定义规则常量和工具函数，不含副作用
  - 客服合规模块（compliance.py）的现有逻辑不受影响
  - 上架模块使用本模块中的规则执行后处理过滤
"""

from __future__ import annotations

import re
from typing import TypedDict

# =============================================================================
# 通用禁忌词（客服 + 上架共用）
# =============================================================================

# ── 诊断性语言（硬拦截级别） ──────────────────────────────────────────────────
PROHIBITED_DIAGNOSTIC_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"你这是.{0,10}病"), "诊断性语言"),
    (re.compile(r"你得了.{0,15}"), "诊断性语言"),
    (re.compile(r"确诊"), "诊断性语言"),
    (re.compile(r"诊断为"), "诊断性语言"),
]

# ── 处方建议（硬拦截级别） ────────────────────────────────────────────────────
PROHIBITED_PRESCRIPTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"建议你(吃|服用).{0,15}药"), "处方建议"),
    (re.compile(r"一天(吃|服用|用)\s*\d+\s*次"), "处方建议"),
    (re.compile(r"用量\s*\d+\s*(mg|毫克|克|ml|毫升)", re.IGNORECASE), "处方建议"),
]

# ── 绝对化承诺（硬拦截级别） ──────────────────────────────────────────────────
PROHIBITED_ABSOLUTE_CLAIMS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"保证有效"), "绝对化承诺"),
    (re.compile(r"100\s*%\s*(治愈|治好|有效)"), "绝对化承诺"),
    (re.compile(r"彻底(治愈|治好)"), "绝对化承诺"),
    (re.compile(r"根治"), "绝对化承诺"),
    (re.compile(r"包治"), "绝对化承诺"),
    (re.compile(r"药到病除"), "绝对化承诺"),
    (re.compile(r"立竿见影"), "绝对化承诺"),
]

# ── 替代就医（硬拦截级别） ────────────────────────────────────────────────────
PROHIBITED_REPLACE_MEDICAL: list[tuple[re.Pattern, str]] = [
    (re.compile(r"不用去医院"), "替代就医"),
    (re.compile(r"代替就医"), "替代就医"),
    (re.compile(r"替代就医"), "替代就医"),
    (re.compile(r"在家就能治"), "替代就医"),
]

# =============================================================================
# 上架专用规则
# =============================================================================

# ── 禁用词（出现则为 fatal/error 级别） ──────────────────────────────────────
LISTING_PROHIBITED_WORDS: list[str] = [
    "处方",
    "抗生素",
    "激素",
    "麻醉",
    "毒品",
]

# ── 虚假宣传（error 级别） ────────────────────────────────────────────────────
LISTING_FALSE_CLAIMS: list[str] = [
    "治愈",
    "根治",
    "100%有效",
    "无副作用",
    "包治",
]

# ── 夸大宣传（warning 级别） ──────────────────────────────────────────────────
LISTING_EXAGGERATION: list[str] = [
    "最好",
    "第一",
    "顶级",
    "国际领先",
]

# ── 标题清洗词（自动移除） ────────────────────────────────────────────────────
TITLE_REMOVE_WORDS: list[str] = [
    "厂家直销",
    "批发",
    "爆款",
    "热卖",
    "新款",
    "包邮",
    "特价",
    "促销",
    "一件代发",
]

# ── 软替换映射（上架场景，保留内容但规范用词） ───────────────────────────────
_SOFT_REPLACE_MAP: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"治愈"), "辅助改善", "治愈→辅助改善"),
    (re.compile(r"(?<!理)治疗(?!仪|设备|方案名|器)"), "辅助健康管理", "治疗→辅助健康管理"),
    (re.compile(r"疗效"), "使用效果", "疗效→使用效果"),
    (re.compile(r"根治"), "改善", "根治→改善"),
    (re.compile(r"包治"), "适用于", "包治→适用于"),
    (re.compile(r"无副作用"), "按说明书使用", "无副作用→按说明书使用"),
]

# =============================================================================
# 工具函数
# =============================================================================

class ViolationItem(TypedDict):
    """单个违规项描述"""
    field: str
    matched_text: str
    rule_category: str
    severity: str          # "fatal" | "error" | "warning"
    suggestion: str
    auto_fixed: bool
    fixed_text: str        # 修复后文本（仅当 auto_fixed=True）


def apply_title_clean(title: str) -> tuple[str, list[str]]:
    """
    清洗标题：移除 TITLE_REMOVE_WORDS 中的营销词汇。

    Returns:
        (cleaned_title, removed_words)
    """
    cleaned = title
    removed: list[str] = []
    for word in TITLE_REMOVE_WORDS:
        if word in cleaned:
            cleaned = cleaned.replace(word, "").strip()
            removed.append(word)
    # 去除连续空格
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, removed


def _soft_replace(text: str) -> tuple[str, list[str]]:
    """对文本执行软替换，返回 (替换后文本, 替换记录列表)"""
    result = text
    applied: list[str] = []
    for pattern, replacement, label in _SOFT_REPLACE_MAP:
        new_text = pattern.sub(replacement, result)
        if new_text != result:
            applied.append(label)
            result = new_text
    return result, applied


def check_text_violations(
    text: str,
    field_name: str,
    auto_fix: bool = True,
) -> tuple[str, list[ViolationItem]]:
    """
    对给定文本执行合规检查，可选自动修复。

    检查顺序：
      1. LISTING_PROHIBITED_WORDS  (fatal)
      2. LISTING_FALSE_CLAIMS      (error) + 软替换
      3. LISTING_EXAGGERATION      (warning)
      4. PROHIBITED_ABSOLUTE_CLAIMS (error) + 软替换
      5. PROHIBITED_REPLACE_MEDICAL (fatal)

    Args:
        text:       待检查文本
        field_name: 字段名（用于日志/issue 报告）
        auto_fix:   是否自动修复（替换违规词）

    Returns:
        (possibly_fixed_text, violations)
    """
    if not text:
        return text, []

    violations: list[ViolationItem] = []
    current_text = text

    # ── 1. 禁用词（fatal，不自动替换，仅标记） ────────────────────────────
    for word in LISTING_PROHIBITED_WORDS:
        if word in current_text:
            violations.append(ViolationItem(
                field=field_name,
                matched_text=word,
                rule_category="禁用词",
                severity="fatal",
                suggestion=f"移除或替换词汇「{word}」，医疗器械商品禁止使用此类词汇",
                auto_fixed=False,
                fixed_text="",
            ))

    # ── 2. 虚假宣传（error，尝试软替换） ─────────────────────────────────
    for word in LISTING_FALSE_CLAIMS:
        if word in current_text:
            fixed_text, replacements = _soft_replace(current_text)
            did_fix = bool(replacements) and auto_fix
            violations.append(ViolationItem(
                field=field_name,
                matched_text=word,
                rule_category="虚假宣传",
                severity="error",
                suggestion=f"「{word}」属虚假宣传，建议改为「辅助改善」「帮助监测」等合规表述",
                auto_fixed=did_fix,
                fixed_text=fixed_text if did_fix else "",
            ))
            if did_fix:
                current_text = fixed_text

    # ── 3. 夸大宣传（warning，不自动替换） ───────────────────────────────
    for word in LISTING_EXAGGERATION:
        if word in current_text:
            violations.append(ViolationItem(
                field=field_name,
                matched_text=word,
                rule_category="夸大宣传",
                severity="warning",
                suggestion=f"「{word}」属夸大宣传，建议删除或改为具体数据说明",
                auto_fixed=False,
                fixed_text="",
            ))

    # ── 4. 绝对化承诺（error，软替换） ───────────────────────────────────
    for pattern, rule_name in PROHIBITED_ABSOLUTE_CLAIMS:
        m = pattern.search(current_text)
        if m:
            fixed_text, replacements = _soft_replace(current_text)
            did_fix = bool(replacements) and auto_fix
            violations.append(ViolationItem(
                field=field_name,
                matched_text=m.group(0),
                rule_category=rule_name,
                severity="error",
                suggestion=f"「{m.group(0)}」属绝对化承诺，违反平台规范，建议删除",
                auto_fixed=did_fix,
                fixed_text=fixed_text if did_fix else "",
            ))
            if did_fix:
                current_text = fixed_text

    # ── 5. 替代就医（fatal，不自动替换） ─────────────────────────────────
    for pattern, rule_name in PROHIBITED_REPLACE_MEDICAL:
        m = pattern.search(current_text)
        if m:
            violations.append(ViolationItem(
                field=field_name,
                matched_text=m.group(0),
                rule_category=rule_name,
                severity="fatal",
                suggestion=f"「{m.group(0)}」属替代就医表述，违反医疗器械监管规定，必须删除",
                auto_fixed=False,
                fixed_text="",
            ))

    return current_text, violations


__all__ = [
    "PROHIBITED_DIAGNOSTIC_PATTERNS",
    "PROHIBITED_PRESCRIPTION_PATTERNS",
    "PROHIBITED_ABSOLUTE_CLAIMS",
    "PROHIBITED_REPLACE_MEDICAL",
    "LISTING_PROHIBITED_WORDS",
    "LISTING_FALSE_CLAIMS",
    "LISTING_EXAGGERATION",
    "TITLE_REMOVE_WORDS",
    "ViolationItem",
    "apply_title_clean",
    "check_text_violations",
]
