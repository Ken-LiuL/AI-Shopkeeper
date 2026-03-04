#!/usr/bin/env python3
"""探测 QNH 未验证的 API 端点，寻找库存/订单数据。

通过 nodriver 浏览器在 QNH 页面上下文中执行 fetch，
绕过 h5guard 签名。
"""

import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
COOKIE_FILE = ROOT / "config" / "qnh_cookies.json"

# 要探测的端点
ENDPOINTS_TO_PROBE = [
    # 门店商品列表 — 可能含库存
    {
        "name": "store_spu_page",
        "url": "https://qnh.meituan.com/qnh-gw3/api/product/store/page-query-spu",
        "method": "POST",
        "body": {"page": 1, "pageSize": 5, "poiId": 1175006},
    },
    # 门店商品列表 — 不同参数格式
    {
        "name": "store_spu_page_v2",
        "url": "https://qnh.meituan.com/qnh-gw3/api/product/store/page-query-spu",
        "method": "POST",
        "body": {"page": 1, "pageSize": 5, "poiId": 1175006, "status": 1},
    },
    # SKU 列表 — 可能含库存
    {
        "name": "sku_page",
        "url": "https://qnh.meituan.com/qnh-gw3/api/product/tenant/page-query-sku",
        "method": "POST",
        "body": {"page": 1, "pageSize": 5},
    },
    # SPU 详情 — 可能含库存+成本价
    {
        "name": "spu_detail_1001",
        "url": "https://qnh.meituan.com/qnh-gw3/api/product/tenant/detail",
        "method": "POST",
        "body": {"spuId": "1001"},
    },
    # SPU 详情 — 用数字 ID
    {
        "name": "spu_detail_numeric",
        "url": "https://qnh.meituan.com/qnh-gw3/api/product/tenant/detail",
        "method": "POST",
        "body": {"spuId": 1001},
    },
    # 库存查询（猜测端点）
    {
        "name": "stock_query",
        "url": "https://qnh.meituan.com/qnh-gw3/api/product/store/stock-query",
        "method": "POST",
        "body": {"poiId": 1175006, "page": 1, "pageSize": 5},
    },
    # 订单列表（猜测端点）
    {
        "name": "order_list",
        "url": "https://qnh.meituan.com/qnh-gw3/api/order/list",
        "method": "POST",
        "body": {"page": 1, "pageSize": 5, "poiId": 1175006},
    },
    # 订单列表 v2
    {
        "name": "order_page",
        "url": "https://qnh.meituan.com/qnh-gw3/api/order/page-query",
        "method": "POST",
        "body": {"page": 1, "pageSize": 5},
    },
    # goldengateway 销售趋势（修复参数）
    {
        "name": "sales_trend_fix1",
        "url": "https://qnh.meituan.com/goldengateway/empower/generic/table/query",
        "method": "POST",
        "body": {
            "viewCode": "homepage_date_trend_list_new",
            "param": {
                "timeType": "d",
                "poiIds": "1175006,1221411,1232550",
                "tenantId": "1011766",
            },
        },
    },
    # goldengateway 销售趋势（不同参数）
    {
        "name": "sales_trend_fix2",
        "url": "https://qnh.meituan.com/goldengateway/empower/generic/table/query",
        "method": "POST",
        "body": {
            "viewCode": "homepage_date_trend_list_new",
            "param": {
                "timeType": "d",
                "poiIds": "1175006,1221411,1232550",
                "tenantId": "1011766",
                "startDate": "20260225",
                "endDate": "20260304",
            },
        },
    },
    # 库存盘点/预警相关
    {
        "name": "inventory_warning",
        "url": "https://qnh.meituan.com/qnh-gw3/api/product/store/inventory-warning",
        "method": "POST",
        "body": {"poiId": 1175006, "page": 1, "pageSize": 5},
    },
]


async def main():
    import nodriver as uc

    logger.info("启动 nodriver 浏览器...")
    browser = await uc.start(headless=False)
    page = await browser.get("https://qnh.meituan.com")

    # 加载 cookies via CDP
    if COOKIE_FILE.exists():
        cookies = json.loads(COOKIE_FILE.read_text())
        import nodriver.cdp.network as network

        for c in cookies:
            await page.send(
                network.set_cookie(
                    name=c["name"],
                    value=c["value"],
                    domain=c.get("domain", ".meituan.com"),
                    path=c.get("path", "/"),
                )
            )
        logger.info(f"已加载 {len(cookies)} 个 cookies")

    # 导航到 QNH 首页等 h5guard 初始化
    await page.get("https://qnh.meituan.com/")
    await asyncio.sleep(8)
    logger.info("浏览器初始化完成")

    results = {}
    for ep in ENDPOINTS_TO_PROBE:
        name = ep["name"]
        url = ep["url"]
        body = json.dumps(ep["body"])
        logger.info(f"\n{'=' * 60}\n探测: {name}\n  URL: {url}\n  Body: {body[:100]}")

        try:
            js = f"""
            (async () => {{
                try {{
                    const resp = await fetch("{url}", {{
                        method: "POST",
                        headers: {{"Content-Type": "application/json"}},
                        body: JSON.stringify({body}),
                        credentials: "include"
                    }});
                    const status = resp.status;
                    const text = await resp.text();
                    let data = null;
                    try {{ data = JSON.parse(text); }} catch(e) {{}}
                    return JSON.stringify({{status, data, text: text.substring(0, 500)}});
                }} catch(e) {{
                    return JSON.stringify({{error: e.message}});
                }}
            }})()
            """
            result_raw = await page.evaluate(js)
            result_str = result_raw if isinstance(result_raw, str) else json.dumps(result_raw)
            result = json.loads(result_str)
            results[name] = result

            status = result.get("status", "?")
            if result.get("error"):
                logger.warning(f"  ❌ Error: {result['error']}")
            elif result.get("data"):
                data = result["data"]
                code = data.get("code", data.get("status", "?"))
                msg = data.get("msg", data.get("message", ""))[:80]
                # 检查是否有有用数据
                inner = data.get("data", {})
                if isinstance(inner, dict):
                    keys = list(inner.keys())[:10]
                    count = inner.get(
                        "total",
                        inner.get("totalCount", len(inner.get("list", inner.get("rows", [])))),
                    )
                    logger.info(f"  ✅ HTTP {status} | code={code} | msg={msg}")
                    logger.info(f"     keys={keys} count={count}")
                    # 输出第一条数据的字段
                    items = inner.get("list", inner.get("rows", inner.get("records", [])))
                    if items and isinstance(items, list) and items:
                        item_keys = list(items[0].keys()) if isinstance(items[0], dict) else []
                        logger.info(f"     item_keys={item_keys[:15]}")
                        # 检查库存相关字段
                        stock_fields = [
                            k
                            for k in item_keys
                            if any(
                                s in k.lower()
                                for s in ["stock", "inventory", "num", "count", "qty", "available"]
                            )
                        ]
                        if stock_fields:
                            logger.info(f"     🎯 库存字段发现! {stock_fields}")
                            for sf in stock_fields:
                                logger.info(f"        {sf} = {items[0][sf]}")
                elif isinstance(inner, list):
                    logger.info(f"  ✅ HTTP {status} | code={code} | items={len(inner)}")
                else:
                    logger.info(f"  ⚠️ HTTP {status} | code={code} | msg={msg}")
            else:
                logger.info(f"  ⚠️ HTTP {status} | raw: {result.get('text', '')[:100]}")

        except Exception as e:
            logger.error(f"  ❌ Exception: {e}")
            results[name] = {"error": str(e)}

        await asyncio.sleep(1)  # 避免限流

    # 保存结果
    out = ROOT / "data" / "endpoint_probe_results.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    logger.info(f"\n结果已保存到 {out}")

    browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
