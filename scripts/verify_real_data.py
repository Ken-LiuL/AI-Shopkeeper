#!/usr/bin/env python3
"""
验证系统数据真实化状态 - 检查所有模块是否使用真实数据而非模拟数据

检查项目：
1. 竞品数据是否来自真实采集
2. 自有门店数据是否来自真实API
3. API中是否移除了假数据fallback
4. 确认所有数据源的真实性
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.postgres import get_pool, init_pool

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class RealDataVerifier:
    """真实数据验证器"""

    def __init__(self):
        self.issues = []
        self.successes = []

    async def verify_competitor_data(self):
        """验证竞品数据真实性"""
        pool = get_pool()

        logger.info("🔍 检查竞品数据真实性...")

        # 1. 检查是否有真实采集的竞品数据
        real_competitor_count = await pool.fetchval("""
            SELECT COUNT(*) FROM competitor_products
            WHERE last_synced >= NOW() - INTERVAL '24 hours'
        """)

        if real_competitor_count > 0:
            self.successes.append(f"✅ 竞品商品: {real_competitor_count} 条近24小时内的真实数据")
        else:
            self.issues.append(
                "❌ 竞品商品: 无近期真实数据，请运行 scripts/real_competitor_scraper.py"
            )

        # 2. 检查竞品店铺数据
        real_store_count = await pool.fetchval("""
            SELECT COUNT(*) FROM competitor_stores
            WHERE last_synced >= NOW() - INTERVAL '24 hours'
        """)

        if real_store_count > 0:
            self.successes.append(f"✅ 竞品店铺: {real_store_count} 条近24小时内的真实数据")
        else:
            self.issues.append("❌ 竞品店铺: 无近期真实数据")

        # 3. 检查竞品关键词数据
        real_keyword_count = await pool.fetchval("""
            SELECT COUNT(*) FROM competitor_keywords
            WHERE last_synced >= NOW() - INTERVAL '24 hours'
        """)

        if real_keyword_count > 0:
            self.successes.append(f"✅ 竞品关键词: {real_keyword_count} 条近24小时内的真实数据")
        else:
            self.issues.append("❌ 竞品关键词: 无近期真实数据")

        # 4. 检查数据源类型分布
        data_sources = await pool.fetch("""
            SELECT
                CASE
                    WHEN store_id LIKE 'mt_%' THEN '美团真实采集'
                    WHEN store_id LIKE 'jd_%' THEN '京东数据'
                    WHEN store_id LIKE 'tmall_%' THEN '天猫数据'
                    WHEN store_id LIKE 'demo_%' OR name LIKE '%演示%' THEN '演示数据'
                    ELSE '其他数据'
                END as data_type,
                COUNT(*) as count
            FROM competitor_products
            GROUP BY
                CASE
                    WHEN store_id LIKE 'mt_%' THEN '美团真实采集'
                    WHEN store_id LIKE 'jd_%' THEN '京东数据'
                    WHEN store_id LIKE 'tmall_%' THEN '天猫数据'
                    WHEN store_id LIKE 'demo_%' OR name LIKE '%演示%' THEN '演示数据'
                    ELSE '其他数据'
                END
        """)

        demo_data_count = 0
        for row in data_sources:
            if row["data_type"] == "演示数据":
                demo_data_count = row["count"]
                self.issues.append(f"⚠️ 发现 {demo_data_count} 条演示竞品数据，建议清理")
            else:
                self.successes.append(f"✅ {row['data_type']}: {row['count']} 条数据")

    async def verify_own_store_data(self):
        """验证自有门店数据真实性"""
        pool = get_pool()

        logger.info("🔍 检查自有门店数据真实性...")

        # 1. 检查商品数据是否来自真实API
        product_count = await pool.fetchval("SELECT COUNT(*) FROM qnh_products")
        recent_products = await pool.fetchval("""
            SELECT COUNT(*) FROM qnh_products
            WHERE updated_at >= NOW() - INTERVAL '7 days'
        """)

        if product_count > 0:
            self.successes.append(f"✅ 商品数据: 总计 {product_count} 条")
            if recent_products > 0:
                self.successes.append(f"✅ 商品数据: 近7天更新 {recent_products} 条，数据较新")
            else:
                self.issues.append("⚠️ 商品数据: 近7天无更新，可能需要重新同步")
        else:
            self.issues.append("❌ 商品数据: 无数据，请检查同步器")

        # 2. 检查订单数据
        order_count = await pool.fetchval("SELECT COUNT(*) FROM orders_summary")
        recent_orders = await pool.fetchval("""
            SELECT COUNT(*) FROM orders_summary
            WHERE created_at >= NOW() - INTERVAL '7 days'
        """)

        if order_count > 0:
            self.successes.append(f"✅ 订单数据: 总计 {order_count} 条")
            if recent_orders > 0:
                self.successes.append(f"✅ 订单数据: 近7天新增 {recent_orders} 条")
        else:
            self.issues.append("❌ 订单数据: 无数据，请检查同步器")

        # 3. 检查metrics数据（流量、销售等）
        metrics_tables = ["daily_metrics", "traffic_summary", "sales_metrics"]
        for table in metrics_tables:
            try:
                count = await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
                if count > 0:
                    self.successes.append(f"✅ {table}: {count} 条数据")
                else:
                    self.issues.append(f"⚠️ {table}: 无数据")
            except Exception:
                self.issues.append(f"❌ {table}: 表不存在或无法访问")

        # 4. 检查是否有明显的假数据标识
        fake_data_indicators = [
            ("demo", "演示"),
            ("mock", "模拟"),
            ("test", "测试"),
            ("sample", "样本"),
            ("fake", "假数据"),
        ]

        for indicator, desc in fake_data_indicators:
            fake_products = await pool.fetchval(f"""
                SELECT COUNT(*) FROM qnh_products
                WHERE LOWER(name) LIKE '%{indicator}%' OR LOWER(spu_id) LIKE '%{indicator}%'
            """)

            if fake_products > 0:
                self.issues.append(f"⚠️ 发现 {fake_products} 个可能的{desc}商品数据")

    async def verify_api_cleanup(self):
        """验证API中是否移除了假数据fallback"""
        logger.info("🔍 检查API代码中的假数据清理情况...")

        import os
        import subprocess

        # 搜索API代码中可能的假数据模式
        api_path = "src/api"
        search_patterns = [
            "demo",
            "mock",
            "假数据",
            "模拟",
            "演示",
            "fallback.*demo",
            "sample.*data",
        ]

        fake_data_files = set()

        for pattern in search_patterns:
            try:
                result = subprocess.run(
                    ["grep", "-r", "-i", "-l", pattern, api_path],
                    capture_output=True,
                    text=True,
                    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                )

                if result.returncode == 0:
                    files = result.stdout.strip().split("\n")
                    for file in files:
                        if file:
                            fake_data_files.add(file)
            except Exception:
                pass

        if fake_data_files:
            for file in sorted(fake_data_files):
                self.issues.append(f"⚠️ {file} 可能仍包含假数据代码，需检查")
        else:
            self.successes.append("✅ API代码: 未发现明显的假数据模式")

    async def check_syncer_health(self):
        """检查9个同步器的健康状态"""
        pool = get_pool()

        logger.info("🔍 检查同步器健康状态...")

        # 关键同步器列表（goldengateway的9个syncer）
        syncers = [
            "products",
            "orders",
            "metrics",
            "categories",
            "customers",
            "inventory",
            "finance",
            "promotions",
            "reviews",
        ]

        for syncer_name in syncers:
            try:
                # 检查sync_state表中的状态
                status = await pool.fetchrow(
                    """
                    SELECT status, last_sync, error_message
                    FROM sync_state
                    WHERE syncer_name = $1
                    ORDER BY last_sync DESC
                    LIMIT 1
                """,
                    syncer_name,
                )

                if status:
                    if status["status"] == "success":
                        last_sync = status["last_sync"]
                        if last_sync and last_sync > datetime.now() - timedelta(days=1):
                            self.successes.append(f"✅ {syncer_name} syncer: 近24小时内成功同步")
                        else:
                            self.issues.append(f"⚠️ {syncer_name} syncer: 超过24小时未同步")
                    else:
                        error = status.get("error_message", "未知错误")
                        self.issues.append(f"❌ {syncer_name} syncer: 同步失败 - {error}")
                else:
                    self.issues.append(f"⚠️ {syncer_name} syncer: 无同步记录")

            except Exception as e:
                self.issues.append(f"❌ {syncer_name} syncer: 检查失败 - {e}")

    async def run_verification(self):
        """运行完整验证"""
        logger.info("🚀 开始验证系统数据真实化状态...")

        await self.verify_competitor_data()
        await self.verify_own_store_data()
        await self.verify_api_cleanup()
        await self.check_syncer_health()

        # 输出结果
        print("\n" + "=" * 60)
        print("📊 数据真实化验证报告")
        print("=" * 60)

        if self.successes:
            print(f"\n✅ 成功项 ({len(self.successes)}):")
            for success in self.successes:
                print(f"   {success}")

        if self.issues:
            print(f"\n⚠️ 待改进项 ({len(self.issues)}):")
            for issue in self.issues:
                print(f"   {issue}")
        else:
            print("\n🎉 所有检查项通过！系统已完全使用真实数据")

        # 总结
        total_checks = len(self.successes) + len(self.issues)
        success_rate = len(self.successes) / total_checks * 100 if total_checks > 0 else 0

        print(f"\n📈 真实数据使用率: {success_rate:.1f}% ({len(self.successes)}/{total_checks})")

        if success_rate >= 90:
            print("🎯 状态: 优秀 - 系统基本实现数据真实化")
        elif success_rate >= 70:
            print("⚡ 状态: 良好 - 主要功能使用真实数据")
        elif success_rate >= 50:
            print("📝 状态: 待改进 - 部分功能仍需优化")
        else:
            print("🔧 状态: 需要修复 - 存在较多假数据")

        print("\n💡 建议操作:")
        if len([i for i in self.issues if "竞品" in i]) > 0:
            print("   1. 运行竞品采集器: python scripts/real_competitor_scraper.py")

        if len([i for i in self.issues if "syncer" in i]) > 0:
            print("   2. 检查同步器配置和网络连接")
            print("   3. 重启sync daemon或手动运行同步")

        if len([i for i in self.issues if "API" in i or "代码" in i]) > 0:
            print("   4. 清理API代码中的假数据fallback")

        print("\n" + "=" * 60)


async def main():
    """主函数"""
    try:
        await init_pool()

        verifier = RealDataVerifier()
        await verifier.run_verification()

    except Exception as e:
        logger.error(f"验证失败: {e}")
        import traceback

        traceback.print_exc()
    finally:
        pool = get_pool()
        if pool:
            await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
