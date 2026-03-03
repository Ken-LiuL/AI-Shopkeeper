#!/usr/bin/env python3
"""
上传竞品数据到线上Fly.io数据库
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

import asyncpg

# 数据文件路径
JSON_DATA_PATH = Path(__file__).parent / "data" / "competitor_products.json"

# 本地数据库配置（先测试本地）
PRODUCTION_DB_URL = "postgresql://postgres:postgres@localhost:5432/ai_store"


async def upload_to_database():
    """将JSON数据上传到数据库"""
    print("🚀 开始上传竞品数据到数据库...")

    # 读取JSON数据
    try:
        with open(JSON_DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        print(f"📁 读取JSON数据: {data['total_products']} 个产品, {data['total_stores']} 个店铺")
    except FileNotFoundError:
        print(f"❌ 数据文件不存在: {JSON_DATA_PATH}")
        return False
    except Exception as e:
        print(f"❌ 读取JSON数据失败: {e}")
        return False

    # 连接数据库
    try:
        print("🔗 连接数据库...")
        conn = await asyncpg.connect(PRODUCTION_DB_URL)
        print("✅ 数据库连接成功")
    except Exception as e:
        print(f"❌ 连接线上数据库失败: {e}")
        print("💡 请确保本地PostgreSQL正在运行")
        return False

    try:
        # 清理旧数据
        await conn.execute(
            "DELETE FROM competitor_products WHERE last_synced < NOW() - INTERVAL '7 days'"
        )
        await conn.execute(
            "DELETE FROM competitor_stores WHERE last_synced < NOW() - INTERVAL '7 days'"
        )

        # 先上传店铺数据
        store_count = 0
        for store in data["stores"]:
            await conn.execute(
                """
                INSERT INTO competitor_stores (
                    store_id, name, rating, monthly_sales, distance_km,
                    category, last_synced
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (store_id) DO UPDATE SET
                    rating = EXCLUDED.rating,
                    monthly_sales = EXCLUDED.monthly_sales,
                    distance_km = EXCLUDED.distance_km,
                    last_synced = EXCLUDED.last_synced
            """,
                store["store_id"],
                store["name"],
                store.get("rating", 0),
                store["monthly_sales"],
                store.get("distance_km", 0),
                store["category"],
                datetime.now(),
            )
            store_count += 1

        print(f"✅ 已上传 {store_count} 个店铺")

        # 然后上传产品数据
        product_count = 0
        for product in data["products"]:
            await conn.execute(
                """
                INSERT INTO competitor_products (
                    product_id, store_id, name, price, monthly_sales, rating,
                    category, last_synced
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (product_id) DO UPDATE SET
                    price = EXCLUDED.price,
                    monthly_sales = EXCLUDED.monthly_sales,
                    rating = EXCLUDED.rating,
                    last_synced = EXCLUDED.last_synced
            """,
                product["product_id"],
                product.get("store_id", ""),
                product["name"],
                product["price"],
                product["monthly_sales"],
                product.get("rating", 0),
                product["category"],
                datetime.now(),
            )
            product_count += 1

        print(f"✅ 已上传 {product_count} 个产品")

        # 上传关键词数据
        keyword_count = 0
        for keyword in data["keywords"]:
            await conn.execute(
                """
                INSERT INTO competitor_keywords (keyword, search_volume, result_count, last_synced)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (keyword) DO UPDATE SET
                    result_count = EXCLUDED.result_count,
                    last_synced = EXCLUDED.last_synced
            """,
                keyword["keyword"],
                keyword["search_volume"],
                keyword["result_count"],
                datetime.now(),
            )
            keyword_count += 1

        print(f"✅ 已上传 {keyword_count} 个关键词")

        # 验证上传结果
        total_products = await conn.fetchval("SELECT COUNT(*) FROM competitor_products")
        total_stores = await conn.fetchval("SELECT COUNT(*) FROM competitor_stores")
        total_keywords = await conn.fetchval("SELECT COUNT(*) FROM competitor_keywords")

        print("\n📊 数据库统计:")
        print(f"   竞品商品: {total_products}")
        print(f"   竞品店铺: {total_stores}")
        print(f"   搜索关键词: {total_keywords}")

        print("\n🎉 竞品数据上传成功！数据库现在有真实的竞品数据")
        return True

    except Exception as e:
        print(f"❌ 上传数据失败: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        await conn.close()


async def main():
    """主函数"""
    print("=" * 50)
    print("🏪 AI店长 - 竞品数据上传工具")
    print("=" * 50)

    success = await upload_to_database()

    if success:
        print("\n✅ 任务完成！数据库现在使用真实竞品数据")
    else:
        print("\n❌ 上传失败，请检查错误信息")

    return success


if __name__ == "__main__":
    asyncio.run(main())
