"""调试 JavaScript 执行问题"""

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


async def test_js_execution(page):
    """测试不同的 JavaScript 执行方式"""

    logger.info("=== Testing simple sync JavaScript ===")

    # 测试1: 简单同步代码
    try:
        result = await page.send(
            nodriver.cdp.runtime.evaluate(expression="'Hello World'", return_by_value=True)
        )

        if isinstance(result, tuple):
            response, _ = result
        else:
            response = result

        logger.info(f"Test 1 result: {response}")
        logger.info(f"Result type: {type(response)}")
        if hasattr(response, "result"):
            logger.info(f"Result.result: {response.result}")
            if hasattr(response.result, "value"):
                logger.info(f"Result.result.value: {response.result.value}")

    except Exception as e:
        logger.error(f"Test 1 failed: {e}")

    logger.info("=== Testing simple async JavaScript ===")

    # 测试2: 简单异步代码
    try:
        js_code = """
            (async () => {
                return 'Hello Async World';
            })()
        """

        result = await page.send(
            nodriver.cdp.runtime.evaluate(
                expression=js_code, await_promise=True, return_by_value=True
            )
        )

        if isinstance(result, tuple):
            response, _ = result
        else:
            response = result

        logger.info(f"Test 2 result: {response}")
        if hasattr(response, "result") and hasattr(response.result, "value"):
            logger.info(f"Test 2 value: {response.result.value}")

    except Exception as e:
        logger.error(f"Test 2 failed: {e}")

    logger.info("=== Testing fetch to known endpoint ===")

    # 测试3: 测试 fetch 到一个已知的端点
    try:
        js_code = """
            (async () => {
                try {
                    const resp = await fetch('/', {
                        method: 'GET',
                        credentials: 'include'
                    });
                    return JSON.stringify({
                        status: resp.status,
                        statusText: resp.statusText,
                        ok: resp.ok,
                        url: resp.url
                    });
                } catch(e) {
                    return JSON.stringify({
                        error: e.message,
                        name: e.name
                    });
                }
            })()
        """

        result = await page.send(
            nodriver.cdp.runtime.evaluate(
                expression=js_code, await_promise=True, return_by_value=True
            )
        )

        if isinstance(result, tuple):
            response, _ = result
        else:
            response = result

        logger.info(f"Test 3 result: {response}")
        if hasattr(response, "result") and hasattr(response.result, "value"):
            value = response.result.value
            logger.info(f"Test 3 value: {value}")
            if value:
                parsed = json.loads(value)
                logger.info(f"Test 3 parsed: {parsed}")

    except Exception as e:
        logger.error(f"Test 3 failed: {e}")


async def main():
    """主函数"""
    logger.info("=== JavaScript Execution Debug ===")

    browser, page = await init_browser()

    try:
        # 导航到 IM 页面
        page = await browser.get("https://qnh.meituan.com/#/medCrm/wb/todo/im")
        await page.sleep(10)

        await test_js_execution(page)

    except Exception as e:
        logger.error(f"Error: {e}")
        raise
    finally:
        if browser:
            browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
