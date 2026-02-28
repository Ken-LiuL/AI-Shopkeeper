"""美团商家后台客服 IM 聊天记录爬取脚本 - Phase 2

Usage: python3 scripts/scrape_im_history.py

Phase 2: 用 nodriver 在页面内直接调用 API 拉取聊天记录
策略: 在页面内执行 JS，自动带上 cookie/签名/h5guard
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import nodriver
import nodriver.cdp.network

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COOKIE_FILE = Path(__file__).parent.parent / "config" / "qnh_cookies.json"
OUTPUT_DIR = Path(__file__).parent.parent / "data"
IM_PAGE = "https://qnh.meituan.com/#/medCrm/wb/todo/im"


async def init_browser():
    """初始化浏览器，加载 cookies，等待 h5guard 初始化"""
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

    # h5guard 初始化序列（参考 sync_all_products.py）
    page = await browser.get("https://qnh.meituan.com/home.html")
    await page.sleep(10)
    logger.info(f"Loaded {len(cookies)} cookies and initialized h5guard")
    return browser, page


async def evaluate_js(page, js_code: str) -> str | None:
    """Execute async JS in page context via CDP Runtime.evaluate.
    nodriver returns (RemoteObject, ExceptionDetails) tuple."""
    import nodriver.cdp.runtime

    result = await page.send(
        nodriver.cdp.runtime.evaluate(
            expression=js_code,
            await_promise=True,
            return_by_value=True,
        )
    )

    # result is tuple: (RemoteObject, ExceptionDetails | None)
    if isinstance(result, tuple):
        remote_obj, exc = result
        if exc:
            logger.error(f"JS Exception: {exc}")
            return None
        return remote_obj.value if remote_obj else None
    # fallback: single RemoteObject
    return result.value if hasattr(result, "value") else None


def _make_fetch_js(url: str, method: str = "GET") -> str:
    return f"""
        (async () => {{
            try {{
                const resp = await fetch('{url}', {{
                    method: '{method}',
                    credentials: 'include',
                    headers: {{ 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }}
                }});
                const text = await resp.text();
                return JSON.stringify({{
                    status: resp.status,
                    ok: resp.ok,
                    url: resp.url,
                    response: text.substring(0, 5000),
                    responseLength: text.length
                }});
            }} catch(e) {{
                return JSON.stringify({{ error: e.message }});
            }}
        }})()
    """


async def test_api_endpoints(page):
    """测试两套 API 端点"""
    logger.info("=== Testing API Endpoints ===")

    endpoints = {
        "workbench_records": "/workbench/b/dialog/chatting/records",
        "workbench_pending": "/workbench/b/dialog/pending/records",
        "workbench_customerName": "/workbench/b/dialog/chatting/customerName",
        "neixin_chatlist": "https://api.neixin.cn/msg/api/pub/v1/chatlist",
        "neixin_range": "https://api.neixin.cn/msg/api/pub/v3/history/chat/range",
        "neixin_info": "https://api.neixin.cn/msg/api/pub/v1/chatlist/info",
    }

    results = {}
    for name, url in endpoints.items():
        logger.info(f"Testing: {name} → {url}")
        try:
            raw = await evaluate_js(page, _make_fetch_js(url))
            if raw:
                parsed = json.loads(raw)
                results[name] = parsed
                status = parsed.get("status", "?")
                logger.info(
                    f"  {'✅' if parsed.get('ok') else '❌'} Status {status}, {parsed.get('responseLength', 0)} bytes"
                )
                if parsed.get("response"):
                    logger.info(f"  Preview: {parsed['response'][:200]}")
            else:
                results[name] = {"no_response": True}
                logger.warning("  No response (evaluate returned None)")
        except Exception as e:
            logger.error(f"  Exception: {e}")
            results[name] = {"exception": str(e)}

    # 保存
    test_file = OUTPUT_DIR / "api_test_results.json"
    test_file.parent.mkdir(exist_ok=True)
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump(
            {"tested_at": datetime.now().isoformat(), "results": results},
            f,
            ensure_ascii=False,
            indent=2,
        )
    logger.info(f"Test results saved to {test_file}")
    return results


async def scrape_conversations_workbench(page):
    """使用工作台 API 抓取对话记录"""
    logger.info("=== Scraping via Workbench API ===")

    chatting_raw = await evaluate_js(page, _make_fetch_js("/workbench/b/dialog/chatting/records"))
    chatting_records = json.loads(chatting_raw) if chatting_raw else {"no_response": True}
    logger.info(f"Chatting records: {json.dumps(chatting_records, ensure_ascii=False)[:500]}")

    pending_raw = await evaluate_js(page, _make_fetch_js("/workbench/b/dialog/pending/records"))
    pending_records = json.loads(pending_raw) if pending_raw else {"no_response": True}
    logger.info(f"Pending records: {json.dumps(pending_records, ensure_ascii=False)[:500]}")

    return {"chatting_records": chatting_records, "pending_records": pending_records}


async def scrape_conversations_neixin(page):
    """使用内信 API 抓取对话记录"""
    logger.info("=== Scraping via Neixin API ===")
    conversations = []

    chatlist_raw = await evaluate_js(
        page, _make_fetch_js("https://api.neixin.cn/msg/api/pub/v1/chatlist")
    )
    if not chatlist_raw:
        return {"chatlist": {"no_response": True}, "conversations": []}

    chatlist = json.loads(chatlist_raw)
    logger.info(f"Chatlist: {json.dumps(chatlist, ensure_ascii=False)[:500]}")

    # Parse response to find chat IDs
    response_data = chatlist.get("response", "")
    if response_data and isinstance(response_data, str):
        try:
            inner = json.loads(response_data)
            chat_items = inner.get("data", []) if isinstance(inner, dict) else []
        except json.JSONDecodeError:
            chat_items = []
    else:
        chat_items = []

    chat_ids = []
    for item in chat_items if isinstance(chat_items, list) else []:
        if isinstance(item, dict):
            cid = item.get("chatId") or item.get("chat_id") or item.get("id")
            if cid:
                chat_ids.append(str(cid))

    logger.info(f"Found {len(chat_ids)} chat IDs: {chat_ids[:5]}")

    for i, chat_id in enumerate(chat_ids[:20]):
        logger.info(f"Fetching history {i + 1}/{min(len(chat_ids), 20)}: {chat_id}")
        raw = await evaluate_js(
            page,
            _make_fetch_js(
                f"https://api.neixin.cn/msg/api/pub/v3/history/chat/range?chatId={chat_id}"
            ),
        )
        if raw:
            parsed = json.loads(raw)
            conversations.append({"chat_id": chat_id, "data": parsed})
            logger.info(f"  ✅ {parsed.get('responseLength', 0)} bytes")
        else:
            logger.warning("  ❌ No response")
        await page.sleep(1)

    return {"chatlist": chatlist, "conversations": conversations}


async def scrape_with_xhr_fallback(page):
    """XHR fallback"""
    logger.info("=== Trying XMLHttpRequest fallback ===")
    raw = await evaluate_js(
        page,
        """
        new Promise((resolve) => {
            const xhr = new XMLHttpRequest();
            xhr.open('GET', '/workbench/b/dialog/chatting/records', true);
            xhr.withCredentials = true;
            xhr.onreadystatechange = function() {
                if (xhr.readyState === 4) {
                    resolve(JSON.stringify({ status: xhr.status, response: xhr.responseText.substring(0, 5000) }));
                }
            };
            xhr.send();
        })
    """,
    )
    if raw:
        result = json.loads(raw)
        logger.info(
            f"XHR result: status={result.get('status')}, len={len(result.get('response', ''))}"
        )
        return result
    return None


async def main():
    """主函数"""
    logger.info("=== 美团 IM 聊天记录爬取 Phase 2 ===")

    # 检查 cookie 文件
    if not COOKIE_FILE.exists():
        logger.error(f"Cookie file not found: {COOKIE_FILE}")
        return

    browser, page = await init_browser()

    try:
        # 导航到 IM 页面
        logger.info(f"Navigating to IM page: {IM_PAGE}")
        page = await browser.get(IM_PAGE)
        await page.sleep(10)  # 等待 IM 加载

        # 检查是否跳转到登录页
        current_url = str(page.url)
        if "login" in current_url.lower() or "signin" in current_url.lower():
            logger.error("❌ Redirected to login page - cookies may be expired")
            logger.error(f"Current URL: {current_url}")
            return

        logger.info(f"✅ Successfully loaded IM page: {current_url}")

        # 1. 测试 API 端点
        api_test_results = await test_api_endpoints(page)

        # 2. 根据测试结果选择可用的 API 进行抓取
        scraped_data = {}

        # 尝试工作台 API
        if any("workbench" in k and v.get("status") == 200 for k, v in api_test_results.items()):
            logger.info("Workbench API available, scraping...")
            scraped_data["workbench"] = await scrape_conversations_workbench(page)
        else:
            logger.warning("Workbench API not available")

        # 尝试内信 API
        if any("neixin" in k and v.get("status") == 200 for k, v in api_test_results.items()):
            logger.info("Neixin API available, scraping...")
            scraped_data["neixin"] = await scrape_conversations_neixin(page)
        else:
            logger.warning("Neixin API not available")

        # 如果都不行，尝试 XHR
        if not scraped_data:
            logger.info("No APIs available, trying XHR fallback...")
            xhr_result = await scrape_with_xhr_fallback(page)
            if xhr_result:
                scraped_data["xhr_fallback"] = xhr_result

        # 保存结果
        output_file = OUTPUT_DIR / "im_conversations.json"
        output_file.parent.mkdir(exist_ok=True)

        final_data = {
            "scraped_at": datetime.now().isoformat(),
            "current_url": current_url,
            "api_test_results": api_test_results,
            "scraped_data": scraped_data,
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Results saved to {output_file}")

        # 打印总结
        logger.info("=== Scraping Summary ===")
        for source, data in scraped_data.items():
            if isinstance(data, dict):
                if source == "workbench":
                    chatting_count = (
                        len(data.get("chatting_records", {}).get("data", []))
                        if isinstance(data.get("chatting_records"), dict)
                        else 0
                    )
                    pending_count = (
                        len(data.get("pending_records", {}).get("data", []))
                        if isinstance(data.get("pending_records"), dict)
                        else 0
                    )
                    logger.info(
                        f"{source}: {chatting_count} chatting + {pending_count} pending records"
                    )
                elif source == "neixin":
                    conv_count = len(data.get("conversations", []))
                    logger.info(f"{source}: {conv_count} conversations")
                else:
                    logger.info(f"{source}: {len(str(data))} chars")

        if not scraped_data:
            logger.warning("❌ No data scraped successfully")
        else:
            logger.info("✅ Scraping completed successfully")

    except Exception as e:
        logger.error(f"Error during scraping: {e}")
        raise
    finally:
        if browser:
            browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
