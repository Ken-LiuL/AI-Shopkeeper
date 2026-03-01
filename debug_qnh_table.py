#!/usr/bin/env python3

import asyncio
import sys

sys.path.append("/Users/pengkun/Dropbox/workspace/ai-store-manager")

from src.db import postgres as pg


async def debug_qnh_table():
    """检查qnh_products表结构和数据"""

    # 初始化数据库连接
    await pg.init_pool()
    pool = pg.get_pool()

    try:
        # 1. 检查表结构
        print("=== qnh_products 表结构 ===")
        columns = await pool.fetch("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'qnh_products'
            ORDER BY ordinal_position
        """)

        for col in columns:
            print(
                f"{col['column_name']}: {col['data_type']} ({'NULL' if col['is_nullable'] == 'YES' else 'NOT NULL'})"
            )

        # 2. 检查数据样本
        print("\n=== 数据样本 (前5条) ===")
        samples = await pool.fetch("""
            SELECT spu_id, name, category, channel_status, retail_price
            FROM qnh_products
            LIMIT 5
        """)

        for row in samples:
            print(f"ID: {row['spu_id']}, Name: {row['name']}, Category: {row['category']}")
            print(f"  Status: {row['channel_status']}, Price: {row['retail_price']}")
            print()

        # 3. 检查channel_status的不同值
        print("\n=== channel_status 不同值统计 ===")
        status_counts = await pool.fetch("""
            SELECT channel_status, COUNT(*) as count
            FROM qnh_products
            GROUP BY channel_status
            ORDER BY count DESC
        """)

        for row in status_counts:
            print(f"'{row['channel_status']}': {row['count']} 条")

        # 4. 检查category不同值
        print("\n=== category 不同值统计 (前10个) ===")
        category_counts = await pool.fetch("""
            SELECT category, COUNT(*) as count
            FROM qnh_products
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category
            ORDER BY count DESC
            LIMIT 10
        """)

        for row in category_counts:
            print(f"'{row['category']}': {row['count']} 条")

    except Exception as e:
        print(f"错误: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await pg.close_pool()


if __name__ == "__main__":
    asyncio.run(debug_qnh_table())
