#!/usr/bin/env python3
"""Quick diagnostic to understand current API responses"""

import json
import urllib.request


def test_endpoint(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            content = response.read().decode("utf-8")
            return json.loads(content)
    except Exception as e:
        return {"error": str(e)}


def main():
    base = "https://ai-shopkeeper-kk.fly.dev"

    # Test key endpoints
    endpoints = [
        "/api/dashboard/overview",
        "/api/competitors/price-comparison",
        "/api/pricing/suggestions",
        "/api/products/recommendations",
    ]

    for endpoint in endpoints:
        print(f"\n=== {endpoint} ===")
        result = test_endpoint(base + endpoint)
        print(json.dumps(result, indent=2, ensure_ascii=False)[:500] + "...")


if __name__ == "__main__":
    main()
