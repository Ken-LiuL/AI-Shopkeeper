#!/bin/bash
# start.sh — 幂等启动 Xvfb 虚拟显示器，然后运行 uvicorn

set -e

DISPLAY_NUM="${DISPLAY:-:99}"
LOCK_FILE="/tmp/.X${DISPLAY_NUM#:}-lock"

if xdpyinfo -display "$DISPLAY_NUM" >/dev/null 2>&1; then
    echo "[start.sh] Xvfb 已可用，复用现有显示 $DISPLAY_NUM"
else
    if [ -f "$LOCK_FILE" ] && ! pgrep -f "Xvfb $DISPLAY_NUM" >/dev/null 2>&1; then
        echo "[start.sh] 检测到残留锁文件，清理 $LOCK_FILE"
        rm -f "$LOCK_FILE"
    fi

    echo "[start.sh] 启动 Xvfb 虚拟显示器 $DISPLAY_NUM..."
    Xvfb "$DISPLAY_NUM" -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
    XVFB_PID=$!

    sleep 2
    if ! xdpyinfo -display "$DISPLAY_NUM" >/dev/null 2>&1; then
        echo "[start.sh] WARNING: Xvfb 未就绪，继续尝试..."
    fi
    echo "[start.sh] Xvfb 已启动 (PID=$XVFB_PID)"
fi

export DISPLAY="$DISPLAY_NUM"

echo "[start.sh] 启动 uvicorn..."
exec python -m uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
