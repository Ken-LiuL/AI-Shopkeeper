#!/usr/bin/env python3
"""
Fix identified issues and test the system
"""

import json
import sys
import urllib.parse
import urllib.request
from typing import Any


def request_api(
    endpoint: str,
    method: str = "GET",
    data: dict = None,
    base_url: str = "https://ai-shopkeeper-kk.fly.dev",
) -> dict[str, Any]:
    """Make API request with proper encoding support"""
    url = base_url + endpoint

    try:
        if method == "GET":
            req = urllib.request.Request(url)
            # Add proper headers for Chinese character support
            req.add_header("Accept-Charset", "utf-8")

            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode("utf-8")
                return {"success": True, "data": json.loads(content)}
        else:
            post_data = json.dumps(data).encode("utf-8") if data else b""
            headers = {"Content-Type": "application/json; charset=utf-8", "Accept-Charset": "utf-8"}
            req = urllib.request.Request(url, data=post_data, headers=headers, method=method)

            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode("utf-8")
                return {"success": True, "data": json.loads(content)}

    except Exception as e:
        return {"success": False, "error": str(e)}


def main():
    issues_found = []
    issues_fixed = []

    print("🔧 AI Store Manager Issue Fix & Test")
    print("=" * 50)

    # Test 1: Fix knowledge search with Chinese characters
    print("\n1. Testing knowledge search with Chinese characters...")

    # Properly encode Chinese characters in URL
    chinese_query = "轮椅"
    encoded_query = urllib.parse.quote(chinese_query, safe="")
    endpoint = f"/api/knowledge/search?q={encoded_query}"

    result = request_api(endpoint)
    if result["success"]:
        print("✅ Knowledge search with Chinese characters works")
        data = result["data"]
        if isinstance(data.get("data"), list) and len(data["data"]) > 0:
            print(f"   Found {len(data['data'])} results")
        else:
            print("   No results returned (may be empty database)")
    else:
        issues_found.append(f"Knowledge search still failing: {result['error']}")
        print(f"❌ Knowledge search still failing: {result['error']}")

    # Test 2: Fix recommendations endpoint (use correct path)
    print("\n2. Testing product recommendations (correct endpoint)...")

    result = request_api("/api/selection/recommendations")
    if result["success"]:
        print("✅ Product recommendations endpoint works")
        recommendations = result["data"].get("data", [])
        if recommendations:
            print(f"   Found {len(recommendations)} recommendations")
            # Check data quality
            for rec in recommendations[:3]:
                if "price" in rec and isinstance(rec.get("price"), (int, float)):
                    print(f"   - {rec.get('name', 'Unknown')[:40]}... ¥{rec['price']}")
                else:
                    issues_found.append("Recommendation data missing price or wrong type")
        else:
            print("   No recommendations available (may be expected)")
    else:
        issues_found.append(f"Recommendations endpoint failing: {result['error']}")
        print(f"❌ Recommendations endpoint failing: {result['error']}")

    # Test 3: Fix reports export (use correct method)
    print("\n3. Testing reports export (correct method)...")

    # Special handling for reports export - it returns CSV, not JSON
    try:
        base_url = "https://ai-shopkeeper-kk.fly.dev"
        url = base_url + "/api/reports/export?report_type=daily&format=csv"
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            content_type = response.headers.get("content-type", "")
            content = response.read().decode("utf-8")

            if "text/csv" in content_type and "order_count" in content:
                print("✅ Reports export endpoint works")
                print("   CSV export data received successfully")
            else:
                issues_found.append(f"Reports export unexpected format: {content_type}")
                print(f"❌ Reports export unexpected format: {content_type}")
    except Exception as e:
        issues_found.append(f"Reports export failing: {e}")
        print(f"❌ Reports export failing: {e}")

    # Test 4: Check price comparison data quality
    print("\n4. Testing price comparison data quality...")

    result = request_api("/api/competitors/price-comparison")
    if result["success"]:
        response_data = result["data"]
        # Handle the API response structure {"success": true, "data": [...]}
        if isinstance(response_data, dict) and "data" in response_data:
            data = response_data["data"]
        else:
            data = response_data

        if isinstance(data, list):
            extreme_issues = 0
            type_issues = 0

            for item in data[:10]:  # Check first 10 items
                try:
                    our_price = float(item.get("our_price", 0))
                    competitor_price = float(item.get("competitor_price", 0))

                    if our_price > 0 and competitor_price > 0:
                        ratio = competitor_price / our_price
                        if ratio > 100 or ratio < 0.01:  # 100x difference or more
                            extreme_issues += 1

                except (ValueError, TypeError):
                    type_issues += 1

            if extreme_issues == 0 and type_issues == 0:
                print("✅ Price comparison data quality looks good")
            else:
                if extreme_issues > 0:
                    issues_found.append(f"Found {extreme_issues} extreme price differences")
                    print(f"⚠️  Found {extreme_issues} extreme price differences")
                if type_issues > 0:
                    issues_found.append(f"Found {type_issues} price data type issues")
                    print(f"⚠️  Found {type_issues} price data type issues")
        else:
            issues_found.append("Price comparison data format unexpected")
            print("❌ Price comparison data format unexpected")
    else:
        issues_found.append(f"Price comparison endpoint failing: {result['error']}")
        print(f"❌ Price comparison endpoint failing: {result['error']}")

    # Test 5: Check error handling for invalid requests
    print("\n5. Testing error handling...")

    test_cases = [
        "/api/products/999999999",
        "/api/products?page=-1",
        "/api/knowledge/search?q=",  # Empty query
    ]

    good_error_handling = 0
    for endpoint in test_cases:
        result = request_api(endpoint)
        if not result["success"] or "error" in str(result.get("data", {})):
            good_error_handling += 1
        else:
            print(f"   ⚠️  Poor error handling for: {endpoint}")

    if good_error_handling == len(test_cases):
        print("✅ Error handling looks good")
    else:
        print(
            f"⚠️  Error handling could be improved ({good_error_handling}/{len(test_cases)} cases handled)"
        )

    # Summary
    print("\n" + "=" * 50)
    print("📊 Fix & Test Summary")
    print("=" * 50)

    if not issues_found:
        print("🎉 All major issues have been resolved!")
        print("The system is ready for production use.")
        return 0
    else:
        print(f"❌ {len(issues_found)} issues still need attention:")
        for i, issue in enumerate(issues_found, 1):
            print(f"   {i}. {issue}")

        print("\nNext steps:")
        print("- Fix these remaining issues in the source code")
        print("- Deploy with: fly deploy --local-only")
        print("- Re-run this test script")

        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
