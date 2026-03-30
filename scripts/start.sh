#!/bin/bash
# start.sh — 启动 uvicorn 应用服务器
set -e

echo "[start.sh] 启动 uvicorn..."
exec python -m uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
