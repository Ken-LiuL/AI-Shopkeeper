"""
医疗器械合规过滤模块 (P1-1 Compliance Layer)

两级过滤：
  1. 硬拦截 (hard block)  — 命中后整条回复替换为转人工话术，设置 needs_human=True
  2. 软替换 (soft replace) — 替换措辞，保留回复

日志格式：
  硬拦截: [CS-COMPLIANCE-BLOCK]  session=... rule=... original_prefix=...
  软替换: [CS-COMPLIANCE-REPLACE] session=... replacements=...
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── 转人工话术 ────────────────────────────────────────────────────────────────

HUMAN_HANDOFF_COMPLIANCE_REPLY = (
    "您好，您提到的问题涉及专业医疗建议，为保障您的健康安全，"
    "我们为您转接专业人工客服，请稍候🙏"
)

# ── 硬拦截规则 ────────────────────────────────────────────────────────────────
# 格式：(compiled_pattern, rule_name)
# 命中任意一条 → 整条回复替换为 HUMAN_HANDOFF_COMPLIANCE_REPLY，needs_human=True

_HARD_BLOCK_RULES: list[tuple[re.Pattern, str]] = [
    # ① 诊断性语言
    (re.compile(r"你这是.{0,10}病"), "诊断性语言"),
    (re.compile(r"你得了.{0,15}"), "诊断性语言"),
    (re.compile(r"确诊"), "诊断性语言"),
    (re.compile(r"诊断为"), "诊断性语言"),
    # ② 处方建议
    (re.compile(r"建议你(吃|服用).{0,15}药"), "处方建议"),
    (re.compile(r"一天(吃|服用|用)\s*\d+\s*次"), "处方建议"),
    (re.compile(r"用量\s*\d+\s*(mg|毫克|克|ml|毫升)", re.IGNORECASE), "处方建议"),
    # ③ 绝对化承诺
    (re.compile(r"保证有效"), "绝对化承诺"),
    (re.compile(r"100\s*%\s*(治愈|治好|有效)"), "绝对化承诺"),
    (re.compile(r"彻底(治愈|治好)"), "绝对化承诺"),
    (re.compile(r"根治"), "绝对化承诺"),
    (re.compile(r"包治"), "绝对化承诺"),
    (re.compile(r"药到病除"), "绝对化承诺"),
    (re.compile(r"立竿见影"), "绝对化承诺"),
    # ④ 替代就医
    (re.compile(r"不用去医院"), "替代就医"),
    (re.compile(r"代替就医"), "替代就医"),
    (re.compile(r"替代就医"), "替代就医"),
    (re.compile(r"在家就能治"), "替代就医"),
]

# ── 软替换规则 ────────────────────────────────────────────────────────────────
# 格式：(compiled_pattern, replacement_str, rule_label)
# 全部替换后保留回复，仅记录日志

_SOFT_REPLACE_RULES: list[tuple[re.Pattern, str, str]] = [
    # 注意：顺序敏感。长词/复合词优先，避免先替换子串导致后续规则失效。
    # 原有软替换规则（向后兼容，需在「疗效」之前）
    (re.compile(r"保证疗效"), "有助于改善", "保证疗效→有助于改善"),
    # 「治愈」优先于「治疗」
    (re.compile(r"治愈"), "辅助改善", "治愈→辅助改善"),
    # 「治疗」需在「疗效」之前，避免「治疗效果」被「疗效」先行拆开
    # 不含"理疗"/"调理"等复合词，避免过度替换产品官方名称
    (re.compile(r"(?<!理)治疗(?!仪|设备|方案名|器)"), "辅助健康管理", "治疗→辅助健康管理"),
    # 「疗效」在「治疗」之后，防止「治疗效果」被误拆
    (re.compile(r"疗效"), "使用效果", "疗效→使用效果"),
    (re.compile(r"患者"), "使用者", "患者→使用者"),
    (re.compile(r"病人"), "有需要的朋友", "病人→有需要的朋友"),
]

# ── 流式回写时需要保留的最大前瞻字符数（供 nodes.py 使用）──────────────────────
# 取所有规则中最长字面量长度 - 1（用于流式场景的安全前瞻窗口）
_HARD_LITERAL_SAMPLES = [
    "你这是病", "你得了", "确诊", "诊断为",
    "建议你吃药", "一天吃1次", "用量1mg",
    "保证有效", "100%治愈", "彻底治愈", "根治", "包治",
    "药到病除", "立竿见影",
    "不用去医院", "代替就医", "替代就医", "在家就能治",
]
_SOFT_LITERAL_SAMPLES = [repl for _, repl, _ in _SOFT_REPLACE_RULES]
COMPLIANCE_STREAM_HOLDBACK_CHARS: int = max(
    (len(s) for s in _HARD_LITERAL_SAMPLES + _SOFT_LITERAL_SAMPLES),
    default=1,
) - 1


# ── 结果数据类 ────────────────────────────────────────────────────────────────

@dataclass
class ComplianceResult:
    """合规过滤结果。"""
    text: str
    needs_human: bool
    was_filtered: bool                        # 是否发生了任何修改
    block_rule: str | None = None            # 硬拦截时命中的规则名


# ── 公共 API ─────────────────────────────────────────────────────────────────

def check(text: str, session_id: str = "") -> ComplianceResult:
    """对 AI 回复文本执行完整合规检查。

    流程：
      1. 硬拦截扫描 → 命中则直接返回转人工话术
      2. 软替换扫描 → 替换措辞，保留回复
      3. 无命中 → 原样返回

    Args:
        text:       待检查的 AI 回复文本
        session_id: 当前会话 ID（用于日志）

    Returns:
        ComplianceResult
    """
    if not text:
        return ComplianceResult(text=text, needs_human=False, was_filtered=False)

    # ── Step 1: 硬拦截 ──────────────────────────────────────────────
    for pattern, rule_name in _HARD_BLOCK_RULES:
        if pattern.search(text):
            logger.warning(
                "[CS-COMPLIANCE-BLOCK] session=%s rule=%s original_prefix=%.50s",
                session_id,
                rule_name,
                text,
            )
            return ComplianceResult(
                text=HUMAN_HANDOFF_COMPLIANCE_REPLY,
                needs_human=True,
                was_filtered=True,
                block_rule=rule_name,
            )

    # ── Step 2: 软替换 ──────────────────────────────────────────────
    filtered = text
    replacements: list[str] = []
    for pattern, replacement, label in _SOFT_REPLACE_RULES:
        new_text = pattern.sub(replacement, filtered)
        if new_text != filtered:
            replacements.append(label)
            filtered = new_text

    if replacements:
        logger.info(
            "[CS-COMPLIANCE-REPLACE] session=%s replacements=%s",
            session_id,
            "; ".join(replacements),
        )
        return ComplianceResult(text=filtered, needs_human=False, was_filtered=True)

    return ComplianceResult(text=filtered, needs_human=False, was_filtered=False)


def soft_filter(text: str) -> str:
    """仅执行软替换（不做硬拦截）。

    供 _postprocess_reply_text 向后兼容使用，以及流式处理中间 chunk 的安全过滤。
    """
    if not text:
        return text
    filtered = text
    for pattern, replacement, _ in _SOFT_REPLACE_RULES:
        filtered = pattern.sub(replacement, filtered)
    return filtered


__all__ = [
    "ComplianceResult",
    "HUMAN_HANDOFF_COMPLIANCE_REPLY",
    "COMPLIANCE_STREAM_HOLDBACK_CHARS",
    "check",
    "soft_filter",
]
