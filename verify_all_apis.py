#!/usr/bin/env python3
"""Verify all 36 API endpoints are working correctly."""

import json
import sys
import urllib.parse
import urllib.request


def test_endpoint(base_url: str, endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """Test a single API endpoint."""
    url = base_url + endpoint
    print(f"Testing {method} {endpoint}...", end=" ")

    try:
        if method == "GET":
            with urllib.request.urlopen(url, timeout=15) as response:
                status = response.getcode()
                content = response.read().decode("utf-8")
        else:
            # POST method
            post_data = json.dumps(data).encode("utf-8") if data else None
            headers = {"Content-Type": "application/json"} if data else {}
            req = urllib.request.Request(url, data=post_data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=15) as response:
                status = response.getcode()
                content = response.read().decode("utf-8")

        # Parse JSON response
        try:
            response_data = json.loads(content)
        except json.JSONDecodeError:
            response_data = {"raw": content[:200]}

        print(f"✅ {status}")
        return {
            "endpoint": endpoint,
            "method": method,
            "status": status,
            "success": True,
            "data": response_data,
        }

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return {
            "endpoint": endpoint,
            "method": method,
            "status": None,
            "success": False,
            "error": str(e),
        }


def main():
    base_url = "https://ai-shopkeeper-kk.fly.dev"

    # List of all API endpoints to test
    endpoints = [
        # Dashboard
        "/api/dashboard/overview",
        "/api/dashboard/sales-trend",
        # Analytics
        "/api/analytics/overview",
        "/api/analytics/customer-service",
        "/api/analytics/trends",
        "/api/analytics/conversion",
        # Orders
        "/api/orders/recent",
        "/api/orders/stats",
        "/api/orders/trend",
        "/api/orders/refunds",
        "/api/orders",
        # Products
        "/api/products/search",
        "/api/products/categories",
        "/api/products/trending",
        "/api/products/recommendations",
        "/api/products",
        # Pricing
        "/api/pricing/suggestions",
        "/api/pricing/analysis/1020",  # Test with specific product ID
        # Competitors
        "/api/competitors/stores",
        "/api/competitors/products",
        "/api/competitors/price-comparison",
        # Customer Service
        "/api/customer-service/sessions",
        "/api/customer-service/stats",
        "/api/customer-service/analytics",
        # Knowledge
        "/api/knowledge/search?q=轮椅",
        "/api/knowledge/v1/search?q=轮椅",
        "/api/knowledge/products",
        "/api/knowledge/faq",
        "/api/knowledge/status",
        # Sync
        "/api/sync/status",
        "/api/sync/history",
        # Selection
        "/api/selection/runs",
        "/api/selection/recommendations",
        # Listing
        "/api/listing",
        # Reports
        "/api/reports/daily",
        "/api/reports/weekly",
    ]

    print(f"🚀 Testing {len(endpoints)} API endpoints...")
    print(f"Base URL: {base_url}")
    print("=" * 60)

    results = []
    success_count = 0
    error_count = 0

    for endpoint in endpoints:
        result = test_endpoint(base_url, endpoint)
        results.append(result)

        if result["success"]:
            success_count += 1
        else:
            error_count += 1

    print("\n" + "=" * 60)
    print(f"📊 SUMMARY: {success_count} ✅ success, {error_count} ❌ errors")

    if error_count > 0:
        print(f"\n❌ FAILED ENDPOINTS ({error_count}):")
        for result in results:
            if not result["success"]:
                print(f"  • {result['endpoint']}: {result.get('error', 'Unknown error')}")

    if error_count == 0:
        print("\n🎉 ALL ENDPOINTS WORKING!")
    else:
        print(f"\n⚠️  {error_count} endpoints need attention.")

    # Return error count for script exit code
    return error_count


if __name__ == "__main__":
    error_count = main()
    sys.exit(min(error_count, 1))  # Exit with 1 if any errors, 0 if all good
