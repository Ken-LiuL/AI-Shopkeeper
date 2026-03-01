#!/usr/bin/env python3

import asyncio

import aiohttp


async def test_api_endpoints():
    """测试三个有问题的API端点"""

    base_url = "http://localhost:8000"

    endpoints = [
        "/api/products/pricing",  # 问题1: 应该返回404
        "/api/store/overview",  # 问题2: 应该返回404
        "/api/inventory/overview",  # 问题3: 返回数据全是0
    ]

    async with aiohttp.ClientSession() as session:
        for endpoint in endpoints:
            try:
                url = f"{base_url}{endpoint}"
                async with session.get(url) as response:
                    print(f"\n=== {endpoint} ===")
                    print(f"Status: {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        print(f"Response: {data}")
                    else:
                        text = await response.text()
                        print(f"Error: {text}")
            except Exception as e:
                print(f"\n=== {endpoint} ===")
                print(f"Exception: {e}")


if __name__ == "__main__":
    asyncio.run(test_api_endpoints())
