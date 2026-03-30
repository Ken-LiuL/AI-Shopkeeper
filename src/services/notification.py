"""通知推送服务 — 支持 Telegram / Webhook / 飞书 / 微信企业 / 钉钉"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")

# 飞书机器人 webhook
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
# 企业微信机器人 webhook
WECHAT_WEBHOOK_URL = os.getenv("WECHAT_WEBHOOK_URL", "")
# 钉钉机器人 webhook
DINGTALK_WEBHOOK_URL = os.getenv("DINGTALK_WEBHOOK_URL", "")


async def send_telegram(text: str, chat_id: str = "") -> bool:
    """发送 Telegram 消息"""
    token = TELEGRAM_BOT_TOKEN
    cid = chat_id or TELEGRAM_CHAT_ID
    if not token or not cid:
        logger.warning("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"chat_id": cid, "text": text, "parse_mode": "HTML"})
            if resp.status_code == 200:
                logger.info(f"Telegram sent to {cid}")
                return True
            logger.warning(f"Telegram failed: {resp.status_code} {resp.text[:100]}")
            return False
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


async def send_webhook(payload: dict) -> bool:
    """发送通用 Webhook 通知"""
    if not WEBHOOK_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(WEBHOOK_URL, json=payload)
            return resp.status_code < 400
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return False


async def send_feishu(title: str, body: str, severity: str = "medium") -> bool:
    """发送飞书机器人消息（富文本 post 格式）

    环境变量: FEISHU_WEBHOOK_URL
    飞书文档: https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
    """
    webhook_url = FEISHU_WEBHOOK_URL
    if not webhook_url:
        logger.debug("Feishu webhook not configured (FEISHU_WEBHOOK_URL)")
        return False

    emoji = {"critical": "🚨", "high": "⚠️", "medium": "📋", "low": "💡"}.get(severity, "📋")
    color_map = {"critical": "red", "high": "orange", "medium": "yellow", "low": "green"}
    color = color_map.get(severity, "yellow")

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"{emoji} {title}"},
                "template": color,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": body},
                }
            ],
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("StatusCode") == 0:
                logger.info("Feishu webhook sent successfully")
                return True
            logger.warning(f"Feishu webhook failed: {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Feishu webhook error: {e}")
        return False


async def send_wechat(title: str, body: str, severity: str = "medium") -> bool:
    """发送企业微信机器人消息（markdown 格式）

    环境变量: WECHAT_WEBHOOK_URL
    文档: https://developer.work.weixin.qq.com/document/path/91770
    """
    webhook_url = WECHAT_WEBHOOK_URL
    if not webhook_url:
        logger.debug("WeChat webhook not configured (WECHAT_WEBHOOK_URL)")
        return False

    emoji = {"critical": "🚨", "high": "⚠️", "medium": "📋", "low": "💡"}.get(severity, "📋")
    color_map = {"critical": "warning", "high": "warning", "medium": "info", "low": "comment"}
    font_color = color_map.get(severity, "info")

    markdown_content = f"## {emoji} {title}\n\n{body}\n\n> 严重程度: <font color=\"{font_color}\">{severity}</font>"

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": markdown_content},
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("errcode") == 0:
                logger.info("WeChat webhook sent successfully")
                return True
            logger.warning(f"WeChat webhook failed: {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"WeChat webhook error: {e}")
        return False


async def send_dingtalk(title: str, body: str, severity: str = "medium") -> bool:
    """发送钉钉机器人消息（markdown 格式）

    环境变量: DINGTALK_WEBHOOK_URL
    文档: https://open.dingtalk.com/document/robots/custom-robot-access
    """
    webhook_url = DINGTALK_WEBHOOK_URL
    if not webhook_url:
        logger.debug("DingTalk webhook not configured (DINGTALK_WEBHOOK_URL)")
        return False

    emoji = {"critical": "🚨", "high": "⚠️", "medium": "📋", "low": "💡"}.get(severity, "📋")

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"{emoji} {title}",
            "text": f"## {emoji} {title}\n\n{body}\n\n> 严重程度: **{severity}**",
        },
        "at": {"isAtAll": severity == "critical"},
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("errcode") == 0:
                logger.info("DingTalk webhook sent successfully")
                return True
            logger.warning(f"DingTalk webhook failed: {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"DingTalk webhook error: {e}")
        return False


async def send_alert(title: str, body: str, severity: str = "medium") -> dict[str, Any]:
    """发送告警通知（Telegram + Webhook + 飞书 + 微信企业 + 钉钉）"""
    emoji = {"critical": "🚨", "high": "⚠️", "medium": "📋", "low": "💡"}.get(severity, "📋")
    telegram_text = f"{emoji} <b>{title}</b>\n\n{body}"

    configured_channels: list[str] = []
    sent_channels: list[str] = []

    # Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        configured_channels.append("telegram")
        if await send_telegram(telegram_text):
            sent_channels.append("telegram")

    # 通用 Webhook
    if WEBHOOK_URL:
        configured_channels.append("webhook")
        if await send_webhook({"title": title, "body": body, "severity": severity}):
            sent_channels.append("webhook")

    # 飞书
    if FEISHU_WEBHOOK_URL:
        configured_channels.append("feishu")
        if await send_feishu(title, body, severity):
            sent_channels.append("feishu")

    # 企业微信
    if WECHAT_WEBHOOK_URL:
        configured_channels.append("wechat")
        if await send_wechat(title, body, severity):
            sent_channels.append("wechat")

    # 钉钉
    if DINGTALK_WEBHOOK_URL:
        configured_channels.append("dingtalk")
        if await send_dingtalk(title, body, severity):
            sent_channels.append("dingtalk")

    if not configured_channels:
        return {
            "sent": False,
            "reason": "notification_not_configured",
            "channels_attempted": [],
            "channels_sent": [],
        }

    sent = bool(sent_channels)
    return {
        "sent": sent,
        "reason": "sent" if sent else "notification_delivery_failed",
        "channels_attempted": configured_channels,
        "channels_sent": sent_channels,
    }


async def send_report(title: str, body: str) -> dict[str, Any]:
    """发送日报通知（飞书 + 微信企业 + 钉钉 + Telegram + Webhook）

    与 send_alert 不同，日报为信息类推送，使用 info/green 样式，无严重程度语义。
    """
    telegram_text = f"📊 <b>{title}</b>\n\n{body}"

    configured_channels: list[str] = []
    sent_channels: list[str] = []

    # Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        configured_channels.append("telegram")
        if await send_telegram(telegram_text):
            sent_channels.append("telegram")

    # 通用 Webhook
    if WEBHOOK_URL:
        configured_channels.append("webhook")
        if await send_webhook({"title": title, "body": body, "type": "daily_report"}):
            sent_channels.append("webhook")

    # 飞书（green 主题）
    if FEISHU_WEBHOOK_URL:
        configured_channels.append("feishu")
        if await send_feishu(title, body, severity="low"):
            sent_channels.append("feishu")

    # 企业微信
    if WECHAT_WEBHOOK_URL:
        configured_channels.append("wechat")
        if await send_wechat(title, body, severity="low"):
            sent_channels.append("wechat")

    # 钉钉
    if DINGTALK_WEBHOOK_URL:
        configured_channels.append("dingtalk")
        if await send_dingtalk(title, body, severity="low"):
            sent_channels.append("dingtalk")

    if not configured_channels:
        logger.info("No notification channels configured for daily report")
        return {
            "sent": False,
            "reason": "notification_not_configured",
            "channels_attempted": [],
            "channels_sent": [],
        }

    sent = bool(sent_channels)
    return {
        "sent": sent,
        "reason": "sent" if sent else "notification_delivery_failed",
        "channels_attempted": configured_channels,
        "channels_sent": sent_channels,
    }


async def check_and_push_alerts(pool) -> dict:
    """检查待处理的告警并推送"""
    from datetime import datetime, timedelta

    results = {"checked": 0, "pushed": 0, "errors": 0}

    try:
        # 获取最近未推送的 critical/high 告警
        rows = await pool.fetch("""
            SELECT a.alert_id, a.alert_type, a.severity, a.root_cause, a.recommended_action,
                   p.name AS product_name, p.stock
            FROM alerts a
            LEFT JOIN products p ON a.product_id = p.product_id
            WHERE a.status = 'pending'
              AND a.severity IN ('critical', 'high')
              AND a.created_at >= $1
            ORDER BY a.severity DESC, a.created_at DESC
            LIMIT 20
        """, datetime.utcnow() - timedelta(hours=24))

        results["checked"] = len(rows)
        if not rows:
            return results

        # 汇总告警
        critical = [r for r in rows if r["severity"] == "critical"]
        high = [r for r in rows if r["severity"] == "high"]

        lines = []
        if critical:
            lines.append(f"🚨 {len(critical)} 个紧急告警:")
            for r in critical[:5]:
                name = (r["product_name"] or "未知商品")[:20]
                lines.append(f"  • {name} — {r['root_cause']}")
        if high:
            lines.append(f"⚠️ {len(high)} 个高级告警:")
            for r in high[:5]:
                name = (r["product_name"] or "未知商品")[:20]
                lines.append(f"  • {name} — {r['root_cause']}")

        body = "\n".join(lines)
        send_result = await send_alert("店铺告警汇总", body, "critical" if critical else "high")
        results["notification"] = send_result

        if send_result.get("sent"):
            results["pushed"] = len(rows)
            await pool.execute(
                """
                UPDATE alerts
                SET notification_status = 'sent',
                    notification_reason = $1,
                    notification_updated_at = NOW()
                WHERE alert_id = ANY($2::text[])
                """,
                ",".join(send_result.get("channels_sent", [])) or "sent",
                [r["alert_id"] for r in rows],
            )
        elif send_result.get("reason") == "notification_not_configured":
            await pool.execute(
                """
                UPDATE alerts
                SET notification_status = 'not_configured',
                    notification_reason = $1,
                    notification_updated_at = NOW()
                WHERE alert_id = ANY($2::text[])
                """,
                "notification_not_configured",
                [r["alert_id"] for r in rows],
            )
            results["not_configured"] = len(rows)
        else:
            await pool.execute(
                """
                UPDATE alerts
                SET notification_status = 'failed',
                    notification_reason = $1,
                    notification_updated_at = NOW()
                WHERE alert_id = ANY($2::text[])
                """,
                str(send_result.get("reason", "notification_delivery_failed")),
                [r["alert_id"] for r in rows],
            )
            results["errors"] = 1

    except Exception as e:
        logger.error(f"Alert push check failed: {e}")
        results["errors"] = 1

    return results
