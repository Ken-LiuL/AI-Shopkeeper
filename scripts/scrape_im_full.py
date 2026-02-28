"""美团 IM 聊天记录全量爬取 — 历史会话 + 当前会话

爬取所有可访问的历史对话，不只是近1天。
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

    for (const sys of sysMessages) {
        const text = sys.textContent?.trim();
        if (text) {
            messages.push({ role: 'system', name: '', time: '', content: text.substring(0, 500) });
        }
    }

    return JSON.stringify({ bubbleCount: bubbles.length, sysCount: sysMessages.length, messages: messages });
})()
"""


async def scrape_session_list(page):
    """Get all session items currently visible"""
    raw = await ev(
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
    return json.loads(raw) if raw else {"count": 0, "names": []}


async def scroll_and_load_more(page, max_scrolls=20):
    """Scroll session list to load more items"""
    prev_count = 0
    for i in range(max_scrolls):
        raw = await ev(
            page,
            """
            (() => {
                const list = document.querySelector('[class*="sessionList"]');
                if (list) {
                    list.scrollTop = list.scrollHeight;
                }
                const items = document.querySelectorAll('[class*="sessionItem"]');
                return items.length;
            })()
        """,
        )
        count = int(raw) if raw else 0
        logger.info(f"  Scroll {i + 1}: {count} sessions loaded")
        if count == prev_count:
            break  # No more to load
        prev_count = count
        await page.sleep(2)
    return prev_count


async def scrape_conversations(page, sessions, tab_name):
    """Scrape all conversations from current session list"""
    conversations = []
    total = sessions["count"]

    for i in range(total):
        name = sessions["names"][i] if i < len(sessions["names"]) else f"session_{i}"
        logger.info(f"  [{i + 1}/{total}] {name}")

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
        await page.sleep(2)

        # Scroll chat to top to load older messages, repeat a few times
        for _ in range(3):
            scrolled = await ev(
                page,
                """
                (() => {
                    const list = document.querySelector('[class*="bubbleList"], .yyfe-infinite-list');
                    if (list) {
                        const before = list.scrollTop;
                        list.scrollTop = 0;
                        return list.scrollTop !== before ? 'scrolled' : 'at_top';
                    }
                    return 'no_list';
                })()
            """,
            )
            if scrolled != "scrolled":
                break
            await page.sleep(1.5)

        msgs_raw = await ev(page, EXTRACT_MESSAGES_JS)
        msgs = json.loads(msgs_raw) if msgs_raw else {"messages": []}

        msg_list = msgs["messages"]
        customer_msgs = sum(1 for m in msg_list if m["role"] == "customer")
        agent_msgs = sum(1 for m in msg_list if m["role"] == "agent")

        if msg_list:
            logger.info(f"    {len(msg_list)} msgs (C:{customer_msgs} A:{agent_msgs})")

        conversations.append(
            {
                "tab": tab_name,
                "index": i,
                "session_name": name,
                "message_count": len(msg_list),
                "messages": msg_list,
            }
        )

    return conversations


async def main():
    logger.info("=== 美团 IM 聊天记录全量爬取 ===")
    browser, page = await init_browser()
    all_conversations = []

    try:
        page = await browser.get("https://qnh.meituan.com/#/medCrm/wb/todo/im?_s_layout_hidden_=1")
        await page.sleep(10)

        # Dump available tabs
        tabs_raw = await ev(
            page,
            """
            (() => {
                const els = document.querySelectorAll('span, div, a');
                const tabs = [];
                for (const el of els) {
                    const text = el.textContent?.trim();
                    if (text && (text.includes('历史会话') || text.includes('当前会话') || text.includes('待办会话') ||
                        text.includes('待接待') || text.includes('接待中') || text.includes('未接待已结束'))) {
                        if (!tabs.some(t => t.text === text)) {
                            tabs.push({ text: text, tag: el.tagName, cls: (el.className || '').substring(0, 80) });
                        }
                    }
                }
                return JSON.stringify(tabs);
            })()
        """,
        )
        tabs = json.loads(tabs_raw) if tabs_raw else []
        logger.info(f"Found tabs: {[t['text'] for t in tabs]}")

        # 1. Scrape current "近1天未接待已结束" (already visible)
        logger.info("\n=== Tab: 近1天未接待已结束 ===")
        sessions = await scrape_session_list(page)
        logger.info(f"Sessions: {sessions['count']}")
        convs = await scrape_conversations(page, sessions, "近1天未接待已结束")
        all_conversations.extend(convs)

        # 2. Click "历史会话" tab
        logger.info("\n=== Tab: 历史会话 ===")
        clicked = await ev(
            page,
            """
            (() => {
                const els = document.querySelectorAll('span, div, a, li');
                for (const el of els) {
                    const text = el.textContent?.trim();
                    if (text === '历史会话') {
                        el.click();
                        return 'clicked';
                    }
                }
                return 'not found';
            })()
        """,
        )
        logger.info(f"历史会话 click: {clicked}")
        await page.sleep(5)

        if clicked == "clicked":
            # Scroll to load more historical sessions
            logger.info("Loading more historical sessions...")
            total_loaded = await scroll_and_load_more(page, max_scrolls=30)
            logger.info(f"Total historical sessions loaded: {total_loaded}")

            sessions = await scrape_session_list(page)
            logger.info(f"Historical sessions: {sessions['count']}")
            convs = await scrape_conversations(page, sessions, "历史会话")
            all_conversations.extend(convs)

        # 3. Try "待接待" and "接待中" if they have items
        for tab_name in ["待接待", "接待中"]:
            logger.info(f"\n=== Tab: {tab_name} ===")
            clicked = await ev(
                page,
                f"""
                (() => {{
                    const els = document.querySelectorAll('span, div, a, li');
                    for (const el of els) {{
                        const text = el.textContent?.trim();
                        if (text && text.startsWith('{tab_name}')) {{
                            el.click();
                            return 'clicked';
                        }}
                    }}
                    return 'not found';
                }})()
            """,
            )
            if clicked == "clicked":
                await page.sleep(3)
                sessions = await scrape_session_list(page)
                if sessions["count"] > 0:
                    convs = await scrape_conversations(page, sessions, tab_name)
                    all_conversations.extend(convs)
                else:
                    logger.info(f"  No sessions in {tab_name}")

        # Save everything
        total_msgs = sum(c["message_count"] for c in all_conversations)
        output = {
            "scraped_at": datetime.now().isoformat(),
            "total_sessions": len(all_conversations),
            "total_messages": total_msgs,
            "conversations": all_conversations,
        }

        output_file = OUTPUT_DIR / "im_conversations_full.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(
            f"\n✅ Saved {len(all_conversations)} conversations ({total_msgs} messages) to {output_file}"
        )

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        # Save partial results
        if all_conversations:
            partial_file = OUTPUT_DIR / "im_conversations_partial.json"
            with open(partial_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"scraped_at": datetime.now().isoformat(), "conversations": all_conversations},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            logger.info(f"Partial results saved to {partial_file}")
    finally:
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
