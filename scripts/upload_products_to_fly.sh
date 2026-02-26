#!/bin/bash
# Upload local all_products.json to Fly app and import to Postgres
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_FILE="$SCRIPT_DIR/../data/all_products.json"
APP="ai-shopkeeper-kk"

if [ ! -f "$DATA_FILE" ]; then
  echo "❌ $DATA_FILE not found. Run sync_all_products.py first (local JSON mode)."
  exit 1
fi

COUNT=$(python3 -c "import json; print(len(json.load(open('$DATA_FILE'))))")
echo "📦 Uploading $COUNT products to Fly..."

# Base64 encode and pipe through ssh
cat "$DATA_FILE" | base64 | fly ssh console -a "$APP" -C "python3 -c \"
import sys, base64, json, psycopg2

data = base64.b64decode(sys.stdin.read())
products = json.loads(data)
print(f'Received {len(products)} products')

c = psycopg2.connect('host=ai-shopkeeper-kk-db.flycast dbname=ai_shopkeeper_kk user=ai_shopkeeper_kk password=8c6qWp4phD6K2dt sslmode=disable')
cur = c.cursor()

for p in products:
    spu_id = str(p.get('spuId', ''))
    name = p.get('spuName') or p.get('goodsName') or ''
    brand = ''
    if isinstance(p.get('brand'), dict):
        brand = p['brand'].get('brandName', '')
    pic_urls = p.get('picUrlList', [])
    image_url = pic_urls[0] if pic_urls else ''
    skus = p.get('skus', [])
    weight_type = p.get('weightTypeDesc', '')

    retail_price = None
    spec = ''
    if skus:
        spec = skus[0].get('specName', '')
        suggest = skus[0].get('suggestPrice', {})
        if isinstance(suggest, dict):
            tp = suggest.get('tenantSuggestPrice', {})
            if isinstance(tp, dict) and tp.get('unifiedSuggestPrice'):
                try: retail_price = float(tp['unifiedSuggestPrice'])
                except: pass

    status = '在售' if p.get('onlineStatus') == 1 else '停售'

    cur.execute('''
        INSERT INTO qnh_products (spu_id, name, brand, spec, retail_price, image_url, status, pic_urls, skus, weight_type, synced_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (spu_id) DO UPDATE SET
            name = EXCLUDED.name, brand = EXCLUDED.brand, spec = EXCLUDED.spec,
            retail_price = EXCLUDED.retail_price, image_url = EXCLUDED.image_url,
            status = EXCLUDED.status, pic_urls = EXCLUDED.pic_urls,
            skus = EXCLUDED.skus, weight_type = EXCLUDED.weight_type, synced_at = NOW()
    ''', (spu_id, name, brand, spec, retail_price, image_url, status,
          json.dumps(pic_urls, ensure_ascii=False), json.dumps(skus, ensure_ascii=False), weight_type))

c.commit()
cur.execute('SELECT count(*) FROM qnh_products')
print(f'✅ Upserted {len(products)} products. Total in DB: {cur.fetchone()[0]}')
c.close()
\""

echo "✅ Done!"
