"""美团 IM 聊天记录爬取 — 通过拦截页面自身的网络请求获取数据

策略：不主动调 API，而是在页面上下文中拦截/hook fetch/XHR，
当用户（自动模拟）点击会话时，页面自己会调 neixin API 拉消息，
我们拦截这些响应收集数据。
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import nodriver
import nodriver.cdp.network
import nodriver.cdp.runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COOKIE_FILE = Path(__file__).parent.parent / "config" / "qnh_cookies.json"
OUTPUT_DIR = Path(__file__).parent.parent / "data"


async def init_browser():
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
    page = await browser.get("https://qnh.meituan.com/home.html")
    await page.sleep(10)
    logger.info(f"Loaded {len(cookies)} cookies, h5guard init done")
    return browser, page


async def evaluate_js(page, js_code: str) -> str | None:
    result = await page.send(
        nodriver.cdp.runtime.evaluate(
            expression=js_code,
            await_promise=True,
            return_by_value=True,
        )
    )
    if isinstance(result, tuple):
        remote_obj, exc = result
        if exc:
            logger.error(f"JS Exception: {exc}")
            return None
        return remote_obj.value if remote_obj else None
    return result.value if hasattr(result, "value") else None


async def main():
    logger.info("=== 美团 IM 聊天记录爬取 (拦截模式) ===")
    browser, page = await init_browser()

    try:
        # Navigate to IM page
        logger.info("Navigating to IM page...")
        page = await browser.get("https://qnh.meituan.com/#/medCrm/wb/todo/im?_s_layout_hidden_=1")
        await page.sleep(8)

        # Inject JS hook to intercept all fetch/XHR responses
        logger.info("Injecting network interceptor...")
        await evaluate_js(
            page,
            """
            (() => {
                window.__im_captured = [];

                // Hook fetch
                const origFetch = window.fetch;
                window.fetch = async function(...args) {
                    const resp = await origFetch.apply(this, args);
                    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
                    if (url.includes('neixin.cn') || url.includes('dialog') || url.includes('chatting') || url.includes('history') || url.includes('chatlist') || url.includes('records')) {
                        try {
                            const clone = resp.clone();
                            const text = await clone.text();
                            window.__im_captured.push({
                                url: url,
                                status: resp.status,
                                body: text.substring(0, 10000),
                                timestamp: Date.now()
                            });
                        } catch(e) {}
                    }
                    return resp;
                };

                // Hook XMLHttpRequest
                const origOpen = XMLHttpRequest.prototype.open;
                const origSend = XMLHttpRequest.prototype.send;
                XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                    this._url = url;
                    return origOpen.call(this, method, url, ...rest);
                };
                XMLHttpRequest.prototype.send = function(...args) {
                    this.addEventListener('load', function() {
                        const url = this._url || '';
                        if (url.includes('neixin.cn') || url.includes('dialog') || url.includes('chatting') || url.includes('history') || url.includes('chatlist') || url.includes('records')) {
                            window.__im_captured.push({
                                url: url,
                                status: this.status,
                                body: this.responseText.substring(0, 10000),
                                timestamp: Date.now()
                            });
                        }
                    });
                    return origSend.apply(this, args);
                };

                return 'interceptor installed';
            })()
        """,
        )
        logger.info("Interceptor installed ✅")

        # Wait for initial page load API calls
        await page.sleep(5)

        # Check what we captured so far
        captured = await evaluate_js(page, "JSON.stringify(window.__im_captured)")
        initial_data = json.loads(captured) if captured else []
        logger.info(f"Initial capture: {len(initial_data)} requests")
        for item in initial_data:
            logger.info(
                f"  {item['url'][:100]} -> {item['status']}, {len(item.get('body', ''))} bytes"
            )

        # Now try to click on conversation items to trigger message loading
        logger.info("Looking for conversation items to click...")

        # Find clickable conversation items
        conv_count_raw = await evaluate_js(
            page,
            """
            (() => {
                // Try various selectors for conversation list items
                const selectors = [
                    '.dialog-list-item',
                    '.conversation-item',
                    '.chat-item',
                    '.im-chat-item',
                    '[class*="dialog"][class*="item"]',
                    '[class*="chat"][class*="item"]',
                    '[class*="conversation"]',
                    '[class*="session"][class*="item"]',
                    '.im-sidebar li',
                    '.chat-list li',
                ];

                for (const sel of selectors) {
                    const items = document.querySelectorAll(sel);
                    if (items.length > 0) {
                        return JSON.stringify({
                            selector: sel,
                            count: items.length,
                            texts: Array.from(items).slice(0, 5).map(el => el.textContent?.trim()?.substring(0, 100))
                        });
                    }
                }

                // Fallback: dump page structure
                const body = document.body;
                const allElements = body.querySelectorAll('*');
                const classNames = new Set();
                allElements.forEach(el => {
                    if (el.className && typeof el.className === 'string') {
                        el.className.split(' ').forEach(cls => {
                            if (cls.match(/dialog|chat|im|conversation|session|message|record/i)) {
                                classNames.add(cls);
                            }
                        });
                    }
                });

                return JSON.stringify({
                    selector: null,
                    count: 0,
                    relevantClasses: Array.from(classNames).slice(0, 30),
                    bodyText: document.body.innerText?.substring(0, 1000)
                });
            })()
        """,
        )

        conv_info = json.loads(conv_count_raw) if conv_count_raw else {}
        logger.info(f"Conversation items: {json.dumps(conv_info, ensure_ascii=False)[:500]}")

        if conv_info.get("selector") and conv_info.get("count", 0) > 0:
            selector = conv_info["selector"]
            count = min(conv_info["count"], 20)
            logger.info(f"Found {count} conversations with selector: {selector}")

            for i in range(count):
                logger.info(f"Clicking conversation {i + 1}/{count}...")
                await evaluate_js(
                    page,
                    f"""
                    (() => {{
                        const items = document.querySelectorAll('{selector}');
                        if (items[{i}]) {{
                            items[{i}].click();
                            return 'clicked';
                        }}
                        return 'not found';
                    }})()
                """,
                )
                await page.sleep(3)  # Wait for messages to load

                # Collect captured data
                new_captured = await evaluate_js(page, "JSON.stringify(window.__im_captured)")
                new_data = json.loads(new_captured) if new_captured else []
                logger.info(f"  Captured so far: {len(new_data)} requests")
        else:
            logger.warning("No conversation items found. Dumping page for analysis.")

        # Final collection
        final_raw = await evaluate_js(page, "JSON.stringify(window.__im_captured)")
        all_captured = json.loads(final_raw) if final_raw else []

        logger.info(f"\n=== Final Results: {len(all_captured)} captured requests ===")

        # Parse and structure conversations
        conversations = []
        for item in all_captured:
            try:
                body = json.loads(item.get("body", "{}"))
                conversations.append(
                    {
                        "url": item["url"],
                        "status": item["status"],
                        "data": body,
                        "timestamp": item["timestamp"],
                    }
                )
            except json.JSONDecodeError:
                conversations.append(
                    {
                        "url": item["url"],
                        "status": item["status"],
                        "raw_body": item.get("body", "")[:2000],
                        "timestamp": item["timestamp"],
                    }
                )

        # Save
        output = {
            "scraped_at": datetime.now().isoformat(),
            "method": "intercept",
            "total_captured": len(all_captured),
            "page_info": conv_info,
            "captured_requests": conversations,
        }

        output_file = OUTPUT_DIR / "im_conversations.json"
        output_file.parent.mkdir(exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Saved to {output_file}")

        # Also save raw captured for debugging
        raw_file = OUTPUT_DIR / "im_raw_captured.json"
        with open(raw_file, "w", encoding="utf-8") as f:
            json.dump(all_captured, f, ensure_ascii=False, indent=2)
        logger.info(f"Raw data saved to {raw_file}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
