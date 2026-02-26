"""本地同步脚本 — 抓 QNH 数据后通过 API 推送到 Fly 后端。

Usage: python3 scripts/sync_via_api.py [--from-local]
  默认: 启动 Chrome 抓取最新数据
  --from-local: 跳过抓取，直接上传 data/all_products.json
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FLY_URL = "https://ai-shopkeeper-kk.fly.dev"
SYNC_API_KEY = ""  # 未配置则不需要
DATA_DIR = Path(__file__).parent.parent / "data"
COOKIE_FILE = Path(__file__).parent.parent / "config" / "qnh_cookies.json"
PAGE_SIZE = 20
API_PATH = "/qnh-gw3/api/product/tenant/page-query"
BATCH_SIZE = 100  # 每批上传数量


async def fetch_from_browser() -> list[dict]:
    """启动 Chrome 抓取 QNH SPU 数据。"""
    import nodriver
    import nodriver.cdp.network

    with open(COOKIE_FILE) as f:
        cookies = json.load(f)

    browser = await nodriver.start(
        headless=False,
        browser_args=["--no-first-run", "--no-default-browser-check"],
    )
    page = await browser.get("https://qnh.meituan.com")

    for name, value in cookies.items():
        await page.send(
            nodriver.cdp.network.set_cookie(
                name=str(name), value=str(value), domain=".meituan.com", path="/"
            )
        )
    logger.info("Loaded %d cookies", len(cookies))

    page = await browser.get("https://qnh.meituan.com/#/unifiedGoods/tenant/spu-list")
    logger.info("Waiting for h5guard init (12s)...")
    await page.sleep(12)
    logger.info("Browser ready ✓")

    products = []
    page_no = 1

    while True:
        key = f"__spu_{int(time.time() * 1000)}_{page_no}"
        body = json.dumps({"page": page_no, "pageSize": PAGE_SIZE, "current": page_no})

        js = f"""
            window.{key} = 'pending';
            fetch('{API_PATH}?yodaReady=h5&csecplatform=4&csecversion=4.2.0', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                credentials: 'include',
                body: {body}
            }}).then(r => r.json())
              .then(d => {{ window.{key} = JSON.stringify(d); }})
              .catch(e => {{ window.{key} = JSON.stringify({{_error: true, message: e.message}}); }});
        """
        await page.evaluate(js)
        await page.sleep(3)

        result_str = await page.evaluate(f"window.{key}")
        if result_str == "pending":
            await page.sleep(3)
            result_str = await page.evaluate(f"window.{key}")

        if not result_str or result_str == "pending":
            logger.warning("Page %d: no response, stopping", page_no)
            break

        result = json.loads(result_str)
        if result.get("_error"):
            logger.error("Page %d error: %s", page_no, result.get("message"))
            break

        data = result.get("data", {})
        items = data.get("list", [])
        total = data.get("total", 0)

        if not items:
            break

        products.extend(items)
        logger.info("Page %d: got %d items (total so far: %d/%d)", page_no, len(items), len(products), total)

        if len(products) >= total:
            break
        page_no += 1

    browser.stop()
    logger.info("Fetched %d products total", len(products))

    # Save local backup
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "all_products.json"
    out.write_text(json.dumps(products, ensure_ascii=False, indent=2))
    logger.info("Local backup: %s", out)

    return products


async def upload_to_api(products: list[dict]) -> None:
    """分批上传商品数据到 Fly 后端。"""
    async with httpx.AsyncClient(timeout=60) as client:
        for i in range(0, len(products), BATCH_SIZE):
            batch = products[i : i + BATCH_SIZE]
            payload = {
                "source": "products",
                "data": batch,
            }
            if SYNC_API_KEY:
                payload["api_key"] = SYNC_API_KEY

            resp = await client.post(f"{FLY_URL}/api/sync/ingest", json=payload)
            if resp.status_code == 200:
                result = resp.json()
                logger.info(
                    "Batch %d-%d: uploaded %d records ✓",
                    i, i + len(batch), result.get("records", 0),
                )
            else:
                logger.error("Batch %d-%d failed: %s %s", i, i + len(batch), resp.status_code, resp.text)
                return

    logger.info("✅ All %d products uploaded to %s", len(products), FLY_URL)


async def main():
    from_local = "--from-local" in sys.argv

    if from_local:
        local_file = DATA_DIR / "all_products.json"
        if not local_file.exists():
            logger.error("❌ %s not found", local_file)
            return
        products = json.loads(local_file.read_text())
        logger.info("Loaded %d products from local file", len(products))
    else:
        products = await fetch_from_browser()

    if not products:
        logger.error("No products to upload")
        return

    await upload_to_api(products)


if __name__ == "__main__":
    asyncio.run(main())
