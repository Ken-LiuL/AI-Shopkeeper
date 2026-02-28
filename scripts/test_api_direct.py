"""直接测试 API 调用，不使用 JSON.stringify"""

import asyncio
import json
import logging
from pathlib import Path

import nodriver
import nodriver.cdp.network
import nodriver.cdp.runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COOKIE_FILE = Path(__file__).parent.parent / "config" / "qnh_cookies.json"


async def init_browser():
    """初始化浏览器"""
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
    return browser, page


async def test_api_simple(page):
    """测试 API，不使用 JSON.stringify，直接看结果"""

    logger.info("=== Testing API without JSON.stringify ===")

    # 测试1: 直接返回 fetch 结果的状态
    try:
        js_code = """
            (async () => {
                try {
                    const resp = await fetch('/workbench/b/dialog/chatting/records', {
                        method: 'GET',
                        credentials: 'include'
                    });
                    return {
                        status: resp.status,
                        ok: resp.ok,
                        statusText: resp.statusText
                    };
                } catch(e) {
                    return {
                        error: e.message,
                        name: e.name
                    };
                }
            })()
        """

        result = await page.send(
            nodriver.cdp.runtime.evaluate(
                expression=js_code, await_promise=True, return_by_value=True
            )
        )

        logger.info(f"API test result: {result}")
        logger.info(f"Result type: {type(result)}")
        logger.info(f"Result value: {getattr(result, 'value', 'NO VALUE ATTR')}")

    except Exception as e:
        logger.error(f"API test failed: {e}")

    # 测试2: 简单返回字符串
    try:
        js_code = """
            (async () => {
                const resp = await fetch('/workbench/b/dialog/chatting/records', {
                    credentials: 'include'
                });
                return `Status: ${resp.status}, OK: ${resp.ok}`;
            })()
        """

        result = await page.send(
            nodriver.cdp.runtime.evaluate(
                expression=js_code, await_promise=True, return_by_value=True
            )
        )

        logger.info(f"String test result: {result}")
        logger.info(f"String value: {getattr(result, 'value', 'NO VALUE ATTR')}")

    except Exception as e:
        logger.error(f"String test failed: {e}")

    # 测试3: 获取真实响应内容
    try:
        js_code = """
            (async () => {
                const resp = await fetch('/workbench/b/dialog/chatting/records', {
                    credentials: 'include'
                });
                const text = await resp.text();
                return `Status: ${resp.status}, Length: ${text.length}, Preview: ${text.substring(0, 100)}`;
            })()
        """

        result = await page.send(
            nodriver.cdp.runtime.evaluate(
                expression=js_code, await_promise=True, return_by_value=True
            )
        )

        logger.info(f"Content test result: {result}")
        logger.info(f"Content value: {getattr(result, 'value', 'NO VALUE ATTR')}")

    except Exception as e:
        logger.error(f"Content test failed: {e}")


async def main():
    """主函数"""
    logger.info("=== Direct API Testing ===")

    browser, page = await init_browser()

    try:
        # 导航到 IM 页面
        page = await browser.get("https://qnh.meituan.com/#/medCrm/wb/todo/im")
        await page.sleep(10)

        current_url = str(page.url)
        logger.info(f"Current URL: {current_url}")

        if "login" in current_url.lower():
            logger.error("Redirected to login - cookies expired")
            return

        await test_api_simple(page)

    except Exception as e:
        logger.error(f"Error: {e}")
        raise
    finally:
        if browser:
            browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
