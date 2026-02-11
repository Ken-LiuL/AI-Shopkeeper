"""Notifier Skill — 企业微信预警推送 + 日报。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field


# ── Pydantic Models ──────────────────────────────────────────────────────────

class AlertPayload(BaseModel):
    severity: str  # critical/warning/info
    title: str
    product_name: str
    description: str
    root_cause: str = ""
    action: str = ""

class DailyReportPayload(BaseModel):
    date: str
    metrics: Dict[str, Any]
    top_recommendations: List[Dict[str, Any]] = Field(default_factory=list)


# ── Emoji mapping ────────────────────────────────────────────────────────────

_SEVERITY_EMOJI = {
    "critical": "🚨",
    "warning": "⚠️",
    "info": "ℹ️",
}


class NotifierSkill:
    """企业微信通知技能。"""

    def __init__(self, webhook_url: str = "", timeout: float = 10.0):
        """
        Args:
            webhook_url: 企业微信机器人 Webhook URL。
            timeout: HTTP 请求超时秒数。
        """
        self._webhook_url = webhook_url
        self._timeout = timeout

    # ── 预警推送 ─────────────────────────────────────────────────────────

    async def send_alert(self, payload: AlertPayload) -> bool:
        """发送预警通知到企业微信。"""
        emoji = _SEVERITY_EMOJI.get(payload.severity, "")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        message = (
            f"{emoji} 【{payload.severity.upper()}预警】{payload.title}\n\n"
            f"📦 商品: {payload.product_name}\n"
            f"📊 异常: {payload.description}\n"
        )
        if payload.root_cause:
            message += f"🔍 原因: {payload.root_cause}\n"
        if payload.action:
            message += f"💡 建议: {payload.action}\n"
        message += f"\n⏰ 时间: {now}"

        return await self._send_wechat_work(message)

    # ── 每日报告 ─────────────────────────────────────────────────────────

    async def send_daily_report(self, payload: DailyReportPayload) -> bool:
        """发送每日选品/运营报告。"""
        m = payload.metrics
        lines = [
            f"📊 【每日运营报告】{payload.date}",
            "",
            "📈 核心指标:",
            f"  • 总销售额: ¥{m.get('total_revenue', 0):,.0f}",
            f"  • 总订单数: {m.get('total_orders', 0)}",
            f"  • 平均毛利率: {m.get('avg_margin', 0):.1%}",
            f"  • 预警数量: {m.get('alert_count', 0)}",
        ]

        if payload.top_recommendations:
            lines.append("")
            lines.append("🏆 今日推荐选品:")
            for i, rec in enumerate(payload.top_recommendations[:5], 1):
                name = rec.get("keyword", rec.get("name", ""))
                score = rec.get("score", rec.get("final_score", 0))
                lines.append(f"  {i}. {name} (评分: {score:.1f})")

        lines.append(f"\n⏰ 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        message = "\n".join(lines)
        return await self._send_wechat_work(message)

    # ── 通用消息发送 ─────────────────────────────────────────────────────

    async def send_text(self, text: str) -> bool:
        """发送纯文本消息。"""
        return await self._send_wechat_work(text)

    # ── 企业微信发送 ─────────────────────────────────────────────────────

    async def _send_wechat_work(self, content: str) -> bool:
        """通过企业微信机器人 Webhook 发送 markdown/text 消息。"""
        if not self._webhook_url:
            # No webhook configured — log only
            return False

        body = {
            "msgtype": "text",
            "text": {"content": content},
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._webhook_url, json=body)
                resp.raise_for_status()
                data = resp.json()
                return data.get("errcode", -1) == 0
        except Exception:
            return False
