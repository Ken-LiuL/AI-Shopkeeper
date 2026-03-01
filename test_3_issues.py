#!/usr/bin/env python3
"""Test the 3 specific issues that were supposed to be fixed."""

import asyncio

import httpx

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"


async def test_3_issues():
    """Test the 3 specific issues."""

    print("🧪 Testing 3 Fixed Issues")
    print(f"🌐 Target: {BASE_URL}")
    print("=" * 50)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Issue 1: Chat endpoint 404
        print("1️⃣ Testing Chat endpoint 404")
        try:
            response = await client.post(
                f"{BASE_URL}/api/v1/chat",
                json={"message": "今天销售怎么样", "session_id": "test-session"},
            )
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(
                    f"   ✅ Chat endpoint working! Got reply: {len(data.get('data', {}).get('reply', '')) > 0}"
                )
            else:
                print(f"   ❌ Still failing: {response.text[:100]}")
        except Exception as e:
            print(f"   ❌ Error: {e}")

        print()

        # Issue 2: Products list parsing error
        print("2️⃣ Testing Products list parsing error")
        try:
            response = await client.get(f"{BASE_URL}/api/v1/products/list")
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                products = data.get("data", [])
                print(f"   ✅ Products list working! Got {len(products)} products")
                if products:
                    first_product = products[0]
                    print(
                        f"   Example product: {first_product.get('name', 'N/A')} - ¥{first_product.get('retail_price', 0)}"
                    )
            else:
                print(f"   ❌ Still failing: {response.text[:100]}")
        except Exception as e:
            print(f"   ❌ Error: {e}")

        print()

        # Issue 3: Alerts table schema missing
        print("3️⃣ Testing Alerts table schema")
        try:
            response = await client.get(f"{BASE_URL}/api/alerts/")
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                alerts = data.get("data", [])
                print(f"   ✅ Alerts endpoint working! Got {len(alerts)} alerts")
                if alerts:
                    first_alert = alerts[0]
                    print(
                        f"   Example alert: {first_alert.get('title', 'N/A')} - {first_alert.get('severity', 'N/A')}"
                    )
            else:
                print(f"   ❌ Still failing: {response.text[:100]}")
        except Exception as e:
            print(f"   ❌ Error: {e}")

        print()
        print("=" * 50)
        print("🏁 Test Complete!")


if __name__ == "__main__":
    asyncio.run(test_3_issues())
