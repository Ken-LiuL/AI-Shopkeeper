#!/usr/bin/env python3
"""临时脚本查看 channel_status 的实际数据格式"""

import asyncio

from src.db import postgres as pg


async def check_channel_status():
    """检查 qnh_products 表中的 channel_status 字段实际存储格式"""

    # 初始化数据库连接池
    await pg.init_pool()
    pool = pg.get_pool()

    print("=== 检查 channel_status 数据格式 ===")

    # 1. 统计不同类型的 channel_status 数据
    status_samples = await pool.fetch("""
        SELECT DISTINCT channel_status, COUNT(*) as count
        FROM qnh_products
        WHERE channel_status IS NOT NULL
        GROUP BY channel_status
        ORDER BY count DESC
        LIMIT 15
    """)

    print("\n1. channel_status 值分布 (前15个):")
    for row in status_samples:
        print(f"  {row['channel_status']} -> {row['count']} 条记录")

    # 2. 查看总体统计
    total_stats = await pool.fetchrow("""
        SELECT
            COUNT(*) as total_products,
            COUNT(channel_status) as has_channel_status,
            COUNT(CASE WHEN channel_status IS NULL THEN 1 END) as null_status,
            COUNT(CASE WHEN channel_status::text = 'null' THEN 1 END) as text_null
        FROM qnh_products
    """)

    print("\n2. 总体统计:")
    print(f"  总商品数: {total_stats['total_products']}")
    print(f"  有 channel_status 的: {total_stats['has_channel_status']}")
    print(f"  channel_status 为 NULL 的: {total_stats['null_status']}")
    print(f"  channel_status 为 'null' 文本的: {total_stats['text_null']}")

    # 3. 查看具体数据样例
    sample_products = await pool.fetch("""
        SELECT spu_id, name, channel_status, status, retail_price
        FROM qnh_products
        WHERE channel_status IS NOT NULL
        LIMIT 10
    """)

    print("\n3. 数据样例 (前10个):")
    for product in sample_products:
        print(f"  商品: {product['name'][:20]}...")
        print(f"    channel_status: {product['channel_status']}")
        print(f"    status: {product['status']}")
        print(f"    retail_price: {product['retail_price']}")

        # 如果是JSONB，尝试解析具体字段
        channel_status = product["channel_status"]
        if isinstance(channel_status, dict):
            print(f"    channel_status 是字典，包含键: {list(channel_status.keys())}")
            for key, value in channel_status.items():
                print(f"      {key}: {value}")
        print()


if __name__ == "__main__":
    asyncio.run(check_channel_status())
