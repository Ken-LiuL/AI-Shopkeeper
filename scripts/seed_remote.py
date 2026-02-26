"""Seed products via fly ssh - write script to file, then execute."""

import subprocess
import sys
import tempfile

SEED_CODE = r"""
import asyncio, os, json, asyncpg
async def main():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    await pool.execute("CREATE TABLE IF NOT EXISTS qnh_products (spu_id TEXT NOT NULL, sku_id TEXT DEFAULT '', tenant_id TEXT DEFAULT '', name TEXT DEFAULT '', barcode TEXT DEFAULT '', category TEXT DEFAULT '', brand TEXT DEFAULT '', spec TEXT DEFAULT '', unit TEXT DEFAULT '', cost_price NUMERIC, retail_price NUMERIC, channel_price JSONB, status TEXT DEFAULT '', channel_status JSONB, image_url TEXT DEFAULT '', extra JSONB, synced_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (spu_id, sku_id))")
    prods = [
        ("1001","鱼跃制氧机 8F-5AW","制氧雾化","鱼跃","5L/min",2680),
        ("1002","欧姆龙雾化器 NE-C900","制氧雾化","欧姆龙","压缩式",599),
        ("1003","鱼跃轮椅 H062","轮椅拐杖","鱼跃","铝合金折叠",899),
        ("1004","护膝保暖关节套","康复护具","海尔斯","均码",79),
        ("1005","电子血压计 HEM-7136","监测专区","欧姆龙","上臂式",299),
        ("1006","体温计 红外额温枪","监测专区","鱼跃","YT-1",129),
        ("1007","血糖仪套装 GA-3型","监测专区","三诺","含50片试纸",159),
        ("1008","N95口罩 独立包装","春节应急","3M","30只/盒",89),
        ("1009","医用退热贴 儿童型","春节应急","兵兵","6片/盒",25),
        ("1010","碘伏消毒液 500ml","春节应急","海氏海诺","500ml",18),
        ("1011","创可贴 防水型","春节应急","云南白药","100片/盒",32),
        ("1012","腰椎牵引器","康复护具","佳禾","充气式",168),
        ("1013","助行器 四脚拐杖","轮椅拐杖","鱼跃","铝合金可调",128),
        ("1014","雾化面罩 儿童款","制氧雾化","欧姆龙","通用接口",35),
        ("1015","指夹式血氧仪","监测专区","鱼跃","YX306",169),
        ("1016","颈椎按摩仪","康复护具","SKG","K5-2",459),
        ("1017","医用棉签 灭菌型","春节应急","稳健","200支/袋",12),
        ("1018","止血绷带 弹性自粘","春节应急","3M","7.5cm*4.5m",28),
        ("1019","隐形眼镜护理液","春节应急","海昌","500ml",45),
        ("1020","电动轮椅 D130HL","轮椅拐杖","互邦","锂电池可折叠",4580),
    ]
    for p in prods:
        await pool.execute("INSERT INTO qnh_products (spu_id, sku_id, tenant_id, name, category, brand, spec, retail_price, status, synced_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now()) ON CONFLICT (spu_id, sku_id) DO UPDATE SET name=EXCLUDED.name, category=EXCLUDED.category, brand=EXCLUDED.brand, spec=EXCLUDED.spec, retail_price=EXCLUDED.retail_price, status=EXCLUDED.status, synced_at=now()", p[0], "", "1011766", p[1], p[2], p[3], p[4], p[5], "在售")
    t = await pool.fetchval("SELECT COUNT(*) FROM qnh_products")
    print(f"OK seeded {len(prods)} products. Total: {t}")
    await pool.close()
asyncio.run(main())
"""

# Write to temp file, upload via fly sftp, execute
print("Writing seed script...")
with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
    f.write(SEED_CODE)
    tmp = f.name
print(f"Temp: {tmp}")

# Upload
print("Uploading...")
r = subprocess.run(
    ["fly", "sftp", "shell", "--app", "ai-shopkeeper-kk"],
    input=f"put {tmp} /tmp/seed.py\nquit\n",
    capture_output=True,
    text=True,
    timeout=30,
)
print("Upload:", r.stdout[-200:] if r.stdout else "", r.stderr[-200:] if r.stderr else "")

# Execute
print("Executing...")
r = subprocess.run(
    ["fly", "ssh", "console", "--app", "ai-shopkeeper-kk", "-C", "python3 /tmp/seed.py"],
    capture_output=True,
    text=True,
    timeout=60,
)
print("STDOUT:", r.stdout)
if r.stderr:
    print("STDERR:", r.stderr[:300])
sys.exit(r.returncode)
