#!/bin/bash
# start.sh — 启动 Xvfb 虚拟显示器，然后运行 uvicorn

set -e

echo "[start.sh] 启动 Xvfb 虚拟显示器 :99..."
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!

# 等 Xvfb 就绪
sleep 2
if ! xdpyinfo -display :99 >/dev/null 2>&1; then
    echo "[start.sh] WARNING: Xvfb 未就绪，继续尝试..."
fi
echo "[start.sh] Xvfb 已启动 (PID=$XVFB_PID)"

export DISPLAY=:99

echo "[start.sh] 启动 uvicorn..."
exec uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
