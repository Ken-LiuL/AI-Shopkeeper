"""本地数据同步 daemon — 从 QNH 抓数据推送到 Render 后端。

使用 nodriver 启动真实 Chrome，绕过 h5guard 反爬，
抓取数据后 POST 到后端 /api/sync/ingest 接口。

用法:
    BACKEND_URL=https://ai-shopkeeper-1dl4.onrender.com \
    SYNC_API_KEY=xxx \
    python scripts/sync_daemon.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime

import aiohttp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sync_daemon")

BACKEND_URL = os.environ.get("BACKEND_URL", "https://ai-shopkeeper-1dl4.onrender.com")
SYNC_API_KEY = os.environ.get("SYNC_API_KEY", "")
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", "300"))  # 5 分钟

# viewCode → source 映射
VIEW_CODES = {
    "homepage_hotsale_goods_rank_table_view_new": "products",
    "customer_consume_rank_table_view_new": "customers",
    "homepage_not_erp_poi_rank_table_view": "metrics",
    "homepage_date_trend_list_new": "traffic",
    "homepage_data_overview_view_not_erp": "metrics",  # complexModule
    "homepage_channel_distribute_table_view_new": "channels",
}

# 直接 cookie 访问的 API
DIRECT_APIS = {
    "products_category": {
        "source": "products",
        "url": "/api/v1/merchant/storeCategory/queryAll",
        "method": "GET",
    },
    "channels_list": {
        "source": "channels",
        "url": "/api/v1/tenant/channels",
        "method": "GET",
    },
    "workbench": {
        "source": "orders",
        "url": "/workbench/b/dashboard/query/upcoming",
        "method": "GET",
    },
}

POI_IDS = [1232550, 1221411, 1175006]


async def push_to_backend(source: str, data: list[dict]) -> dict:
    """POST 数据到后端 ingest API。"""
    async with aiohttp.ClientSession() as session:
        payload = {
            "source": source,
            "data": data,
            "synced_at": datetime.now(UTC).isoformat(),
            "api_key": SYNC_API_KEY,
        }
        async with session.post(
            f"{BACKEND_URL}/api/sync/ingest",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            result = await resp.json()
            return result


async def fetch_golden_data(
    page, view_code: str, api_path: str, date_type: str = "d"
) -> list[dict]:
    """通过浏览器 evaluate 调用 goldengateway API。"""
    import time

    today = datetime.now().strftime("%Y%m%d")
    key = f"__sync_{int(time.time() * 1000)}"

    body = json.dumps(
        {
            "viewCode": view_code,
            "param": {
                "poiIds": POI_IDS,
                "channelIds": [],
                "dateType": date_type,
                "beginDate": today,
                "endDate": today,
                "page": 1,
                "pageSize": 100,
                "order": "",
                "isSelectAllPoi": False,
            },
        }
    )

    # body 需要作为字符串传给 fetch，转义单引号
    body_escaped = body.replace("'", "\\'")
    js = f"""
        window.{key} = 'pending';
        fetch('{api_path}?yodaReady=h5&csecplatform=4&csecversion=4.2.0', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            credentials: 'include',
            body: '{body_escaped}'
        }}).then(r => r.json())
          .then(d => {{ window.{key} = JSON.stringify(d); }})
          .catch(e => {{ window.{key} = JSON.stringify({{_error: true, message: e.message}}); }});
    """
    await page.evaluate(js)
    await page.sleep(5)

    result_str = await page.evaluate(f"window.{key}")
    if result_str == "pending":
        await page.sleep(5)
        result_str = await page.evaluate(f"window.{key}")

    if not result_str or result_str == "pending":
        return []

    data = json.loads(result_str)
    if data.get("_error"):
        logger.warning("API error for %s: %s", view_code, data.get("message"))
        return []

    if data.get("code") != 0:
        logger.warning("API code=%s for %s: %s", data.get("code"), view_code, data.get("msg"))
        return []

    # 提取 dataList 或 valueList
    payload_data = data.get("data", {})
    return payload_data.get("dataList") or payload_data.get("valueList") or [payload_data]


async def fetch_direct_api(page, name: str, config: dict) -> list[dict]:
    """通过浏览器 evaluate 调用可 cookie 直接访问的 API。"""
    import time

    key = f"__sync_{int(time.time() * 1000)}"
    url = config["url"]
    method = config.get("method", "GET")

    if method == "GET":
        js = f"""
            window.{key} = 'pending';
            fetch('{url}?yodaReady=h5&csecplatform=4&csecversion=4.2.0', {{credentials: 'include'}})
                .then(r => r.json())
                .then(d => {{ window.{key} = JSON.stringify(d); }})
                .catch(e => {{ window.{key} = JSON.stringify({{_error: true, message: e.message}}); }});
        """
    else:
        js = f"""
            window.{key} = 'pending';
            fetch('{url}?yodaReady=h5&csecplatform=4&csecversion=4.2.0', {{
                method: 'POST', headers: {{'Content-Type': 'application/json'}},
                credentials: 'include', body: '{{}}'
            }}).then(r => r.json())
              .then(d => {{ window.{key} = JSON.stringify(d); }})
              .catch(e => {{ window.{key} = JSON.stringify({{_error: true, message: e.message}}); }});
        """

    await page.evaluate(js)
    await page.sleep(3)
    result_str = await page.evaluate(f"window.{key}")
    if not result_str or result_str == "pending":
        return []

    data = json.loads(result_str)
    if data.get("code") != 0:
        logger.warning("Direct API %s: code=%s", name, data.get("code"))
        return []

    return [data.get("data", {})]


async def sync_round(page) -> None:
    """执行一轮完整同步。"""
    logger.info("=" * 50)
    logger.info("开始同步轮次 %s", datetime.now().strftime("%H:%M:%S"))

    # 1. goldengateway APIs（需要 mtgsig，通过浏览器）
    golden_apis = {
        "homepage_hotsale_goods_rank_table_view_new": "/goldengateway/empower/generic/table/query",
        "customer_consume_rank_table_view_new": "/goldengateway/empower/generic/table/query",
        "homepage_not_erp_poi_rank_table_view": "/goldengateway/empower/generic/table/query",
        "homepage_date_trend_list_new": "/goldengateway/empower/generic/table/query",
        "homepage_channel_distribute_table_view_new": "/goldengateway/empower/homepage/channelDistributeList",
    }

    # complexModule 单独处理
    overview_api = "/goldengateway/empower/complexModule/queryTable"

    for vc, api_path in golden_apis.items():
        source = VIEW_CODES[vc]
        try:
            data = await fetch_golden_data(page, vc, api_path)
            if data:
                result = await push_to_backend(source, data)
                logger.info(
                    "✅ %s (%s): pushed %d records → %s", vc[:30], source, len(data), result
                )
            else:
                logger.info("⏭️  %s: no data", vc[:30])
        except Exception as e:
            logger.error("❌ %s: %s", vc[:30], e)

    # overview (complexModule)
    try:
        data = await fetch_golden_data(page, "homepage_data_overview_view_not_erp", overview_api)
        if data:
            result = await push_to_backend("metrics", data)
            logger.info("✅ overview → metrics: %d records → %s", len(data), result)
    except Exception as e:
        logger.error("❌ overview: %s", e)

    # 2. Direct APIs
    for name, config in DIRECT_APIS.items():
        try:
            data = await fetch_direct_api(page, name, config)
            if data:
                result = await push_to_backend(config["source"], data)
                logger.info("✅ %s → %s: pushed → %s", name, config["source"], result)
        except Exception as e:
            logger.error("❌ %s: %s", name, e)

    logger.info("同步轮次完成")


async def main() -> None:
    import nodriver

    logger.info("🚀 启动同步 daemon")
    logger.info("   Backend: %s", BACKEND_URL)
    logger.info("   Interval: %ds", SYNC_INTERVAL)

    # 启动 Chrome
    browser = await nodriver.start(
        headless=os.environ.get("HEADLESS", "false").lower() == "true",
        no_sandbox=True,
        browser_args=["--no-first-run", "--no-default-browser-check"],
    )

    # 加载 cookies
    cookies_path = os.path.join(os.path.dirname(__file__), "..", "config", "qnh_cookies.json")
    page = await browser.get("https://qnh.meituan.com")
    await page.sleep(2)
    with open(cookies_path) as f:
        raw_cookies = json.load(f)
    # Support both dict format and nodriver list format
    if isinstance(raw_cookies, list):
        cookies = {item["name"]: item["value"] for item in raw_cookies if "name" in item}
    else:
        cookies = raw_cookies
    for name, value in cookies.items():
        await page.send(
            nodriver.cdp.network.set_cookie(
                name=name, value=str(value), domain=".meituan.com", path="/"
            )
        )
    logger.info("已加载 %d 个 cookies", len(cookies))

    # 重新导航让 cookies 生效 + h5guard 初始化
    page = await browser.get("https://qnh.meituan.com/home.html")
    logger.info("等待页面加载和 h5guard 初始化...")
    await page.sleep(15)

    # 验证登录
    title = await page.evaluate("document.title")
    logger.info("页面标题: %s", title)
    await page.evaluate("""
        window.__lc = 'pending';
        fetch('/api/v1/isLogined?yodaReady=h5&csecplatform=4&csecversion=4.2.0', {credentials:'include'})
            .then(r=>r.json()).then(d=>{window.__lc=JSON.stringify(d)})
            .catch(e=>{window.__lc=JSON.stringify({err:e.message})});
    """)
    await page.sleep(3)
    login = await page.evaluate("window.__lc")
    logger.info("登录检查: %s", login)
    logger.info("✅ 浏览器就绪")

    try:
        while True:
            await sync_round(page)
            logger.info("等待 %d 秒...", SYNC_INTERVAL)
            await asyncio.sleep(SYNC_INTERVAL)
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    finally:
        browser.stop()
        logger.info("Daemon 已关闭 ✓")


if __name__ == "__main__":
    asyncio.run(main())
