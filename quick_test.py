#!/usr/bin/env python3
"""Quick test of the key fixed API endpoints."""

import json
import urllib.request


def test_endpoint(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            status = response.getcode()
            content = response.read().decode("utf-8")
            data = json.loads(content)
            return status, data
    except Exception as e:
        return None, str(e)


base_url = "https://ai-shopkeeper-kk.fly.dev"

# Test key endpoints
endpoints = [
    "/api/analytics/trends",
    "/api/listing",
    "/api/knowledge/faq",
    "/api/knowledge/search?q=%E8%BD%AE%E6%A4%85",
    "/api/knowledge/v1/search?q=%E8%BD%AE%E6%A4%85",
]

print("🧪 Quick API Test Results:")
print("=" * 50)

for endpoint in endpoints:
    url = base_url + endpoint
    status, result = test_endpoint(url)

    if status:
        success = result.get("success", False) if isinstance(result, dict) else False
        data_len = (
            len(result.get("data", [])) if isinstance(result, dict) and result.get("data") else 0
        )
        message = result.get("message", "") if isinstance(result, dict) else ""

        status_icon = "✅" if success else "❌"
        print(f"{status_icon} {endpoint}")
        print(f"    Status: {status}, Success: {success}")
        if data_len > 0:
            print(f"    Data items: {data_len}")
        if message:
            print(f"    Message: {message}")
        print()
    else:
        print(f"❌ {endpoint}")
        print(f"    Error: {result}")
        print()
