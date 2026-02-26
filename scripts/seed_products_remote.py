"""Seed qnh_products on remote DB via fly proxy. Run locally."""

import asyncio
import subprocess
import sys


async def seed_via_api():
    """Seed products by calling the knowledge API directly through fly ssh."""

    # Instead of DB access, let's create a simple seed script and run it via fly ssh
    seed_script = '''
import asyncio, os, json
import asyncpg

async def main():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])

    # Ensure table exists
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS qnh_products (
            spu_id TEXT NOT NULL,
            sku_id TEXT DEFAULT '',
            tenant_id TEXT DEFAULT '',
            name TEXT DEFAULT '',
            barcode TEXT DEFAULT '',
            category TEXT DEFAULT '',
            brand TEXT DEFAULT '',
            spec TEXT DEFAULT '',
            unit TEXT DEFAULT '',
            cost_price NUMERIC,
            retail_price NUMERIC,
            channel_price JSONB,
            status TEXT DEFAULT '',
            channel_status JSONB,
            image_url TEXT DEFAULT '',
            extra JSONB,
            synced_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (spu_id, sku_id)
        )
    """)

    # Sample pharmacy products based on known categories
    products = [
        {"spu_id": "1001", "name": "鱼跃制氧机 8F-5AW", "category": "制氧雾化", "brand": "鱼跃", "spec": "5L/min", "retail_price": 2680, "image_url": "https://p0.meituan.net/travelsku/9ce74e94e9fca4d3aa7b8e49e39096f9310641.jpg", "status": "在售"},
        {"spu_id": "1002", "name": "欧姆龙雾化器 NE-C900", "category": "制氧雾化", "brand": "欧姆龙", "spec": "压缩式", "retail_price": 599, "status": "在售"},
        {"spu_id": "1003", "name": "鱼跃轮椅 H062", "category": "轮椅拐杖", "brand": "鱼跃", "spec": "铝合金折叠", "retail_price": 899, "status": "在售"},
        {"spu_id": "1004", "name": "护膝保暖关节套", "category": "康复护具", "brand": "海尔斯", "spec": "均码", "retail_price": 79, "status": "在售"},
        {"spu_id": "1005", "name": "电子血压计 HEM-7136", "category": "监测专区", "brand": "欧姆龙", "spec": "上臂式", "retail_price": 299, "status": "在售"},
        {"spu_id": "1006", "name": "体温计 红外额温枪", "category": "监测专区", "brand": "鱼跃", "spec": "YT-1", "retail_price": 129, "status": "在售"},
        {"spu_id": "1007", "name": "血糖仪套装 GA-3型", "category": "监测专区", "brand": "三诺", "spec": "含50片试纸", "retail_price": 159, "status": "在售"},
        {"spu_id": "1008", "name": "N95口罩 独立包装", "category": "春节应急", "brand": "3M", "spec": "30只/盒", "retail_price": 89, "status": "在售"},
        {"spu_id": "1009", "name": "医用退热贴 儿童型", "category": "春节应急", "brand": "兵兵", "spec": "6片/盒", "retail_price": 25, "status": "在售"},
        {"spu_id": "1010", "name": "碘伏消毒液 500ml", "category": "春节应急", "brand": "海氏海诺", "spec": "500ml", "retail_price": 18, "status": "在售"},
        {"spu_id": "1011", "name": "创可贴 防水型", "category": "春节应急", "brand": "云南白药", "spec": "100片/盒", "retail_price": 32, "status": "在售"},
        {"spu_id": "1012", "name": "腰椎牵引器", "category": "康复护具", "brand": "佳禾", "spec": "充气式", "retail_price": 168, "status": "在售"},
        {"spu_id": "1013", "name": "助行器 四脚拐杖", "category": "轮椅拐杖", "brand": "鱼跃", "spec": "铝合金可调", "retail_price": 128, "status": "在售"},
        {"spu_id": "1014", "name": "雾化面罩 儿童款", "category": "制氧雾化", "brand": "欧姆龙", "spec": "通用接口", "retail_price": 35, "status": "在售"},
        {"spu_id": "1015", "name": "指夹式血氧仪", "category": "监测专区", "brand": "鱼跃", "spec": "YX306", "retail_price": 169, "status": "在售"},
        {"spu_id": "1016", "name": "颈椎按摩仪", "category": "康复护具", "brand": "SKG", "spec": "K5-2", "retail_price": 459, "status": "在售"},
        {"spu_id": "1017", "name": "医用棉签 灭菌型", "category": "春节应急", "brand": "稳健", "spec": "200支/袋", "retail_price": 12, "status": "在售"},
        {"spu_id": "1018", "name": "止血绷带 弹性自粘", "category": "春节应急", "brand": "3M", "spec": "7.5cm*4.5m", "retail_price": 28, "status": "在售"},
        {"spu_id": "1019", "name": "隐形眼镜护理液", "category": "春节应急", "brand": "海昌", "spec": "500ml", "retail_price": 45, "status": "在售"},
        {"spu_id": "1020", "name": "电动轮椅 D130HL", "category": "轮椅拐杖", "brand": "互邦", "spec": "锂电池可折叠", "retail_price": 4580, "status": "在售"},
    ]

    count = 0
    for p in products:
        await pool.execute("""
            INSERT INTO qnh_products (spu_id, sku_id, tenant_id, name, category, brand, spec, retail_price, image_url, status, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
            ON CONFLICT (spu_id, sku_id) DO UPDATE SET
                name=EXCLUDED.name, category=EXCLUDED.category, brand=EXCLUDED.brand,
                spec=EXCLUDED.spec, retail_price=EXCLUDED.retail_price, image_url=EXCLUDED.image_url,
                status=EXCLUDED.status, synced_at=now()
        """, p["spu_id"], "", "1011766", p["name"], p["category"], p["brand"],
            p["spec"], p.get("retail_price"), p.get("image_url", ""), p["status"])
        count += 1

    total = await pool.fetchval("SELECT COUNT(*) FROM qnh_products")
    print(f"Seeded {count} products. Total in DB: {total}")
    await pool.close()

asyncio.run(main())
'''

    # Write and execute via fly ssh
    print("Seeding products via fly ssh...")
    result = subprocess.run(
        [
            "fly",
            "ssh",
            "console",
            "--app",
            "ai-shopkeeper-kk",
            "-C",
            f"python3 -c {repr(seed_script)}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    print("STDOUT:", result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:500])
    return result.returncode


if __name__ == "__main__":
    sys.exit(asyncio.run(seed_via_api()))
