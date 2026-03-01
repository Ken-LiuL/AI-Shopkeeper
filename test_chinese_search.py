#!/usr/bin/env python3
"""Test Chinese search URL encoding"""

import urllib.request
import urllib.parse
import json

def test_chinese_search():
    # Test both endpoints with Chinese parameters
    base_url = "https://ai-shopkeeper-kk.fly.dev"
    query = "轮椅"
    
    # URL encode the Chinese text
    encoded_query = urllib.parse.quote(query)
    print(f"Original query: {query}")
    print(f"Encoded query: {encoded_query}")
    
    endpoints = [
        f"/api/knowledge/search?q={encoded_query}",
        f"/api/knowledge/v1/search?q={encoded_query}"
    ]
    
    for endpoint in endpoints:
        full_url = base_url + endpoint
        print(f"\nTesting: {full_url}")
        
        try:
            with urllib.request.urlopen(full_url, timeout=10) as response:
                status = response.getcode()
                data = response.read().decode('utf-8')
                print(f"Status: {status}")
                
                # Try to parse JSON
                try:
                    json_data = json.loads(data)
                    print(f"Response data keys: {list(json_data.keys())}")
                    if 'data' in json_data:
                        print(f"Data length: {len(json_data['data']) if isinstance(json_data['data'], list) else 'not a list'}")
                except:
                    print(f"Response (first 200 chars): {data[:200]}")
                    
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    test_chinese_search()