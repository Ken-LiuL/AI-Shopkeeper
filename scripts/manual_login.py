"""Manual QNH login — opens browser, you login manually, cookies auto-saved."""

import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COOKIE_FILE = PROJECT_ROOT / "config" / "qnh_cookies.json"


async def main():
    import nodriver as uc
    import nodriver.cdp.network as net

    logger.info("Opening browser — please login manually...")
    browser = await uc.start(
        headless=False,
        sandbox=False,
        browser_args=["--no-first-run", "--no-default-browser-check"],
    )

    epassport_login = (
        "https://qnh-epassport.meituan.com/portal/login"
        "?feconfig=qianniuhua-admin-support-phone-account"
        "&service=shuguopai-admin&bgSource=3"
        "&continue=https%3A%2F%2Fqnh.meituan.com%2Fapi%2Fv1%2Feplogin%2Fcallback"
        "%3FcallbackUrl%3Dhttps%253A%252F%252Fqnh.meituan.com%252Fepassport-callback.html"
        "%26appId%3D3%26bizAppId%3D2%26appName%3D%25E7%2589%25B5%25E7%2589%259B%25E8%258A%25B1"
    )

    tab = await browser.get(epassport_login)

    # Wait for user to login manually — poll URL every 3 seconds
    logger.info("Waiting for you to login... (will auto-detect when you reach qnh.meituan.com)")
    for i in range(120):  # 6 minutes max
        await tab.sleep(3)
        try:
            url = tab.target.url or ""
        except:
            url = ""
        if "qnh.meituan.com" in url and "epassport" not in url:
            logger.info(f"Login successful! URL: {url}")
            break
        if i % 10 == 0 and i > 0:
            logger.info(f"Still waiting... ({i * 3}s)")
    else:
        logger.error("Timeout waiting for login (6 min)")
        browser.stop()
        return

    # Save cookies
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
