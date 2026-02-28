"""美团 IM 聊天记录爬取 — DOM 提取模式

策略：点击每个会话，等页面渲染消息后直接从 DOM 提取文本。
比拦截 API 更可靠（API 返回编码的二进制消息，需要前端解码）。
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
    logger.info("=== 美团 IM 聊天记录爬取 (DOM 提取) ===")
    browser, page = await init_browser()

    try:
        # Navigate to IM page
        page = await browser.get("https://qnh.meituan.com/#/medCrm/wb/todo/im?_s_layout_hidden_=1")
        await page.sleep(10)

        # Check page loaded
        body_text = await evaluate_js(page, "document.body.innerText?.substring(0, 500)")
        logger.info(f"Page loaded: {body_text[:200] if body_text else 'empty'}")

        # First click "近1天未接待已结束" tab to see historical conversations
        logger.info("Clicking historical conversations tab...")
        await evaluate_js(
            page,
            """
            (() => {
                const tabs = document.querySelectorAll('[class*="sessionItem"], [class*="tab"], span, div');
                for (const el of tabs) {
                    const text = el.textContent?.trim();
                    if (text && text.includes('未接待已结束')) {
                        el.click();
                        return 'clicked: ' + text;
                    }
                }
                return 'not found';
            })()
        """,
        )
        await page.sleep(3)

        # Get conversation list using the actual CSS class from Phase 1
        session_items_raw = await evaluate_js(
            page,
            """
            (() => {
                // Use the actual class discovered: sessionItem-DXA6lU
                let items = document.querySelectorAll('[class*="sessionItem"]');
                if (items.length === 0) items = document.querySelectorAll('[class*="session-item"]');
                if (items.length === 0) items = document.querySelectorAll('[class*="SessionItem"]');

                return JSON.stringify({
                    count: items.length,
                    previews: Array.from(items).slice(0, 30).map((el, i) => ({
                        index: i,
                        text: el.textContent?.trim()?.substring(0, 200),
                        classes: el.className
                    }))
                });
            })()
        """,
        )

        sessions = json.loads(session_items_raw) if session_items_raw else {"count": 0}
        logger.info(f"Found {sessions['count']} session items")

        if sessions["count"] == 0:
            # Try broader selector
            logger.info("Trying broader selectors...")
            sessions_raw2 = await evaluate_js(
                page,
                """
                (() => {
                    // List all elements that could be conversation items
                    const all = document.querySelectorAll('*');
                    const candidates = [];
                    for (const el of all) {
                        const cls = el.className || '';
                        if (typeof cls === 'string' && cls.match(/session|dialog|chat/i) && el.children.length < 20) {
                            candidates.push({
                                tag: el.tagName,
                                class: cls.substring(0, 100),
                                text: el.textContent?.trim()?.substring(0, 100),
                                childCount: el.children.length
                            });
                        }
                    }
                    return JSON.stringify(candidates.slice(0, 30));
                })()
            """,
            )
            logger.info(f"Candidates: {sessions_raw2[:1000] if sessions_raw2 else 'none'}")

        conversations = []
        count = min(sessions["count"], 30)

        for i in range(count):
            preview = sessions["previews"][i] if i < len(sessions.get("previews", [])) else {}
            logger.info(
                f"\n--- Clicking conversation {i + 1}/{count}: {preview.get('text', '?')[:60]} ---"
            )

            # Click the session item
            clicked = await evaluate_js(
                page,
                f"""
                (() => {{
                    const items = document.querySelectorAll('[class*="sessionItem"]');
                    if (items[{i}]) {{
                        items[{i}].click();
                        return 'clicked';
                    }}
                    return 'not found';
                }})()
            """,
            )

            if clicked != "clicked":
                logger.warning(f"  Could not click item {i}")
                continue

            await page.sleep(3)  # Wait for messages to render

            # Extract customer name
            customer_name = await evaluate_js(
                page,
                """
                (() => {
                    // Look for customer name in chat header area
                    const nameEl = document.querySelector('[class*="customerName"], [class*="userName"], [class*="chatTitle"], [class*="header"] [class*="name"]');
                    return nameEl ? nameEl.textContent?.trim() : null;
                })()
            """,
            )

            # Extract all messages from the chat area
            messages_raw = await evaluate_js(
                page,
                """
                (() => {
                    // Find message container - try various selectors
                    const selectors = [
                        '[class*="messageRow"]',
                        '[class*="message-row"]',
                        '[class*="chatMessage"]',
                        '[class*="msg-item"]',
                        '[class*="bubble"]',
                    ];

                    let msgElements = [];
                    for (const sel of selectors) {
                        const items = document.querySelectorAll(sel);
                        if (items.length > 0) {
                            msgElements = Array.from(items);
                            break;
                        }
                    }

                    if (msgElements.length === 0) {
                        // Try the chat container
                        const container = document.querySelector('[class*="chatContainer"]');
                        if (container) {
                            // Get all text blocks within chat container
                            const blocks = container.querySelectorAll('div, p, span');
                            const seen = new Set();
                            const texts = [];
                            for (const el of blocks) {
                                const text = el.textContent?.trim();
                                if (text && text.length > 2 && text.length < 1000 && !seen.has(text)) {
                                    seen.add(text);
                                    // Determine if it's from customer or agent
                                    const parent = el.closest('[class*="left"], [class*="right"], [class*="self"], [class*="other"], [class*="customer"], [class*="agent"]');
                                    const role = parent ?
                                        (parent.className.match(/right|self|agent/i) ? 'agent' : 'customer')
                                        : 'unknown';
                                    texts.push({
                                        content: text,
                                        role: role,
                                        classes: el.className?.substring?.(0, 80) || ''
                                    });
                                }
                            }
                            return JSON.stringify({ source: 'chatContainer', count: texts.length, messages: texts.slice(0, 100) });
                        }
                        return JSON.stringify({ source: 'none', count: 0, messages: [] });
                    }

                    return JSON.stringify({
                        source: 'messageRow',
                        count: msgElements.length,
                        messages: msgElements.map(el => {
                            const isRight = el.closest('[class*="right"]') || el.querySelector('[class*="right"]') || el.className?.includes?.('right');
                            const isSelf = el.closest('[class*="self"]') || el.className?.includes?.('self');
                            return {
                                content: el.textContent?.trim()?.substring(0, 500),
                                role: (isRight || isSelf) ? 'agent' : 'customer',
                                classes: el.className?.substring?.(0, 80) || ''
                            };
                        }).filter(m => m.content && m.content.length > 0)
                    });
                })()
            """,
            )

            messages = json.loads(messages_raw) if messages_raw else {"count": 0, "messages": []}
            logger.info(
                f"  Customer: {customer_name}, Messages: {messages.get('count', 0)} ({messages.get('source', '?')})"
            )

            if messages.get("messages"):
                for m in messages["messages"][:3]:
                    logger.info(f"    [{m.get('role', '?')}] {m.get('content', '')[:80]}")

            conversations.append(
                {
                    "index": i,
                    "customer_name": customer_name,
                    "preview": preview.get("text", "")[:200],
                    "messages": messages,
                }
            )

            # Also try scrolling up to load older messages
            await evaluate_js(
                page,
                """
                (() => {
                    const container = document.querySelector('[class*="chatContainer"], [class*="messageList"]');
                    if (container) {
                        container.scrollTop = 0;  // Scroll to top to trigger loading older messages
                    }
                })()
            """,
            )
            await page.sleep(1)

        # Save all conversations
        output = {
            "scraped_at": datetime.now().isoformat(),
            "method": "dom_extraction",
            "total_sessions": sessions["count"],
            "scraped_count": len(conversations),
            "conversations": conversations,
        }

        output_file = OUTPUT_DIR / "im_conversations.json"
        output_file.parent.mkdir(exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(f"\n✅ Saved {len(conversations)} conversations to {output_file}")

        # Summary
        total_msgs = sum(c.get("messages", {}).get("count", 0) for c in conversations)
        logger.info(f"Total messages extracted: {total_msgs}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
