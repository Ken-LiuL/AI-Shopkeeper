"""Fill username/password, then wait for manual login. No other page visits."""

import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COOKIE_FILE = PROJECT_ROOT / "config" / "qnh_cookies.json"
USERNAME = "B13297957849"
PASSWORD = "b13297957849#"

LOGIN_URL = (
    "https://qnh-epassport.meituan.com/portal/login"
    "?feconfig=qianniuhua-admin-support-phone-account"
    "&service=shuguopai-admin&bgSource=3"
    "&continue=https%3A%2F%2Fqnh.meituan.com%2Fapi%2Fv1%2Feplogin%2Fcallback"
    "%3FcallbackUrl%3Dhttps%253A%252F%252Fqnh.meituan.com%252Fepassport-callback.html"
    "%26appId%3D3%26bizAppId%3D2%26appName%3D%25E7%2589%25B5%25E7%2589%259B%25E8%258A%25B1"
)


async def main():
    import nodriver as uc
    import nodriver.cdp.network as net

    logger.info("Starting browser (ONLY login page)...")
    browser = await uc.start(
        headless=False,
        sandbox=False,
        browser_args=["--no-first-run", "--no-default-browser-check"],
    )

    tab = await browser.get(LOGIN_URL)
    await tab.sleep(5)

    # Fill username and password
    js_fill = f"""
    (function() {{
        var inputs = document.querySelectorAll('input');
        var accountInput = null, pwdInput = null;
        for (var i = 0; i < inputs.length; i++) {{
            var type = (inputs[i].type || '').toLowerCase();
            if (type === 'password') pwdInput = inputs[i];
            else if (type === 'text' || type === 'tel') accountInput = inputs[i];
        }}
        if (!accountInput || !pwdInput) return 'inputs_not_found';
        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(accountInput, '{USERNAME}');
        accountInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
        setter.call(pwdInput, '{PASSWORD}');
        pwdInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
        // Check agreement checkbox
        var cbs = document.querySelectorAll('input[type="checkbox"]');
        for (var i = 0; i < cbs.length; i++) {{ if (!cbs[i].checked) cbs[i].click(); }}
        return 'filled';
    }})()
    """
    result = await tab.evaluate(js_fill)
    logger.info(f"Fill result: {result}")
    logger.info("Username and password filled. Please complete login (slider/SMS)...")

    # Wait for successful redirect to qnh.meituan.com
    for i in range(180):  # 9 minutes max
        await tab.sleep(3)
        try:
            url = tab.target.url or ""
        except:
            url = ""
        if "qnh.meituan.com" in url and "epassport" not in url:
            logger.info(f"Login successful! URL: {url}")
            break
        if i % 20 == 0 and i > 0:
            logger.info(f"Still waiting for login... ({i * 3}s)")
    else:
        logger.error("Timeout (9 min)")
        browser.stop()
        return

    # Save ALL meituan cookies
    all_cookies = await tab.send(net.get_all_cookies())
    cookies = [
        {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
            "httpOnly": c.http_only,
        }
        for c in all_cookies
        if "meituan" in c.domain
    ]
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(json.dumps(cookies, indent=2, ensure_ascii=False))
    logger.info(f"Saved {len(cookies)} cookies to {COOKIE_FILE}")

    browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
