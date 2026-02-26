"""Quick test: login via nodriver, capture cookies, test SPU APIs."""

import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COOKIE_FILE = PROJECT_ROOT / "config" / "qnh_cookies.json"
QNH_BASE = "https://qnh.meituan.com"
USERNAME = "B13297957849"
PASSWORD = "b13297957849#"


async def main():
    import nodriver as uc
    import nodriver.cdp.network as net

    logger.info("Starting browser...")
    browser = await uc.start(
        headless=False,
        sandbox=False,
        browser_args=["--no-first-run", "--no-default-browser-check"],
    )

    # Go to epassport login
    epassport_login = (
        "https://qnh-epassport.meituan.com/portal/login"
        "?feconfig=qianniuhua-admin-support-phone-account"
        "&service=shuguopai-admin&bgSource=3"
        "&continue=https%3A%2F%2Fqnh.meituan.com%2Fapi%2Fv1%2Feplogin%2Fcallback"
        "%3FcallbackUrl%3Dhttps%253A%252F%252Fqnh.meituan.com%252Fepassport-callback.html"
        "%26appId%3D3%26bizAppId%3D2%26appName%3D%25E7%2589%25B5%25E7%2589%259B%25E8%258A%25B1"
    )

    tab = await browser.get(epassport_login)
    await tab.sleep(5)

    # Fill login
    js_login = f"""
    (function() {{
        var inputs = document.querySelectorAll('input');
        var accountInput = null, pwdInput = null;
        for (var i = 0; i < inputs.length; i++) {{
            var inp = inputs[i];
            var type = (inp.type || '').toLowerCase();
            if (type === 'password') pwdInput = inp;
            else if (type === 'text' || type === 'tel') accountInput = inp;
        }}
        if (!accountInput || !pwdInput) return 'inputs_not_found';
        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(accountInput, '{USERNAME}');
        accountInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
        setter.call(pwdInput, '{PASSWORD}');
        pwdInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
        return 'filled';
    }})()
    """
    result = await tab.evaluate(js_login)
    logger.info(f"Login fill: {result}")
    await tab.sleep(1)

    # Agree checkbox
    await tab.evaluate("""
    (function() {
        var cbs = document.querySelectorAll('input[type="checkbox"]');
        for (var i = 0; i < cbs.length; i++) { if (!cbs[i].checked) cbs[i].click(); }
    })()
    """)
    await tab.sleep(0.5)

    # Click login
    await tab.evaluate("""
    (function() {
        var btns = document.querySelectorAll('button');
        for (var i = 0; i < btns.length; i++) {
            if ((btns[i].textContent || '').includes('登')) { btns[i].click(); return; }
        }
    })()
    """)
    logger.info("Clicked login, waiting for redirect...")
    await tab.sleep(15)

    url = await tab.evaluate("window.location.href")
    logger.info(f"URL after login: {url}")

    # Save cookies
    all_cookies = await tab.send(net.get_all_cookies())
    cookie_list = all_cookies[0] if isinstance(all_cookies, tuple) else all_cookies
    cookie_dict = {}
    for c in cookie_list:
        if hasattr(c, "name") and hasattr(c, "value"):
            if "meituan" in (getattr(c, "domain", "") or ""):
                cookie_dict[c.name] = c.value
    COOKIE_FILE.write_text(json.dumps(cookie_dict, indent=2))
    logger.info(f"Saved {len(cookie_dict)} cookies")

    # Navigate to home
    if "login" in url.lower() or "epassport" in url.lower():
        logger.error("Still on login page - login failed!")
        # Take screenshot for debug
        import base64

        import nodriver.cdp.page as page_cdp

        ss = await tab.send(page_cdp.capture_screenshot(format_="png"))
        data = ss[0] if isinstance(ss, tuple) else ss
        Path(PROJECT_ROOT / "docs" / "login-debug.png").write_bytes(base64.b64decode(data))
        browser.stop()
        return

    # Go to home, then product page
    tab = await browser.get(f"{QNH_BASE}/home.html")
    await tab.sleep(5)

    # Enable network monitoring
    await tab.send(net.enable())
    captured = []

    def on_request(event):
        url = event.request.url
        if "meituan.com" in url and ("/api/" in url or "/goldengateway/" in url):
            captured.append(
                {
                    "method": event.request.method,
                    "url": url,
                    "postData": getattr(event.request, "post_data", None) or "",
                }
            )
            logger.info(f"API: {event.request.method} {url[:120]}")

    tab.add_handler(net.RequestWillBeSent, on_request)

    # Navigate to product management
    logger.info("Going to product management page...")
    await tab.evaluate(
        f"window.location.href = '{QNH_BASE}/home.html#/unifiedGoods/tenant/spu-list'"
    )
    await tab.sleep(15)

    # Try some known API patterns
    logger.info("Testing API patterns from browser context...")
    api_tests = [
        ("/api/v1/merchant/storeCategory/queryAll", "POST", {"tenantId": "1011766"}),
        ("/api/v1/merchant/spu/page", "POST", {"tenantId": "1011766", "page": 1, "pageSize": 5}),
        ("/api/v1/merchant/spu/list", "POST", {"tenantId": "1011766", "page": 1, "pageSize": 5}),
    ]

    for path, method, body in api_tests:
        js = f"""
        (function() {{
            return fetch('{QNH_BASE}{path}?yodaReady=h5&csecplatform=4&csecversion=4.2.0', {{
                method: '{method}',
                headers: {{'Content-Type': 'application/json'}},
                credentials: 'include',
                body: JSON.stringify({json.dumps(body)})
            }}).then(r => r.text()).then(t => t.substring(0, 1000))
              .catch(e => 'ERROR: ' + e.message);
        }})()
        """
        try:
            result = await tab.evaluate(js)
            logger.info(f"API {path}: {result[:300] if result else 'empty'}")
        except Exception as e:
            logger.error(f"API {path} failed: {e}")

    # Get page content to understand what APIs the product page uses
    page_text = await tab.evaluate(
        "document.body ? document.body.innerText.substring(0, 1000) : ''"
    )
    logger.info(f"Product page text: {page_text[:300]}")

    # Check what was captured
    logger.info(f"\n=== Captured {len(captured)} API calls ===")
    for c in captured:
        path = c["url"].split("?")[0].replace(QNH_BASE, "")
        logger.info(f"  {c['method']} {path}")
        if c["postData"]:
            logger.info(f"    body: {c['postData'][:200]}")

    browser.stop()
    logger.info("Done!")


if __name__ == "__main__":
    asyncio.run(main())
