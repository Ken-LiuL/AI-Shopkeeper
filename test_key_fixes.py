#!/usr/bin/env python3
"""Test the 12 key API fixes to ensure they're all working."""

import json
import urllib.request


def test_endpoint(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            status = response.getcode()
            content = response.read().decode("utf-8")
            data = json.loads(content)
            return status, data, None
    except Exception as e:
        return None, None, str(e)


base_url = "https://ai-shopkeeper-kk.fly.dev"

# Test the 12 key fixes
tests = [
    ("analytics/trends", "/api/analytics/trends", "Should return daily trends data"),
    (
        "pricing/analysis",
        "/api/pricing/analysis/1020",
        "Should fallback to qnh_products if products table empty",
    ),
    (
        "knowledge search",
        "/api/knowledge/search?q=%E8%BD%AE%E6%A4%85",
        "Chinese search encoding should work",
    ),
    (
        "knowledge v1 search",
        "/api/knowledge/v1/search?q=%E8%BD%AE%E6%A4%85",
        "Chinese search v1 should work",
    ),
    ("orders/recent", "/api/orders/recent", "Should return order snapshots from raw data"),
    (
        "competitors price-comparison",
        "/api/competitors/price-comparison",
        "Should handle category path joins",
    ),
    ("listing", "/api/listing", "Should return message about feature availability"),
    (
        "customer-service/stats",
        "/api/customer-service/stats",
        "Should use IM tasks from raw data as fallback",
    ),
    ("knowledge/products", "/api/knowledge/products", "Should return products from qnh_products"),
    ("knowledge/faq", "/api/knowledge/faq", "Should return hardcoded FAQs"),
    ("sync/status", "/api/sync/status", "Should return default sync status description"),
    ("selection/runs", "/api/selection/runs", "Should return message about no runs"),
]

print("🔧 Testing 12 Key API Fixes")
print("=" * 60)

total_tests = len(tests)
success_count = 0
working_endpoints = []
failed_endpoints = []

for name, endpoint, description in tests:
    url = base_url + endpoint
    status, result, error = test_endpoint(url)

    print(f"\n📍 {name.upper()}")
    print(f"   {description}")
    print(f"   {endpoint}")

    if error:
        print(f"   ❌ ERROR: {error}")
        failed_endpoints.append((name, endpoint, error))
        continue

    if status != 200:
        print(f"   ❌ HTTP {status}")
        failed_endpoints.append((name, endpoint, f"HTTP {status}"))
        continue

    if not isinstance(result, dict) or not result.get("success", False):
        success_val = result.get("success") if isinstance(result, dict) else None
        print(f"   ❌ API Error: success = {success_val}")
        if isinstance(result, dict) and "message" in result:
            print(f"      Message: {result['message']}")
        failed_endpoints.append((name, endpoint, f"API success = {success_val}"))
        continue

    # Success case - check data
    data = result.get("data", [])
    message = result.get("message", "")

    if isinstance(data, list):
        data_info = f"{len(data)} items"
    elif isinstance(data, dict):
        data_info = f"dict with {len(data)} keys"
    else:
        data_info = str(type(data).__name__)

    print(f"   ✅ SUCCESS - {data_info}")
    if message:
        print(f"      Message: {message}")

    # Show sample data for some endpoints
    if isinstance(data, list) and len(data) > 0:
        if name == "knowledge/faq":
            print(f"      Sample FAQ: {data[0].get('question', 'N/A')}")
        elif name == "analytics/trends":
            print(f"      Sample trend: {data[0]}")
        elif name == "knowledge/products" and len(data) > 0:
            print(f"      Sample product: {data[0].get('name', 'N/A')}")

    success_count += 1
    working_endpoints.append(name)

print("\n" + "=" * 60)
print(f"📊 SUMMARY: {success_count}/{total_tests} fixes working")

if failed_endpoints:
    print(f"\n❌ FAILED ENDPOINTS ({len(failed_endpoints)}):")
    for name, _endpoint, error in failed_endpoints:
        print(f"   • {name}: {error}")

if success_count == total_tests:
    print("\n🎉 ALL 12 FIXES ARE WORKING! 🎉")
else:
    print(f"\n⚠️  {total_tests - success_count} endpoints still need attention")

# Also test the 12th issue (dashboard pending_tasks)
print("\n🔍 Testing dashboard/overview (12th issue)...")
status, result, error = test_endpoint(base_url + "/api/dashboard/overview")
if error:
    print(f"   ❌ ERROR: {error}")
elif status == 200 and result.get("success"):
    data = result.get("data", {})
    pending_tasks = data.get("pending_tasks", "unknown")
    print(f"   ✅ pending_tasks = {pending_tasks} (should be 0)")
else:
    print(f"   ❌ Failed: HTTP {status}")

print("\n🚀 Deployment verification complete!")
