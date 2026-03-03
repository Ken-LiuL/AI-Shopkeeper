#!/usr/bin/env python3
"""探索 QNH 中所有可能的竞品/行业对标 API。

目标：
1. 查询 homepage_trade_compare_table_view_new (行业对标)
2. 尝试其他可能的 viewCode（竞品分析、价格对比等）
3. 探索 complexModule 的更多可能性
4. 记录所有返回数据的结构

Usage:
    python scripts/explore_qnh_competitor_apis.py [--dry-run]
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.sync.browser_client import BrowserClient
from src.sync.qnh_client import (
    QNHClient,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "1011766"
DEFAULT_POI_IDS = [1175006, 1221411, 1232550]

# 已知的 viewCode
KNOWN_VIEW_CODES = [
    "homepage_hotsale_goods_rank_table_view_new",  # 热销商品排行
    "customer_consume_rank_table_view_new",  # 消费排行
    "homepage_not_erp_poi_rank_table_view",  # 门店排行
    "homepage_date_trend_list_new",  # 趋势分析
    "homepage_trade_compare_table_view_new",  # 行业对标 ← 重点！
    "homepage_data_overview_view_not_erp",  # 数据概览
    "homepage_channel_distribute_table_view_new",  # 渠道分布
]

# 猜测可能存在的竞品相关 viewCode
GUESS_VIEW_CODES = [
    # 竞品相关
    "competitor_analysis_table_view",
    "competitor_price_compare_table_view",
    "competitor_rank_table_view",
    "competitor_poi_rank_table_view",
    "competitor_goods_compare_table_view",
    "industry_competitor_table_view",
    "market_competitor_analysis_view",
    "trade_competitor_table_view",
    # 行业相关
    "trade_analysis_table_view",
    "trade_compare_table_view",
    "industry_analysis_table_view",
    "industry_rank_table_view",
    "industry_price_table_view",
    "market_analysis_table_view",
    "market_price_compare_view",
    # 价格相关
    "goods_price_compare_table_view",
    "price_analysis_table_view",
    "price_trend_table_view",
    "price_monitor_table_view",
    # 周边门店
    "nearby_poi_rank_table_view",
    "nearby_store_compare_table_view",
    "area_poi_rank_table_view",
    "region_poi_compare_table_view",
    # 品类分析
    "category_analysis_table_view",
    "category_rank_table_view",
    "category_compare_table_view",
    "goods_category_rank_table_view",
    # 其他
    "homepage_trade_compare_table_view",  # 无 _new 后缀版本
    "homepage_competitor_table_view",
    "homepage_market_analysis_view",
    "homepage_industry_rank_view",
    "homepage_area_compare_view",
]

OUTPUT_DIR = ROOT_DIR / "data" / "qnh_api_exploration"


async def explore_view_code(client: QNHClient, view_code: str, date_type: str = "w") -> dict | None:
    """尝试查询一个 viewCode，返回结果或 None。"""
    # 用周数据，行业对标通常只有周/月
    today = date.today()
    # 上周
    end = today - timedelta(days=today.weekday() + 1)  # 上周日
    start = end - timedelta(days=6)  # 上周一

    try:
        resp = await client.golden_query(
            view_code=view_code,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            date_type=date_type,
            page=1,
            page_size=50,
        )
        code = resp.get("code")
        if code == 0:
            data = resp.get("data", {})
            if data:
                logger.info("✅ %s 返回数据！", view_code)
                return resp
            else:
                logger.info("⚠️ %s code=0 但 data 为空", view_code)
                return resp
        else:
            msg = resp.get("msg", "")
            logger.info("❌ %s code=%s msg=%s", view_code, code, msg[:100])
            return None
    except Exception as e:
        logger.info("❌ %s 异常: %s", view_code, str(e)[:100])
        return None


async def explore_complex_module(client: QNHClient, view_code: str) -> dict | None:
    """尝试 complexModule/queryTable 查询。"""
    today = date.today()
    end = today - timedelta(days=today.weekday() + 1)
    start = end - timedelta(days=6)

    try:
        resp = await client.golden_complex_query(
            view_code=view_code,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            date_type="w",
        )
        code = resp.get("code")
        if code == 0:
            logger.info("✅ complexModule %s 返回数据！", view_code)
            return resp
        else:
            logger.info("❌ complexModule %s code=%s", view_code, code)
            return None
    except Exception as e:
        logger.info("❌ complexModule %s 异常: %s", view_code, str(e)[:100])
        return None


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = {}

    async with QNHClient(tenant_id=DEFAULT_TENANT_ID, poi_ids=DEFAULT_POI_IDS) as client:
        # 1. 先查已知的行业对标
        logger.info("=" * 60)
        logger.info("阶段 1: 查询已知 viewCode (重点: 行业对标)")
        logger.info("=" * 60)

        for vc in KNOWN_VIEW_CODES:
            # generic table query
            resp = await explore_view_code(client, vc, date_type="w")
            if resp:
                results[f"generic_{vc}"] = resp
            await asyncio.sleep(1)

            # 也尝试 complexModule
            resp2 = await explore_complex_module(client, vc)
            if resp2 and resp2 != resp:
                results[f"complex_{vc}"] = resp2
            await asyncio.sleep(1)

        # 2. 探索猜测的 viewCode
        logger.info("=" * 60)
        logger.info("阶段 2: 探索猜测的竞品 viewCode")
        logger.info("=" * 60)

        for vc in GUESS_VIEW_CODES:
            resp = await explore_view_code(client, vc, date_type="w")
            if resp and resp.get("code") == 0:
                results[f"guess_{vc}"] = resp
            await asyncio.sleep(0.8)

        # 3. 探索 QNH 前端页面找更多 API
        logger.info("=" * 60)
        logger.info("阶段 3: 通过浏览器探索 QNH 页面中的 API 调用")
        logger.info("=" * 60)

        browser = await BrowserClient.get_instance()
        await browser.ensure_ready()

        # 在浏览器中执行 JS，拦截所有 fetch/XHR 请求
        intercept_js = r"""
        (function() {
            window.__qnh_api_calls = [];

            // 拦截 fetch
            const origFetch = window.fetch;
            window.fetch = function(...args) {
                const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
                const body = args[1]?.body || '';
                window.__qnh_api_calls.push({
                    type: 'fetch',
                    url: url,
                    body: typeof body === 'string' ? body : '',
                    time: Date.now()
                });
                return origFetch.apply(this, args);
            };

            // 拦截 XMLHttpRequest
            const origOpen = XMLHttpRequest.prototype.open;
            const origSend = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function(method, url) {
                this.__url = url;
                this.__method = method;
                return origOpen.apply(this, arguments);
            };
            XMLHttpRequest.prototype.send = function(body) {
                window.__qnh_api_calls.push({
                    type: 'xhr',
                    url: this.__url || '',
                    method: this.__method || '',
                    body: typeof body === 'string' ? body : '',
                    time: Date.now()
                });
                return origSend.apply(this, arguments);
            };

            return 'interceptor installed';
        })()
        """

        page = browser._page
        if page:
            try:
                await page.evaluate(intercept_js)
                logger.info("✅ API 拦截器已安装")

                # 导航到可能的竞品分析页面
                competitor_pages = [
                    "https://qnh.meituan.com/home.html#/analysis/trade",
                    "https://qnh.meituan.com/home.html#/analysis/competitor",
                    "https://qnh.meituan.com/home.html#/analysis/industry",
                    "https://qnh.meituan.com/home.html#/analysis/market",
                    "https://qnh.meituan.com/home.html#/analysis",
                    "https://qnh.meituan.com/home.html#/competitor",
                    "https://qnh.meituan.com/home.html#/market",
                    "https://qnh.meituan.com/home.html#/trade",
                ]

                for url in competitor_pages:
                    try:
                        await page.get(url)
                        await asyncio.sleep(3)
                        # 获取拦截到的 API 调用
                        calls = await page.evaluate("window.__qnh_api_calls || []")
                        if calls:
                            logger.info("📡 %s 触发了 %d 个 API 调用:", url, len(calls))
                            for call in calls:
                                api_url = call.get("url", "")
                                if "goldengateway" in api_url or "competitor" in api_url.lower():
                                    logger.info("  🎯 %s", api_url)
                                    body = call.get("body", "")
                                    if body:
                                        try:
                                            parsed = json.loads(body)
                                            logger.info(
                                                "     Body: %s",
                                                json.dumps(parsed, ensure_ascii=False)[:200],
                                            )
                                        except Exception:
                                            pass
                    except Exception as e:
                        logger.debug("页面 %s 加载失败: %s", url, str(e)[:50])
                    await asyncio.sleep(1)

            except Exception as e:
                logger.warning("浏览器探索失败: %s", e)

    # 保存结果
    output_file = OUTPUT_DIR / "exploration_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        # 只保存有数据的结果
        filtered = {}
        for key, val in results.items():
            if val and val.get("code") == 0:
                filtered[key] = val
        json.dump(filtered, f, ensure_ascii=False, indent=2, default=str)

    logger.info("=" * 60)
    logger.info("探索完成！有效结果 %d 个，保存到 %s", len(filtered), output_file)
    logger.info("=" * 60)

    # 打印摘要
    for key, val in filtered.items():
        data = val.get("data", {})
        if isinstance(data, dict):
            for list_key in ("dataList", "valueList", "list", "records"):
                items = data.get(list_key)
                if isinstance(items, list) and items:
                    logger.info(
                        "  %s: %d 条, 字段: %s",
                        key,
                        len(items),
                        list(items[0].keys())[:10] if items else [],
                    )
                    break
            else:
                logger.info("  %s: data keys=%s", key, list(data.keys())[:10])
        else:
            logger.info("  %s: data type=%s", key, type(data).__name__)


if __name__ == "__main__":
    asyncio.run(main())
