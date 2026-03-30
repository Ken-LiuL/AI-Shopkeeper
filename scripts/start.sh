#!/bin/bash
# start.sh — 数据 seed + 启动 uvicorn 应用服务器
set -e

# ── 等待 PostgreSQL 就绪 ──────────────────────────────────────────
echo "[start.sh] 等待 PostgreSQL 就绪..."
for i in $(seq 1 30); do
    if python3 -c "
import asyncio, os, sys
sys.path.insert(0, '/app')
from src.db import postgres as pg
async def check():
    await pg.init(os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@postgres:5432/ai_store'))
    pool = pg.get_pool()
    await pool.fetchval('SELECT 1')
    await pg.close()
asyncio.run(check())
" 2>/dev/null; then
        echo "[start.sh] PostgreSQL 已就绪"
        break
    fi
    echo "[start.sh] 等待 PostgreSQL... ($i/30)"
    sleep 2
done

# ── 导入 sample 数据（幂等，已导入则跳过）──────────────────────────
if [ -d /app/sample ] && [ "$(ls /app/sample/*.xlsx /app/sample/*.xls 2>/dev/null)" ]; then
    echo "[start.sh] 检查并导入 sample 数据..."
    cd /app && python3 scripts/seed_sample_data.py || echo "[start.sh] ⚠️ sample 数据导入失败（非致命）"
fi

# ── 启动应用 ──────────────────────────────────────────────────────
echo "[start.sh] 启动 uvicorn..."
exec python -m uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
