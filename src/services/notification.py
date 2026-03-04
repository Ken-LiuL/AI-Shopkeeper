"""通知推送服务 — 支持 Telegram / Webhook"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")


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
    """发送 Webhook 通知"""
    if not WEBHOOK_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(WEBHOOK_URL, json=payload)
            return resp.status_code < 400
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return False


async def send_alert(title: str, body: str, severity: str = "medium") -> bool:
    """发送告警通知（Telegram + Webhook）"""
    emoji = {"critical": "🚨", "high": "⚠️", "medium": "📋", "low": "💡"}.get(severity, "📋")
    text = f"{emoji} <b>{title}</b>\n\n{body}"

    sent = False
    if TELEGRAM_BOT_TOKEN:
        sent = await send_telegram(text)
    if WEBHOOK_URL:
        sent = await send_webhook({"title": title, "body": body, "severity": severity}) or sent
    return sent


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
        sent = await send_alert("店铺告警汇总", body, "critical" if critical else "high")
        if sent:
            results["pushed"] = len(rows)
        else:
            results["errors"] = 1

    except Exception as e:
        logger.error(f"Alert push check failed: {e}")
        results["errors"] = 1

    return results
