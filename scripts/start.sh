#!/bin/bash
# start.sh — migration + 数据 seed + ETL + uvicorn
set -e

# ── 等待 PostgreSQL 就绪 ──────────────────────────────────────────
echo "[start.sh] 等待 PostgreSQL 就绪..."
pg_ready=0
for i in $(seq 1 30); do
    if python3 -c "
import asyncio, os, sys
sys.path.insert(0, '/app')
from src.db import postgres as pg
async def check():
    os.environ.setdefault('DATABASE_URL', 'postgresql://postgres:postgres@postgres:5432/ai_store')
    await pg.init_pool()
    pool = pg.get_pool()
    await pool.fetchval('SELECT 1')
    await pg.close_pool()
asyncio.run(check())
" 2>/dev/null; then
        echo "[start.sh] PostgreSQL 已就绪"
        pg_ready=1
        break
    fi
    echo "[start.sh] 等待 PostgreSQL... ($i/30)"
    sleep 2
done

if [ "$pg_ready" -ne 1 ]; then
    echo "[start.sh] PostgreSQL 超时未就绪，退出"
    exit 1
fi

# ── 运行数据库 migration ──────────────────────────────────────────
echo "[start.sh] 运行 migrations..."
cd /app && python3 -c "
import asyncio, os, sys, glob
sys.path.insert(0, '/app')
from src.db import postgres as pg
async def run():
    os.environ.setdefault('DATABASE_URL', 'postgresql://postgres:postgres@postgres:5432/ai_store')
    await pg.init_pool()
    pool = pg.get_pool()
    await pool.execute('CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT NOW())')
    for f in sorted(glob.glob('migrations/postgres/*.sql')):
        name = os.path.basename(f)
        exists = await pool.fetchval('SELECT 1 FROM _migrations WHERE name = \$1', name)
        if not exists:
            sql = open(f).read()
            try:
                await pool.execute(sql)
                await pool.execute('INSERT INTO _migrations (name) VALUES (\$1)', name)
                print(f'  ✅ {name}')
            except Exception as e:
                print(f'  ⚠️ {name}: {e}')
    await pg.close_pool()
asyncio.run(run())
" || echo "[start.sh] ⚠️ migration 失败（非致命）"

# ── 导入 sample 数据（幂等，已导入则跳过）──────────────────────────
if [ -d /app/sample ] && ls /app/sample/*.xlsx /app/sample/*.xls >/dev/null 2>&1; then
    echo "[start.sh] 检查并导入 sample 数据 + 运行 ETL..."
    cd /app && python3 scripts/seed_sample_data.py || echo "[start.sh] ⚠️ sample 数据导入失败（非致命）"
fi

# ── 启动应用 ──────────────────────────────────────────────────────
echo "[start.sh] 启动 uvicorn..."
exec python -m uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
