#!/usr/bin/env python3
"""Quick test script to verify the 3 issues are fixed."""

import asyncio
import logging

import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_issues():
    """Test the 3 issues that should be fixed."""

    # Start the server in background
    import subprocess
    import time

    try:
        logger.info("Starting server...")
        proc = subprocess.Popen(
            ["uvicorn", "src.main:app", "--port", "8001"],
            cwd="/Users/pengkun/Dropbox/workspace/ai-store-manager",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(5)  # Give server time to start

        base_url = "http://localhost:8001"

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Test 1: Chat endpoint
            logger.info("Testing chat endpoint...")
            try:
                response = await client.post(
                    f"{base_url}/api/v1/chat",
                    json={"message": "今天销售怎么样", "session_id": "test-session"},
                )
                logger.info(f"Chat endpoint status: {response.status_code}")
                if response.status_code != 200:
                    logger.error(f"Chat endpoint failed: {response.text}")
                else:
                    logger.info("✓ Chat endpoint working")
            except Exception as e:
                logger.error(f"Chat endpoint error: {e}")

            # Test 2: Products list endpoint
            logger.info("Testing products list endpoint...")
            try:
                response = await client.get(f"{base_url}/api/v1/products/list")
                logger.info(f"Products list status: {response.status_code}")
                if response.status_code != 200:
                    logger.error(f"Products list failed: {response.text}")
                else:
                    data = response.json()
                    logger.info(
                        f"✓ Products list working, got {len(data.get('data', []))} products"
                    )
            except Exception as e:
                logger.error(f"Products list error: {e}")

            # Test 3: Alerts endpoint
            logger.info("Testing alerts endpoint...")
            try:
                response = await client.get(f"{base_url}/api/alerts/")
                logger.info(f"Alerts endpoint status: {response.status_code}")
                if response.status_code != 200:
                    logger.error(f"Alerts endpoint failed: {response.text}")
                else:
                    data = response.json()
                    logger.info(
                        f"✓ Alerts endpoint working, got {len(data.get('data', []))} alerts"
                    )
            except Exception as e:
                logger.error(f"Alerts endpoint error: {e}")

    finally:
        if "proc" in locals():
            proc.terminate()
            proc.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(test_issues())
