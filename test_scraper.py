#!/usr/bin/env python3
"""
简化的竞品采集测试脚本
"""

import asyncio
import sys

sys.path.append(".")

from scripts.real_competitor_scraper_json import RealCompetitorScraperJSON


async def test_scraper():
    """测试采集器基本功能"""
    print("🚀 开始测试竞品采集...")

    scraper = RealCompetitorScraperJSON(mode="json")

    # 只测试第一个关键词
    test_keyword = "血压计"

    try:
        # 初始化浏览器
        if not await scraper.init_browser():
            print("❌ 浏览器初始化失败")
            return

        print(f"✅ 浏览器启动成功，测试搜索: {test_keyword}")

        # 访问美团首页
        await scraper.tab.get("https://h5.waimai.meituan.com/")
        await asyncio.sleep(3)
        print("✅ 已访问美团首页")

        # 测试搜索一个关键词
        products = await scraper.search_products(test_keyword, max_results=5)
        print(f"✅ 搜索 '{test_keyword}' 得到 {len(products)} 个结果")

        if products:
            print("📦 示例产品:")
            for i, p in enumerate(products[:3]):
                print(f"  {i + 1}. {p['name'][:30]} - ¥{p['price']} - {p['monthly_sales']}销量")

            # 保存到JSON
            await scraper.save_to_json(products, test_keyword)
            scraper.write_json_file()
            print("✅ 数据已保存到JSON文件")
        else:
            print("⚠️ 未获取到产品数据")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await scraper.close_browser()
        print("🏁 测试完成")


if __name__ == "__main__":
    asyncio.run(test_scraper())
