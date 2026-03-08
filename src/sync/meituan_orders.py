"""美团买药订单同步器。

订单历史 API 必须从「全部订单」页面上下文触发（h5guard 签名依赖页面状态），
因此使用 CDP Network.getResponseBody 抓取订单数据，而非直接 fetch。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Any

import nodriver as uc

logger = logging.getLogger(__name__)
DEFAULT_STORE_ID = os.environ.get("DEFAULT_STORE_ID", "30850916")


@dataclass
class OrderSyncResult:
    success: bool = True
    orders_synced: int = 0
    error: str | None = None


@dataclass
class MeituanOrderSyncer:
    """从美团买药抓取订单历史并写入 PostgreSQL。"""

    cookie_path: str = "config/yiyao_cookies.json"
    wm_poi_id: str = DEFAULT_STORE_ID
    pool: Any = None  # asyncpg pool

    async def _load_cookies(self, page: Any) -> None:
        with open(self.cookie_path) as f:
            cookies = json.load(f)
        for c in cookies:
            try:
                await page.send(uc.cdp.network.set_cookie(
                    name=c["name"],
                    value=c["value"],
                    domain=c.get("domain", ".meituan.com"),
                    path=c.get("path", "/"),
                ))
            except Exception:
                pass

    async def sync_orders(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        max_pages: int = 50,
    ) -> OrderSyncResult:
        """同步指定日期范围的订单。默认同步最近 7 天。"""

        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=6)

        result = OrderSyncResult()
        browser = None

        try:
            import os as _os
            _chrome = _os.environ.get("CHROME_EXECUTABLE_PATH", None)
            browser = await uc.start(
                headless=True,
                browser_executable_path=_chrome,
                browser_args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-setuid-sandbox",
                    "--single-process",
                ],
            )
            page = await browser.get("https://yiyao.meituan.com")
            await asyncio.sleep(2)
            await self._load_cookies(page)

            # 启用 CDP 网络监控
            await page.send(uc.cdp.network.enable())

            # 用于捕获订单历史 response
            captured_request_ids: list[str] = []

            def on_response(event: uc.cdp.network.ResponseReceived) -> None:
                if "order/list/page/history" in event.response.url:
                    captured_request_ids.append(event.request_id)

            page.add_handler(uc.cdp.network.ResponseReceived, on_response)

            # 刷新页面使 cookie 生效
            await page.reload()
            await asyncio.sleep(4)

            # 点击「全部订单」进入订单管理页面
            try:
                btn = await page.find("全部订单", best_match=True, timeout=8)
                if btn:
                    await btn.click()
                    logger.info("Clicked 全部订单")
                    await asyncio.sleep(8)
                else:
                    result.success = False
                    result.error = "Cannot find 全部订单 button"
                    return result
            except Exception as e:
                result.success = False
                result.error = f"Click error: {e}"
                return result

            # 第一页自动加载时已触发，获取其 response
            if captured_request_ids:
                body_tuple = await page.send(
                    uc.cdp.network.get_response_body(captured_request_ids[-1])
                )
                text = body_tuple[0] if body_tuple else ""
                if text:
                    first_page = json.loads(text)
                    if first_page.get("code") == 0:
                        orders = self._extract_orders(first_page)
                        await self._save_orders(orders)
                        result.orders_synced += len(orders)
                        logger.info("Page 1: %d orders", len(orders))

                        # 检查是否有更多页
                        page_info = first_page.get("data", {}).get("pageInfo", {})
                        has_next = page_info.get("hasNext", False)
                        next_label = page_info.get("nextLabel", "")

                        # 分页获取剩余
                        page_num = 2
                        while has_next and page_num <= max_pages:
                            captured_request_ids.clear()
                            # 需要在页面里触发下一页加载
                            # 尝试点击"下一页"或滚动加载
                            try:
                                next_btn = await page.find("下一页", best_match=True, timeout=3)
                                if next_btn:
                                    await next_btn.click()
                                    await asyncio.sleep(5)
                            except Exception:
                                # 可能是滚动加载
                                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                await asyncio.sleep(5)

                            if captured_request_ids:
                                body_tuple = await page.send(
                                    uc.cdp.network.get_response_body(captured_request_ids[-1])
                                )
                                text = body_tuple[0] if body_tuple else ""
                                if text:
                                    page_data = json.loads(text)
                                    if page_data.get("code") == 0:
                                        orders = self._extract_orders(page_data)
                                        await self._save_orders(orders)
                                        result.orders_synced += len(orders)
                                        logger.info("Page %d: %d orders", page_num, len(orders))

                                        page_info = page_data.get("data", {}).get("pageInfo", {})
                                        has_next = page_info.get("hasNext", False)
                                    else:
                                        break
                            else:
                                break
                            page_num += 1
                    else:
                        result.success = False
                        result.error = f"API error: {first_page.get('msg', 'unknown')}"
            else:
                result.success = False
                result.error = "No order history request captured"

        except Exception as e:
            result.success = False
            result.error = str(e)
            logger.exception("Order sync failed")
        finally:
            if browser:
                try:
                    browser.stop()
                except Exception:
                    pass

        logger.info(
            "Order sync complete: success=%s, orders=%d, error=%s",
            result.success, result.orders_synced, result.error,
        )
        return result

    def _extract_orders(self, api_response: dict) -> list[dict]:
        """从 API 响应提取订单记录。"""
        orders = []
        order_list = api_response.get("data", {}).get("orderList", [])

        for raw in order_list:
            try:
                common_info = json.loads(raw.get("commonInfo", "{}"))
                order_info = json.loads(raw.get("orderInfo", "{}"))

                order_id = str(common_info.get("wm_order_id_view", ""))
                order_time = datetime.fromtimestamp(common_info.get("order_time", 0))
                order_status = common_info.get("orderStatus", 0)
                day_seq = common_info.get("wm_poi_order_dayseq", 0)

                # 状态映射
                status_map = {
                    4: "completed",
                    8: "completed",  # 8 = 已完成(自动确认)
                    9: "cancelled",
                    7: "refunded",
                }
                status = status_map.get(order_status, f"status_{order_status}")

                # 费用明细
                charge_block = order_info.get("orderChargeBlockBO", {})
                settlement = charge_block.get("settlementItems", [])
                total_price = 0.0
                commission = 0.0
                delivery_fee = 0.0
                merchant_discount = 0.0
                customer_paid = 0.0

                for item in settlement:
                    name = item.get("name", "")
                    price_text = item.get("priceText", "￥0")
                    price_val = float(price_text.replace("￥", "").replace("¥", "").replace(",", "").replace("-", ""))
                    is_negative = "-" in price_text

                    if "小计" in name:
                        total_price = price_val
                    elif "佣金" in name:
                        commission = price_val
                    elif "配送服务费" in name:
                        delivery_fee = price_val
                    elif "活动支出" in name:
                        merchant_discount = price_val
                    elif "实际支付" in name:
                        customer_paid = price_val

                # 商品明细
                food_block = order_info.get("orderFoodBlockBO", {})
                cart_details = food_block.get("cartDetailVOs", [])
                items = []
                for cart in cart_details:
                    for detail in cart.get("details", []):
                        items.append({
                            "name": detail.get("foodName", ""),
                            "quantity": detail.get("count", 1),
                            "price": detail.get("originFoodPrice", ""),
                            "total": detail.get("totalFoodPrice", ""),
                            "real_pay": detail.get("foodRealPayTotalPrice", ""),
                            "food_id": detail.get("foodId", ""),
                        })

                # 用户信息
                user_info = order_info.get("unifiedUserInfo", {})
                recipient_name = user_info.get("recipientName", "")
                # 脱敏：只保留姓
                if recipient_name:
                    recipient_name = recipient_name[0] + "*" * (len(recipient_name) - 1)

                # 基本信息
                basic_info = order_info.get("unifiedBasicInfo", {})

                orders.append({
                    "order_id": order_id,
                    "store_id": self.wm_poi_id,
                    "order_time": order_time,
                    "day_seq": day_seq,
                    "status": status,
                    "total_price": total_price,
                    "commission": commission,
                    "delivery_fee": delivery_fee,
                    "merchant_discount": merchant_discount,
                    "customer_paid": customer_paid,
                    "items": items,
                    "item_count": len(items),
                    "recipient_name": recipient_name,
                    "poi_name": basic_info.get("wmPoiName", ""),
                })
            except Exception as e:
                logger.warning("Failed to parse order: %s", e)
                continue

        return orders

    async def _save_orders(self, orders: list[dict]) -> None:
        """写入 orders 表。单条失败不中断整个批次。"""
        if not orders or not self.pool:
            return

        saved = 0
        failed = 0
        async with self.pool.acquire() as conn:
            for order in orders:
                try:
                    await conn.execute(
                        """
                        INSERT INTO orders (
                            order_id, store_id, customer_name, total_amount, status,
                            items, order_time, order_date, commission, delivery_fee,
                            merchant_discount, customer_paid, day_seq, created_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
                        ON CONFLICT (order_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            total_amount = EXCLUDED.total_amount,
                            items = EXCLUDED.items,
                            customer_paid = EXCLUDED.customer_paid,
                            commission = EXCLUDED.commission
                        """,
                        order["order_id"],
                        order["store_id"],
                        order["recipient_name"],
                        order["total_price"],
                        order["status"],
                        json.dumps({
                            "products": order["items"],
                        }, ensure_ascii=False),
                        order["order_time"],
                        order["order_time"].date(),
                        order["commission"],
                        order["delivery_fee"],
                        order["merchant_discount"],
                        order["customer_paid"],
                        order["day_seq"],
                    )
                    saved += 1
                except Exception as exc:
                    logger.error("Failed to save order %s: %s", order.get("order_id"), exc)
                    failed += 1

        logger.info("Saved %d/%d orders to database (%d failed)", saved, len(orders), failed)
