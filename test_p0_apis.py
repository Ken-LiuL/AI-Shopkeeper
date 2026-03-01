#!/usr/bin/env python3
"""
测试新实现的P0 API功能
"""

import asyncio
import httpx
import json

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"
# BASE_URL = "http://localhost:8000"  # 本地测试时使用


async def test_orders_api():
    """测试订单管理API"""
    print("🧪 测试订单管理API...")
    
    async with httpx.AsyncClient() as client:
        # 测试订单列表
        response = await client.get(f"{BASE_URL}/api/orders/list?page=1&limit=10")
        print(f"📊 订单列表: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   返回 {len(data.get('data', []))} 条订单")
        
        # 测试订单统计
        response = await client.get(f"{BASE_URL}/api/orders/stats")
        print(f"📊 订单统计: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   今日GMV: {data.get('data', {}).get('today', {}).get('total_amount', 0)}")


async def test_pricing_api():
    """测试智能定价API"""
    print("🧪 测试智能定价API...")
    
    async with httpx.AsyncClient() as client:
        # 测试定价建议
        response = await client.post(f"{BASE_URL}/api/pricing/suggestions")
        print(f"💰 定价建议: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            suggestions = data.get('data', [])
            print(f"   生成 {len(suggestions)} 条定价建议")
            if suggestions:
                print(f"   示例: {suggestions[0].get('name')} - {suggestions[0].get('suggested_price')}元")
        
        # 测试定价规则
        response = await client.get(f"{BASE_URL}/api/pricing/rules")
        print(f"📋 定价规则: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            rules = data.get('data', [])
            print(f"   配置 {len(rules)} 条定价规则")


async def test_inventory_api():
    """测试库存管理API"""
    print("🧪 测试库存管理API...")
    
    async with httpx.AsyncClient() as client:
        # 测试补货建议
        response = await client.get(f"{BASE_URL}/api/inventory/restock-suggestions")
        print(f"📦 补货建议: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            suggestions = data.get('data', [])
            print(f"   生成 {len(suggestions)} 条补货建议")
            if suggestions:
                print(f"   示例: {suggestions[0].get('name')} - 建议补货 {suggestions[0].get('suggested_restock_qty')} 件")
        
        # 测试库存总览
        response = await client.get(f"{BASE_URL}/api/inventory/overview")
        print(f"📋 库存总览: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            overview = data.get('data', {})
            print(f"   总商品: {overview.get('total_products', 0)} 件")
            print(f"   总库存: {overview.get('total_stock', 0)} 件")


async def test_insights_api():
    """测试AI洞察API"""
    print("🧪 测试AI洞察API...")
    
    async with httpx.AsyncClient(timeout=30) as client:  # AI分析需要更长时间
        # 测试每日洞察
        response = await client.get(f"{BASE_URL}/api/insights/daily")
        print(f"🤖 每日洞察: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            insights = data.get('data', {}).get('ai_insights', {})
            recommendations = insights.get('actionable_recommendations', [])
            print(f"   生成 {len(recommendations)} 条建议")
            if recommendations:
                print(f"   首要建议: {recommendations[0].get('action')}")
        
        # 测试业务预警
        response = await client.get(f"{BASE_URL}/api/insights/alerts")
        print(f"⚠️  业务预警: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            alerts = data.get('data', [])
            print(f"   发现 {len(alerts)} 条预警")


async def test_stores_api():
    """测试多店管理API"""
    print("🧪 测试多店管理API...")
    
    async with httpx.AsyncClient() as client:
        # 测试门店对比
        response = await client.get(f"{BASE_URL}/api/stores/overview")
        print(f"🏪 门店对比: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            stores = data.get('data', {}).get('stores', [])
            print(f"   管理 {len(stores)} 家门店")
            if stores:
                best = stores[0]
                print(f"   最佳表现: {best.get('store_name')} - GMV {best.get('today_gmv')}元")
        
        # 测试单店详情
        poi_id = 1232550  # 主店
        response = await client.get(f"{BASE_URL}/api/stores/{poi_id}/summary")
        print(f"🏪 主店详情: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            store_info = data.get('data', {}).get('store_info', {})
            performance = data.get('data', {}).get('today_performance', {})
            print(f"   {store_info.get('name')} - 今日订单: {performance.get('orders')} 单")


async def test_health_check():
    """测试系统健康状态"""
    print("🧪 测试系统健康状态...")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health")
        print(f"❤️  系统健康: {response.status_code}")
        
        response = await client.get(f"{BASE_URL}/ready")
        print(f"⚡ 系统就绪: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            checks = data.get('data', {})
            for service, status in checks.items():
                if service != 'status':
                    status_icon = "✅" if status else "❌"
                    print(f"   {service}: {status_icon}")


async def main():
    """运行所有测试"""
    print("🚀 开始测试AI店长P0功能...")
    print(f"🌐 测试目标: {BASE_URL}")
    print("=" * 50)
    
    try:
        await test_health_check()
        print()
        
        await test_orders_api()
        print()
        
        await test_pricing_api()
        print()
        
        await test_inventory_api()
        print()
        
        await test_insights_api()
        print()
        
        await test_stores_api()
        print()
        
        print("=" * 50)
        print("✅ P0功能测试完成！")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())