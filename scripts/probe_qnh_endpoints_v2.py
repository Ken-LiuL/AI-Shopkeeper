#!/usr/bin/env python3
"""探测 QNH 未验证的 API 端点 — 用已有的 BrowserClient。"""

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

ENDPOINTS = [
    (
        "store_spu_page",
        "/qnh-gw3/api/product/store/page-query-spu",
        {"page": 1, "pageSize": 3, "poiId": 1175006},
    ),
    (
        "store_spu_page_status",
        "/qnh-gw3/api/product/store/page-query-spu",
        {"page": 1, "pageSize": 3, "poiId": 1175006, "status": 1},
    ),
    ("sku_page", "/qnh-gw3/api/product/tenant/page-query-sku", {"page": 1, "pageSize": 3}),
    ("spu_detail", "/qnh-gw3/api/product/tenant/detail", {"spuId": "1001"}),
    ("spu_detail_num", "/qnh-gw3/api/product/tenant/detail", {"spuId": 1001}),
    (
        "stock_query",
        "/qnh-gw3/api/product/store/stock-query",
        {"poiId": 1175006, "page": 1, "pageSize": 3},
    ),
    ("order_list", "/qnh-gw3/api/order/list", {"page": 1, "pageSize": 3, "poiId": 1175006}),
    ("order_page", "/qnh-gw3/api/order/page-query", {"page": 1, "pageSize": 3}),
    ("inventory_warning", "/qnh-gw3/api/product/store/inventory-warning", {"poiId": 1175006}),
    # goldengateway — sales trend with different params
    (
        "sales_trend_v1",
        "goldengateway_table",
        {
            "viewCode": "homepage_date_trend_list_new",
            "param": {"timeType": "d", "poiIds": "1175006,1221411,1232550", "tenantId": "1011766"},
        },
    ),
    (
        "sales_trend_v2",
        "goldengateway_table",
        {
            "viewCode": "homepage_date_trend_list_new",
            "param": {
                "timeType": "d",
                "poiIds": "1175006,1221411,1232550",
                "tenantId": "1011766",
                "startDate": "20260225",
                "endDate": "20260304",
            },
        },
    ),
    (
        "sales_trend_v3",
        "goldengateway_table",
        {
            "viewCode": "homepage_date_trend_list_new",
            "param": {
                "timeType": "d",
                "poiIds": "1175006",
                "tenantId": "1011766",
                "startDate": "2026-02-25",
                "endDate": "2026-03-04",
            },
        },
    ),
]


async def main():
    from src.sync.browser_client import BrowserClient

    bc = BrowserClient()
    logger.info("初始化浏览器...")
    await bc._start_browser()
    logger.info("浏览器就绪")

    results = {}

    for name, path, body in ENDPOINTS:
        logger.info(
            f"\n{'=' * 60}\n探测: {name}\n  path: {path}\n  body: {json.dumps(body, ensure_ascii=False)[:120]}"
        )

        try:
            if path == "goldengateway_table":
                result = await bc.get_golden_data(
                    view_code=body["viewCode"],
                    param=body.get("param", {}),
                )
            else:
                result = await bc.execute_api(path, method="POST", body=body)

            results[name] = result

            if isinstance(result, dict):
                code = result.get("code", result.get("status", "?"))
                msg = str(result.get("msg", result.get("message", "")))[:80]
                data = result.get("data", {})

                if isinstance(data, dict):
                    keys = list(data.keys())[:10]
                    items = data.get("list", data.get("rows", data.get("records", [])))
                    total = data.get(
                        "total",
                        data.get("totalCount", len(items) if isinstance(items, list) else 0),
                    )
                    logger.info(f"  ✅ code={code} | msg={msg}")
                    logger.info(f"     data_keys={keys} total={total}")

                    if isinstance(items, list) and items:
                        item = items[0]
                        if isinstance(item, dict):
                            item_keys = list(item.keys())[:20]
                            logger.info(f"     item_keys={item_keys}")
                            # 找库存/数量相关字段
                            stock_fields = [
                                k
                                for k in item.keys()
                                if any(
                                    s in k.lower()
                                    for s in [
                                        "stock",
                                        "inventory",
                                        "num",
                                        "count",
                                        "qty",
                                        "available",
                                        "cost",
                                        "purchase",
                                    ]
                                )
                            ]
                            if stock_fields:
                                logger.info(f"     🎯 关键字段: {stock_fields}")
                                for sf in stock_fields:
                                    logger.info(f"        {sf} = {item[sf]}")
                            # 输出完整第一条
                            logger.info(
                                f"     FULL_ITEM: {json.dumps(item, ensure_ascii=False, default=str)[:500]}"
                            )
                elif isinstance(data, list):
                    logger.info(f"  ✅ code={code} | list items={len(data)}")
                    if data:
                        logger.info(
                            f"     FIRST: {json.dumps(data[0], ensure_ascii=False, default=str)[:500]}"
                        )
                else:
                    logger.info(f"  ⚠️ code={code} | msg={msg} | data_type={type(data).__name__}")
            else:
                logger.info(f"  ⚠️ result_type={type(result).__name__}: {str(result)[:200]}")

        except Exception as e:
            logger.error(f"  ❌ {type(e).__name__}: {e}")
            results[name] = {"error": str(e)}

        await asyncio.sleep(1)

    # 保存
    out = ROOT / "data" / "endpoint_probe_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    logger.info(f"\n结果已保存到 {out}")

    await bc.close()


if __name__ == "__main__":
    asyncio.run(main())
