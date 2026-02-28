"""美团 IM 聊天记录爬取 v3 — 正确的 DOM 选择器

实际 DOM 结构：
- bubbleList container: .bubbleList-* or .yyfe-infinite-list
- 每条消息: .bubbleItem-*
  - 发送者+时间: .nameRow-*  → span (name), span (time)
  - 消息内容: .messageWrap-* → .contentContainer-*
  - 客户消息: contentContainer 有 class 包含 "customer"
  - 客服消息: contentContainer 没有 "customer"
- 系统消息: .systemMessageContainer-*
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


async def ev(page, js: str) -> str | None:
    r = await page.send(
        nodriver.cdp.runtime.evaluate(
            expression=js,
            await_promise=True,
            return_by_value=True,
        )
    )
    if isinstance(r, tuple):
        obj, exc = r
        if exc:
            logger.error(f"JS: {exc}")
            return None
        return obj.value if obj else None
    return r.value if hasattr(r, "value") else None


EXTRACT_MESSAGES_JS = """
(() => {
    const bubbles = document.querySelectorAll('[class*="bubbleItem"]');
    const sysMessages = document.querySelectorAll('[class*="systemMessageContainer"]');

    const messages = [];

    // Extract bubble messages
    for (const bubble of bubbles) {
        const nameRow = bubble.querySelector('[class*="nameRow"]');
        const spans = nameRow ? nameRow.querySelectorAll('span') : [];
        const name = spans[0]?.textContent?.trim() || '';
        const time = spans[1]?.textContent?.trim() || '';

        const contentEl = bubble.querySelector('[class*="contentContainer"]');
        const content = contentEl?.textContent?.trim() || '';
        const isCustomer = contentEl?.className?.includes('customer') || false;

        if (content) {
            messages.push({
                role: isCustomer ? 'customer' : 'agent',
                name: name,
                time: time,
                content: content.substring(0, 1000)
            });
        }
    }

    // Extract system messages
    for (const sys of sysMessages) {
        const text = sys.textContent?.trim();
        if (text) {
            messages.push({
                role: 'system',
                name: '',
                time: '',
                content: text.substring(0, 500)
            });
        }
    }

    return JSON.stringify({
        bubbleCount: bubbles.length,
        sysCount: sysMessages.length,
        messages: messages
    });
})()
"""


async def main():
    logger.info("=== 美团 IM 聊天记录爬取 v3 ===")
    browser, page = await init_browser()

    try:
        page = await browser.get("https://qnh.meituan.com/#/medCrm/wb/todo/im?_s_layout_hidden_=1")
        await page.sleep(10)

        # Get session count
        count_raw = await ev(
            page,
            """
            (() => {
                const items = document.querySelectorAll('[class*="sessionItem"]');
                return JSON.stringify({
                    count: items.length,
                    names: Array.from(items).map(el => {
                        const nameEl = el.querySelector('[class*="ml-"]') || el.querySelector('span');
                        return nameEl?.textContent?.trim()?.substring(0, 50) || '';
                    })
                });
            })()
        """,
        )
        sessions = json.loads(count_raw) if count_raw else {"count": 0, "names": []}
        total = sessions["count"]
        logger.info(f"Found {total} sessions")

        conversations = []

        for i in range(total):
            name = sessions["names"][i] if i < len(sessions["names"]) else f"session_{i}"
            logger.info(f"\n[{i + 1}/{total}] Clicking: {name}")

            # Click session
            await ev(
                page,
                f"""
                (() => {{
                    const items = document.querySelectorAll('[class*="sessionItem"]');
                    if (items[{i}]) {{ items[{i}].click(); return 'ok'; }}
                    return 'miss';
                }})()
            """,
            )
            await page.sleep(3)

            # Scroll chat to top to load all messages
            await ev(
                page,
                """
                (() => {
                    const list = document.querySelector('[class*="bubbleList"], .yyfe-infinite-list');
                    if (list) { list.scrollTop = 0; }
                })()
            """,
            )
            await page.sleep(2)

            # Extract messages
            msgs_raw = await ev(page, EXTRACT_MESSAGES_JS)
            msgs = json.loads(msgs_raw) if msgs_raw else {"bubbleCount": 0, "messages": []}

            msg_count = len(msgs["messages"])
            customer_msgs = [m for m in msgs["messages"] if m["role"] == "customer"]
            agent_msgs = [m for m in msgs["messages"] if m["role"] == "agent"]

            logger.info(
                f"  Messages: {msg_count} (customer:{len(customer_msgs)}, agent:{len(agent_msgs)}, system:{msg_count - len(customer_msgs) - len(agent_msgs)})"
            )

            # Show first few messages
            for m in msgs["messages"][:3]:
                logger.info(
                    f"    [{m['role']}] {m.get('name', '')} {m.get('time', '')}: {m['content'][:80]}"
                )

            conversations.append(
                {
                    "index": i,
                    "session_name": name,
                    "message_count": msg_count,
                    "messages": msgs["messages"],
                }
            )

        # Save
        output = {
            "scraped_at": datetime.now().isoformat(),
            "total_sessions": total,
            "conversations": conversations,
            "stats": {
                "total_messages": sum(c["message_count"] for c in conversations),
                "avg_messages_per_session": sum(c["message_count"] for c in conversations)
                / max(len(conversations), 1),
            },
        }

        output_file = OUTPUT_DIR / "im_conversations.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(
            f"\n✅ Saved {len(conversations)} conversations ({output['stats']['total_messages']} messages) to {output_file}"
        )

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
