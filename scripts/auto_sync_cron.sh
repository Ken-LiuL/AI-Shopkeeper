#!/bin/bash
# 每日自动同步美团数据 + ETL + 告警推送
# crontab -e:
#   30 1 * * * cd ~/Dropbox/workspace/ai-store-manager && bash scripts/auto_sync_cron.sh >> logs/cron.log 2>&1
#   0 8 * * * cd ~/Dropbox/workspace/ai-store-manager && bash scripts/auto_sync_cron.sh alerts >> logs/cron.log 2>&1

set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate
mkdir -p logs

MODE="${1:-full}"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] Starting auto_sync_cron mode=$MODE"

BASE="https://ai-shopkeeper-kk.fly.dev"

if [ "$MODE" = "alerts" ]; then
    echo "[$TIMESTAMP] Pushing alerts..."
    curl -s -X POST "$BASE/api/alerts/push" | python3 -c "import sys,json;print(json.dumps(json.load(sys.stdin),indent=2))"
    exit 0
fi

# 1. 美团数据同步（需要本地 Chrome）
echo "[$TIMESTAMP] Step 1: Meituan product sync..."
python3 -c "
import asyncio
from src.sync.meituan_products import MeituanProductSyncer
async def main():
    s = MeituanProductSyncer()
    await s.sync()
asyncio.run(main())
" 2>&1 | tail -5

# 2. 美团订单同步
echo "[$TIMESTAMP] Step 2: Meituan order sync..."
python3 -c "
import asyncio
from src.sync.meituan_orders import MeituanOrderSyncer
async def main():
    s = MeituanOrderSyncer()
    await s.sync()
asyncio.run(main())
" 2>&1 | tail -5

# 3. ETL
echo "[$TIMESTAMP] Step 3: ETL pipeline..."
python3 scripts/etl_qnh_to_business.py 2>&1 | tail -5

# 4. 告警推送
echo "[$TIMESTAMP] Step 4: Push alerts..."
curl -s -X POST "$BASE/api/alerts/push" | python3 -c "import sys,json;print(json.dumps(json.load(sys.stdin),indent=2))" 2>&1

echo "[$TIMESTAMP] Done!"
