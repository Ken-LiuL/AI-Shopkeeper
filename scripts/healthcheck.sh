#!/bin/bash
# healthcheck.sh — AI-Shopkeeper service health monitor
#
# Usage:
#   ./scripts/healthcheck.sh
#   HEALTH_URL=http://prod:8000/ready ALERT_WEBHOOK_URL=https://... ./scripts/healthcheck.sh
#
# Can be invoked by cron or Docker HEALTHCHECK.
# Exits 0 if healthy, 1 if degraded/down (and sends webhook alert if configured).

set -euo pipefail

HEALTH_URL="${HEALTH_URL:-http://localhost:8000/ready}"
WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"  # Feishu / DingTalk webhook URL

# Fetch readiness endpoint (10s timeout)
response=$(curl -s -m 10 "$HEALTH_URL" 2>/dev/null) || {
    echo "[ALERT] Failed to reach health endpoint: $HEALTH_URL"
    if [ -n "$WEBHOOK_URL" ]; then
        curl -s -X POST "$WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"msg_type\":\"text\",\"content\":{\"text\":\"🚨 AI店长告警: 无法连接健康检查端点 $HEALTH_URL\"}}" \
            >/dev/null 2>&1 || true
    fi
    exit 1
}

# Parse status field
status=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")

if [ "$status" != "ok" ]; then
    echo "[ALERT] Service unhealthy: $status"
    echo "$response"
    if [ -n "$WEBHOOK_URL" ]; then
        # Send alert to Feishu / DingTalk webhook
        curl -s -X POST "$WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"msg_type\":\"text\",\"content\":{\"text\":\"🚨 AI店长告警: 服务状态 $status\n$response\"}}" \
            >/dev/null 2>&1 || true
    fi
    exit 1
fi

echo "[OK] Service healthy"
exit 0
