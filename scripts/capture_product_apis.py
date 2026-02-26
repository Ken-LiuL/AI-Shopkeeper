"""Capture QNH product management page APIs using nodriver + CDP Network monitoring."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COOKIE_FILE = PROJECT_ROOT / "config" / "qnh_cookies.json"
OUTPUT_FILE = PROJECT_ROOT / "docs" / "product-api-capture.md"

QNH_BASE = "https://qnh.meituan.com"
EPASSPORT_LOGIN = (
    "https://qnh-epassport.meituan.com/portal/login"
    "?feconfig=qianniuhua-admin-support-phone-account"
    "&service=shuguopai-admin&bgSource=3"
    "&continue=https%3A%2F%2Fqnh.meituan.com%2Fapi%2Fv1%2Feplogin%2Fcallback"
    "%3FcallbackUrl%3Dhttps%253A%252F%252Fqnh.meituan.com%252Fepassport-callback.html"
    "%26appId%3D3%26bizAppId%3D2%26appName%3D%25E7%2589%25B5%25E7%2589%259B%25E8%258A%25B1"
)
USERNAME = "B13297957849"
PASSWORD = "b13297957849#"

SKIP_DOMAINS = {
    "catfront.dianping.com",
    "s3.meituan.net",
    "s3plus.meituan.net",
    "s3plus.sankuai.com",
    "awp-static.meituan.net",
    "awps-assets.meituan.net",
}
SKIP_EXTENSIONS = {".js", ".css", ".png", ".jpg", ".gif", ".svg", ".woff", ".woff2", ".ttf", ".ico"}


def is_api_request(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.hostname in SKIP_DOMAINS:
        return False
    path = parsed.path.lower()
    for ext in SKIP_EXTENSIONS:
        if path.endswith(ext):
            return False
    if "/s3webstatic/" in path or "/static/" in path:
        return False
    if parsed.hostname and "meituan.com" in parsed.hostname:
        if "/api/" in path or "/goldengateway/" in path or "/qnh-gw" in path:
            return True
    return False


class APICapture:
    def __init__(self, tab):
        self.tab = tab
        self.requests: dict[str, dict] = {}
        self.captured_apis: list[dict] = []
        self._pending: asyncio.Queue = asyncio.Queue()
        self._task = None

    def start(self):
        self._task = asyncio.create_task(self._fetcher())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _fetcher(self):
        import nodriver.cdp.network as net

        while True:
            rid = await self._pending.get()
            if rid not in self.requests:
                continue
            try:
                resp = await self.tab.send(net.get_response_body(net.RequestId(rid)))
                body = resp[0] if resp else ""
            except Exception:
                body = ""
            info = self.requests.pop(rid, None)
            if info:
                info["responseBody"] = body
                self.captured_apis.append(info)

    def on_request(self, event):
        url = event.request.url
        if is_api_request(url):
            self.requests[event.request_id.to_json()] = {
                "url": url,
                "method": event.request.method,
                "postData": getattr(event.request, "post_data", None) or "",
            }
            logger.info(f"API req: {event.request.method} {url[:120]}")

    def on_response(self, event):
        rid = event.request_id.to_json()
        if rid in self.requests:
            self.requests[rid]["status"] = event.response.status

    def on_finished(self, event):
        rid = event.request_id.to_json()
        if rid in self.requests:
            self._pending.put_nowait(rid)

    def report(self) -> str:
        lines = [
            "# QNH Product API Capture Report",
            "",
            f"Generated: {datetime.now().isoformat()}",
            f"Total unique APIs: {len(self.captured_apis)}",
            "",
        ]
        seen = set()
        unique = []
        for a in self.captured_apis:
            k = f"{a['method']} {a['url'].split('?')[0]}"
            if k not in seen:
                seen.add(k)
                unique.append(a)

        groups = [
            ("/api/ endpoints", [a for a in unique if "/api/" in a["url"]]),
            ("/qnh-gw endpoints", [a for a in unique if "/qnh-gw" in a["url"]]),
            ("/goldengateway/ endpoints", [a for a in unique if "/goldengateway/" in a["url"]]),
        ]
        for name, apis in groups:
            if not apis:
                continue
            lines += [f"## {name}", ""]
            for api in apis:
                path = api["url"].split("?")[0].replace(QNH_BASE, "")
                lines += [
                    f"### `{api['method']} {path}`",
                    "",
                    f"**Status:** {api.get('status', 'N/A')}",
                    "",
                ]
                if api.get("postData"):
                    lines += ["**Request Body:**", "```json"]
                    try:
                        lines.append(
                            json.dumps(json.loads(api["postData"]), indent=2, ensure_ascii=False)[
                                :3000
                            ]
                        )
                    except:
                        lines.append(api["postData"][:3000])
                    lines += ["```", ""]
                if api.get("responseBody"):
                    lines += ["**Response (truncated):**", "```json"]
                    try:
                        lines.append(
                            json.dumps(
                                json.loads(api["responseBody"]), indent=2, ensure_ascii=False
                            )[:5000]
                        )
                    except:
                        lines.append(api["responseBody"][:3000])
                    lines += ["```", ""]
                lines += ["---", ""]
        return "\n".join(lines)


async def login_via_epassport(browser):
    """Login by navigating directly to epassport page (avoids cross-origin iframe issue)."""
    logger.info("Navigating to epassport login page...")
    tab = await browser.get(EPASSPORT_LOGIN)
    await tab.sleep(5)

    # Fill login form
    js_login = f"""
    (function() {{
        var inputs = document.querySelectorAll('input');
        var accountInput = null, pwdInput = null;
        for (var i = 0; i < inputs.length; i++) {{
            var inp = inputs[i];
            var type = (inp.type || '').toLowerCase();
            if (type === 'password') {{
                pwdInput = inp;
            }} else if (type === 'text' || type === 'tel') {{
                accountInput = inp;
            }}
        }}
        if (!accountInput || !pwdInput) {{
            return 'inputs_not_found: ' + inputs.length;
        }}
        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(accountInput, '{USERNAME}');
        accountInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
        accountInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
        setter.call(pwdInput, '{PASSWORD}');
        pwdInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
        pwdInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return 'filled';
    }})()
    """
    result = await tab.evaluate(js_login)
    logger.info(f"Login fill: {result}")

    if result != "filled":
        logger.error("Could not fill login form")
        return None

    await tab.sleep(1)

    # Check agreement checkbox
    js_agree = """
    (function() {
        var cbs = document.querySelectorAll('input[type="checkbox"]');
        for (var i = 0; i < cbs.length; i++) {
            if (!cbs[i].checked) { cbs[i].click(); return 'checkbox_clicked'; }
        }
        // Try clickable elements near 协议/同意
        var els = document.querySelectorAll('span, div, label, a');
        for (var i = 0; i < els.length; i++) {
            var t = els[i].textContent || '';
            if ((t.includes('已阅读') || t.includes('同意')) && els[i].offsetHeight < 50) {
                els[i].click();
                return 'text_clicked: ' + t.substring(0, 40);
            }
        }
        // Try any checkbox-like element
        var checks = document.querySelectorAll('[class*="check"], [role="checkbox"]');
        for (var i = 0; i < checks.length; i++) {
            checks[i].click();
            return 'icon_clicked';
        }
        return 'no_agreement_found';
    })()
    """
    agree = await tab.evaluate(js_agree)
    logger.info(f"Agreement: {agree}")
    await tab.sleep(0.5)

    # Click login button
    js_click = """
    (function() {
        var btns = document.querySelectorAll('button');
        for (var i = 0; i < btns.length; i++) {
            var t = btns[i].textContent || '';
            if (t.includes('登') || t.includes('Login') || t.includes('登录')) {
                btns[i].click();
                return 'clicked: ' + t;
            }
        }
        return 'no_button';
    })()
    """
    click = await tab.evaluate(js_click)
    logger.info(f"Login click: {click}")

    # Wait a moment for potential slider captcha
    await tab.sleep(3)

    # Check for slider captcha and solve it
    for attempt in range(3):
        has_slider = await tab.evaluate("""
        (function() {
            var text = document.body ? document.body.innerText : '';
            return text.includes('滑块') || text.includes('拖动');
        })()
        """)
        if not has_slider:
            break

        logger.info(f"Slider captcha detected (attempt {attempt + 1}), solving...")
        import nodriver.cdp.input_ as input_cdp

        # Find slider handle position and track width
        slider_info = await tab.evaluate("""
        (function() {
            // Find the slider handle (usually has key icon, is a small draggable element)
            var candidates = document.querySelectorAll(
                '[class*="slider"] [class*="handle"], [class*="slider"] [class*="btn"], ' +
                '[class*="drag"], [class*="slide-btn"], [class*="handler"]'
            );
            // Broader search
            if (!candidates.length) {
                candidates = document.querySelectorAll('[class*="slider"] *, [class*="captcha"] *');
            }
            // Find the track
            var tracks = document.querySelectorAll(
                '[class*="slider-track"], [class*="slider-bar"], [class*="slide-bar"], ' +
                '[class*="slider"][class*="bg"], [class*="captcha-slider"]'
            );
            if (!tracks.length) {
                tracks = document.querySelectorAll('[class*="slider"]');
            }

            var handle = null, track = null;
            // The handle is usually small (< 60px width) and inside a wider track
            for (var i = 0; i < candidates.length; i++) {
                var r = candidates[i].getBoundingClientRect();
                if (r.width > 20 && r.width < 80 && r.height > 20 && r.height < 80) {
                    handle = r;
                    break;
                }
            }
            for (var i = 0; i < tracks.length; i++) {
                var r = tracks[i].getBoundingClientRect();
                if (r.width > 150) {
                    track = r;
                    break;
                }
            }

            if (!handle && !track) {
                // Last resort: find any element that looks like a slider
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var s = window.getComputedStyle(all[i]);
                    var r = all[i].getBoundingClientRect();
                    if (s.cursor === 'pointer' && r.width > 20 && r.width < 60 && r.height > 20 && r.height < 60) {
                        var parent = all[i].parentElement;
                        if (parent) {
                            var pr = parent.getBoundingClientRect();
                            if (pr.width > 200) {
                                handle = r;
                                track = pr;
                                break;
                            }
                        }
                    }
                }
            }

            if (!handle || !track) return JSON.stringify({error: 'not_found', handles: candidates.length, tracks: tracks.length});
            return JSON.stringify({
                hx: handle.x + handle.width/2,
                hy: handle.y + handle.height/2,
                hw: handle.width,
                tx: track.x, tw: track.width
            });
        })()
        """)
        logger.info(f"Slider info: {slider_info}")

        try:
            info = json.loads(slider_info)
        except:
            info = {"error": "parse_failed"}

        if "error" in info:
            logger.warning(f"Could not find slider elements: {info}")
            # Fallback: just try to drag from a reasonable position
            # The slider is typically in a modal, centered
            viewport = await tab.evaluate(
                "JSON.stringify({w: window.innerWidth, h: window.innerHeight})"
            )
            vp = json.loads(viewport)
            # Guess: slider is near bottom of modal, around center-y
            start_x = vp["w"] * 0.25
            start_y = vp["h"] * 0.65
            end_x = vp["w"] * 0.75
        else:
            start_x = info["hx"]
            start_y = info["hy"]
            end_x = info["tx"] + info["tw"] - 10

        # Perform drag: mousedown -> multiple mousemoves -> mouseup
        logger.info(f"Dragging from ({start_x:.0f},{start_y:.0f}) to ({end_x:.0f},{start_y:.0f})")

        await tab.send(
            input_cdp.dispatch_mouse_event(
                type_="mousePressed",
                x=start_x,
                y=start_y,
                button=input_cdp.MouseButton("left"),
                click_count=1,
            )
        )
        await tab.sleep(0.1)

        # Move in steps for realism
        steps = 20
        for i in range(1, steps + 1):
            progress = i / steps
            # Add slight randomness to y
            import random

            cur_x = start_x + (end_x - start_x) * progress
            cur_y = start_y + random.uniform(-2, 2)
            await tab.send(
                input_cdp.dispatch_mouse_event(
                    type_="mouseMoved", x=cur_x, y=cur_y, button=input_cdp.MouseButton("left")
                )
            )
            await tab.sleep(0.02 + random.uniform(0, 0.03))

        await tab.send(
            input_cdp.dispatch_mouse_event(
                type_="mouseReleased",
                x=end_x,
                y=start_y,
                button=input_cdp.MouseButton("left"),
                click_count=1,
            )
        )
        logger.info("Slider drag complete")
        await tab.sleep(3)

    # Wait for redirect back to QNH
    logger.info("Waiting for login redirect (10s)...")
    await tab.sleep(10)

    url_after = await tab.evaluate("window.location.href")
    logger.info(f"URL after login: {url_after}")

    if "login" in url_after.lower():
        # Maybe there's a captcha or error
        import nodriver.cdp.page as page_cdp

        try:
            ss = await tab.send(page_cdp.capture_screenshot(format_="png"))
            data = ss[0] if isinstance(ss, tuple) else ss
            path = PROJECT_ROOT / "docs" / "login-result.png"
            path.write_bytes(base64.b64decode(data))
            logger.info(f"Login result screenshot: {path}")
        except:
            pass

        body = await tab.evaluate("document.body ? document.body.innerText.substring(0, 300) : ''")
        logger.info(f"Page text: {body}")
        logger.warning("Still on login page - login may have failed")
        return None

    logger.info("Login successful!")
    return tab


async def main():
    import nodriver as uc
    import nodriver.cdp.network as net
    import nodriver.cdp.page as page_cdp

    logger.info("Starting browser...")
    browser = await uc.start(
        headless=False,
        browser_args=["--no-first-run", "--no-default-browser-check", "--no-sandbox"],
    )

    # Step 1: Login via epassport direct navigation
    tab = await login_via_epassport(browser)
    if not tab:
        logger.error("Login failed, aborting")
        browser.stop()
        return

    # Step 2: Save cookies
    try:
        all_cookies = await tab.send(net.get_all_cookies())
        cookie_list = all_cookies[0] if isinstance(all_cookies, tuple) else all_cookies
        cookie_dict = {}
        for c in cookie_list:
            if hasattr(c, "name") and hasattr(c, "value"):
                if "meituan" in (getattr(c, "domain", "") or ""):
                    cookie_dict[c.name] = c.value
        if cookie_dict:
            COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
            COOKIE_FILE.write_text(json.dumps(cookie_dict, indent=2))
            logger.info(f"Saved {len(cookie_dict)} cookies")
    except Exception as e:
        logger.warning(f"Cookie save failed: {e}")

    # Step 3: Navigate to product management page
    logger.info("Navigating to QNH home...")
    await tab.evaluate(f"window.location.href = '{QNH_BASE}/home.html'")
    await tab.sleep(5)

    # Set up network monitoring
    await tab.send(net.enable())
    capture = APICapture(tab)
    capture.start()
    tab.add_handler(net.RequestWillBeSent, capture.on_request)
    tab.add_handler(net.ResponseReceived, capture.on_response)
    tab.add_handler(net.LoadingFinished, capture.on_finished)

    # Navigate to product page
    logger.info("Navigating to product management...")
    await tab.evaluate(
        f"window.location.href = '{QNH_BASE}/home.html#/unifiedGoods/tenant/spu-list'"
    )
    await tab.sleep(15)

    # Screenshot
    try:
        ss = await tab.send(page_cdp.capture_screenshot(format_="png"))
        data = ss[0] if isinstance(ss, tuple) else ss
        ss_path = PROJECT_ROOT / "docs" / "product-page-screenshot.png"
        ss_path.write_bytes(base64.b64decode(data))
        logger.info(f"Screenshot: {ss_path}")
    except:
        pass

    # Log page content
    try:
        body = await tab.evaluate(
            "document.body ? document.body.innerText.substring(0, 500) : 'no body'"
        )
        logger.info(f"Page text: {body[:200]}")
    except:
        pass

    # Try clicking a product for detail API calls
    logger.info("Looking for product items...")
    try:
        row_count = await tab.evaluate(
            "document.querySelectorAll('.ant-table-row, [class*=goods], [class*=product], [class*=spu], tr').length"
        )
        logger.info(f"Potential product rows: {row_count}")

        if row_count and int(row_count) > 0:
            click_js = """
            (function() {
                var rows = document.querySelectorAll('.ant-table-row, tr[data-row-key]');
                if (rows.length > 0) {
                    var links = rows[0].querySelectorAll('a');
                    if (links.length > 0) { links[0].click(); return 'clicked_link'; }
                    rows[0].click(); return 'clicked_row';
                }
                var btns = document.querySelectorAll('a, button');
                for (var i = 0; i < btns.length; i++) {
                    var t = btns[i].textContent || '';
                    if (t.includes('编辑') || t.includes('查看') || t.includes('详情')) {
                        btns[i].click(); return 'clicked: ' + t;
                    }
                }
                return 'nothing_clicked';
            })()
            """
            result = await tab.evaluate(click_js)
            logger.info(f"Product click: {result}")
            await tab.sleep(10)
    except Exception as e:
        logger.warning(f"Product interaction failed: {e}")

    # Also try navigating to specific SPU pages
    logger.info("Trying direct SPU API calls...")
    try:
        # Trigger goldengateway product listing
        api_js = """
        (function() {
            return fetch('/goldengateway/', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    viewCode: 'qnh_unified_spu_list',
                    param: {
                        tenantId: 1011766,
                        pageNo: 1,
                        pageSize: 20
                    }
                })
            }).then(r => r.text()).then(t => t.substring(0, 2000));
        })()
        """
        api_result = await tab.evaluate(api_js)
        logger.info(f"Direct SPU list API: {api_result[:300] if api_result else 'empty'}")
    except Exception as e:
        logger.warning(f"Direct API call failed: {e}")

    await tab.sleep(5)
    await capture.stop()

    # Drain remaining requests
    for rid in list(capture.requests.keys()):
        try:
            resp = await tab.send(net.get_response_body(net.RequestId(rid)))
            body = resp[0] if resp else ""
        except:
            body = ""
        info = capture.requests.pop(rid, None)
        if info:
            info["responseBody"] = body
            capture.captured_apis.append(info)

    # Save report
    report = capture.report()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(report)
    logger.info(f"Report saved to {OUTPUT_FILE}")

    # Print summary
    print("\n" + "=" * 70)
    print("CAPTURED QNH APIs:")
    print("=" * 70)
    seen = set()
    for api in capture.captured_apis:
        k = f"{api['method']} {api['url'].split('?')[0].replace(QNH_BASE, '')}"
        if k not in seen:
            seen.add(k)
            status = api.get("status", "?")
            body_len = len(api.get("responseBody", ""))
            print(f"  {k} [{status}] {body_len}b")
    print("=" * 70)

    browser.stop()


if __name__ == "__main__":
    # Kill any leftover previous run
    import subprocess

    subprocess.run(["pkill", "-f", "capture_product_apis"], capture_output=True)
    time.sleep(1)
    asyncio.run(main())
