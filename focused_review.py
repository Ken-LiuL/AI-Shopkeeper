#!/usr/bin/env python3
"""Focused review - identify specific issues to fix"""

import json
import urllib.request
from typing import Any


def request_api(
    endpoint: str, base_url: str = "https://ai-shopkeeper-kk.fly.dev"
) -> dict[str, Any]:
    url = base_url + endpoint
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            content = response.read().decode("utf-8")
            return {"success": True, "data": json.loads(content)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def main():
    issues = []

    print("🔍 Focused API Review")
    print("=" * 40)

    # 1. Check basic endpoints first
    print("\n1. Testing basic endpoints...")
    basic_endpoints = [
        "/api/dashboard/overview",
        "/api/products/recommendations",
        "/api/knowledge/search?q=轮椅",
        "/api/reports/export",
    ]

    for endpoint in basic_endpoints:
        result = request_api(endpoint)
        if not result["success"]:
            issues.append(f"❌ {endpoint}: {result['error']}")
            print(f"❌ {endpoint}: {result['error']}")
        else:
            print(f"✅ {endpoint}")

    # 2. Test data quality issues
    print("\n2. Testing data quality...")

    # Check price comparison data
    result = request_api("/api/competitors/price-comparison")
    if result["success"]:
        data = result["data"]
        if isinstance(data, list):
            extreme_prices = []
            for item in data:
                try:
                    our_price = float(item.get("our_price", 0))
                    competitor_price = float(item.get("competitor_price", 0))
                    if our_price > 0 and competitor_price > 0:
                        ratio = competitor_price / our_price
                        if ratio > 100 or ratio < 0.01:  # 100x difference
                            extreme_prices.append(
                                {
                                    "our": our_price,
                                    "comp": competitor_price,
                                    "ratio": ratio,
                                    "product": item.get("name", "")[:50],
                                }
                            )
                except (ValueError, TypeError):
                    continue

            if extreme_prices:
                issues.append(f"❌ Found {len(extreme_prices)} extreme price differences")
                print(f"❌ Found {len(extreme_prices)} extreme price differences:")
                for p in extreme_prices[:3]:  # Show first 3
                    print(f"   ¥{p['our']} vs ¥{p['comp']:.2f} - {p['product']}")

    # 3. Test missing endpoints
    print("\n3. Testing missing endpoints...")
    missing_endpoints = ["/api/customer-service/chat", "/api/products/recommendations"]

    for endpoint in missing_endpoints:
        result = request_api(endpoint)
        if not result["success"] and "404" in str(result["error"]):
            issues.append(f"❌ Missing endpoint: {endpoint}")
            print(f"❌ Missing endpoint: {endpoint}")

    # 4. Test edge cases
    print("\n4. Testing edge cases...")
    edge_cases = ["/api/products?page=-1", "/api/knowledge/search?q=", "/api/products/999999999"]

    for endpoint in edge_cases:
        result = request_api(endpoint)
        if result["success"] and "error" not in str(result.get("data", {})):
            issues.append(f"⚠️  Poor error handling: {endpoint}")
            print(f"⚠️  Poor error handling: {endpoint}")

    print(f"\n📋 Summary: {len(issues)} issues found")
    if issues:
        for issue in issues:
            print(issue)
    else:
        print("🎉 No major issues found!")

    return issues


if __name__ == "__main__":
    main()
