#!/usr/bin/env python3 -u
"""Full login + product API capture in a single browser session."""

import asyncio
import base64
import json
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.stdout.reconfigure(line_buffering=True)

PROFILE = os.path.expanduser("~/.qnh-chrome-profile")
QNH = "https://qnh.meituan.com"
EPASSPORT = (
    "https://qnh-epassport.meituan.com/portal/login"
    "?feconfig=qianniuhua-admin-support-phone-account"
    "&service=shuguopai-admin&bgSource=3"
    "&continue=https%3A%2F%2Fqnh.meituan.com%2Fapi%2Fv1%2Feplogin%2Fcallback"
    "%3FcallbackUrl%3Dhttps%253A%252F%252Fqnh.meituan.com%252Fepassport-callback.html"
    "%26appId%3D3%26bizAppId%3D2%26appName%3D%25E7%2589%25B5%25E7%2589%259B%25E8%258A%25B1"
)
U = "B13297957849"
P = "b13297957849#"

SKIP_HOSTS = {
    "catfront.dianping.com",
    "s3.meituan.net",
    "s3plus.meituan.net",
    "s3plus.sankuai.com",
    "awp-static.meituan.net",
    "awps-assets.meituan.net",
    "lx.meituan.net",
    "report.meituan.com",
    "wreport.meituan.net",
    "verify.meituan.com",
    "serverless.vip.sankuai.com",
}


def is_api(url):
    p = urlparse(url)
    if p.hostname in SKIP_HOSTS:
        return False
    path = p.path.lower()
    if any(
        path.endswith(e)
        for e in [".js", ".css", ".png", ".jpg", ".gif", ".svg", ".woff", ".woff2", ".ttf", ".ico"]
    ):
        return False
    if "/s3webstatic/" in path or "/static/" in path or "/awpstatic/" in path:
        return False
    if p.hostname and "meituan.com" in p.hostname:
        if any(
            x in path
            for x in ["/api/", "/goldengateway/", "/qnh-gw", "/common/", "/core/", "/workbench/"]
        ):
            return True
    return False


captured = []
rmap = {}


async def login(browser):
    """Login flow: fill form -> slider -> SMS wait."""
    import nodriver.cdp.input_ as input_cdp

    tab = await browser.get(EPASSPORT)
    await tab.sleep(6)

    # Fill credentials
    js = f'''(function(){{
        var i=document.querySelectorAll("input");var a,p;
        for(var x=0;x<i.length;x++){{if(i[x].type==="password")p=i[x];else if(i[x].type==="text"||i[x].type==="tel")a=i[x];}}
        if(!a||!p)return "no_inputs";
        var s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set;
        s.call(a,"{U}");a.dispatchEvent(new Event("input",{{bubbles:true}}));
        s.call(p,"{P}");p.dispatchEvent(new Event("input",{{bubbles:true}}));
        var c=document.querySelectorAll("input[type=checkbox]");for(var x=0;x<c.length;x++){{if(!c[x].checked)c[x].click();}}
        return "filled";
    }})()'''
    r = await tab.evaluate(js)
    print(f"Fill: {r}", flush=True)

    await tab.sleep(1)
    await tab.evaluate(
        'document.querySelectorAll("button").forEach(function(b){if(b.textContent.includes("登录"))b.click()})'
    )
    print("Login clicked", flush=True)

    # Wait for slider (up to 15s)
    found = False
    for i in range(15):
        await tab.sleep(1)
        found = await tab.evaluate("!!document.getElementById('yodaBox')")
        if found:
            print(f"Slider found at {i + 1}s", flush=True)
            break

    if found:
        await tab.sleep(2)
        try:
            pos_str = await tab.evaluate(
                "(function(){var b=document.getElementById('yodaBox').getBoundingClientRect();"
                "var w=document.getElementById('yodaBoxWrapper').getBoundingClientRect();"
                "return JSON.stringify({bx:b.x,by:b.y,bw:b.width,bh:b.height,wx:w.x,ww:w.width})})()"
            )
            print(f"Slider pos: {pos_str}", flush=True)
            pos = json.loads(pos_str)
            sx, sy = pos["bx"] + pos["bw"] / 2, pos["by"] + pos["bh"] / 2
            ex = pos["wx"] + pos["ww"] - 5
            await tab.send(
                input_cdp.dispatch_mouse_event(
                    type_="mousePressed",
                    x=sx,
                    y=sy,
                    button=input_cdp.MouseButton("left"),
                    click_count=1,
                )
            )
            await tab.sleep(0.15)
            for i in range(1, 36):
                p = i / 35
                ep = 1 - (1 - p) ** 2.5
                await tab.send(
                    input_cdp.dispatch_mouse_event(
                        type_="mouseMoved",
                        x=sx + (ex - sx) * ep,
                        y=sy + random.uniform(-1, 1),
                        button=input_cdp.MouseButton("left"),
                    )
                )
                await tab.sleep(0.015 + random.uniform(0, 0.025))
            await tab.send(
                input_cdp.dispatch_mouse_event(
                    type_="mouseReleased",
                    x=ex,
                    y=sy,
                    button=input_cdp.MouseButton("left"),
                    click_count=1,
                )
            )
            print("Slider done", flush=True)
        except Exception as e:
            print(f"Slider error: {e}", flush=True)
        await tab.sleep(5)

    # Check state
    text = await tab.evaluate("document.body.innerText.substring(0,500)")

    if "验证码" in text and "手机" in text:
        print("SMS verification needed", flush=True)
        # Click get code
        await tab.evaluate(
            'document.querySelectorAll("button,span,div").forEach(function(e){if(e.textContent.includes("获取验证码")&&e.offsetHeight>0)e.click()})'
        )
        print("SMS sent to 132****849, waiting up to 180s...", flush=True)
        for i in range(180):
            await tab.sleep(1)
            u = await tab.evaluate("window.location.href")
            if "login" not in u.lower():
                print(f"LOGIN OK at {i + 1}s: {u}", flush=True)
                return tab
            if i % 20 == 19:
                print(f"  {i + 1}s...", flush=True)
        print("SMS timeout", flush=True)
        return None

    # Maybe already redirected
    url = await tab.evaluate("window.location.href")
    if "login" not in url.lower():
        print(f"LOGIN OK: {url}", flush=True)
        return tab

    # Might be a timeout error - retry login
    if "超时" in text or "失败" in text:
        print(f"Login error: {text[:100]}, retrying in 10s...", flush=True)
        await tab.sleep(10)
        # Re-navigate and retry
        tab = await browser.get(EPASSPORT)
        await tab.sleep(6)
        await tab.evaluate(f'''(function(){{
            var i=document.querySelectorAll("input");var a,p;
            for(var x=0;x<i.length;x++){{if(i[x].type==="password")p=i[x];else if(i[x].type==="text"||i[x].type==="tel")a=i[x];}}
            var s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set;
            s.call(a,"{U}");a.dispatchEvent(new Event("input",{{bubbles:true}}));
            s.call(p,"{P}");p.dispatchEvent(new Event("input",{{bubbles:true}}));
            var c=document.querySelectorAll("input[type=checkbox]");for(var x=0;x<c.length;x++){{if(!c[x].checked)c[x].click();}}
        }})()''')
        await tab.sleep(1)
        await tab.evaluate(
            'document.querySelectorAll("button").forEach(function(b){if(b.textContent.includes("登录"))b.click()})'
        )
        print("Retry login clicked", flush=True)
        # Wait for slider again
        for i in range(15):
            await tab.sleep(1)
            found = await tab.evaluate("!!document.getElementById('yodaBox')")
            if found:
                break
        if found:
            await tab.sleep(2)
            try:
                pos_str = await tab.evaluate(
                    "(function(){var b=document.getElementById('yodaBox').getBoundingClientRect();"
                    "var w=document.getElementById('yodaBoxWrapper').getBoundingClientRect();"
                    "return JSON.stringify({bx:b.x,by:b.y,bw:b.width,bh:b.height,wx:w.x,ww:w.width})})()"
                )
                pos = json.loads(pos_str)
                sx, sy = pos["bx"] + pos["bw"] / 2, pos["by"] + pos["bh"] / 2
                ex = pos["wx"] + pos["ww"] - 5
                await tab.send(
                    input_cdp.dispatch_mouse_event(
                        type_="mousePressed",
                        x=sx,
                        y=sy,
                        button=input_cdp.MouseButton("left"),
                        click_count=1,
                    )
                )
                await tab.sleep(0.15)
                for i in range(1, 36):
                    p = i / 35
                    ep = 1 - (1 - p) ** 2.5
                    await tab.send(
                        input_cdp.dispatch_mouse_event(
                            type_="mouseMoved",
                            x=sx + (ex - sx) * ep,
                            y=sy + random.uniform(-1, 1),
                            button=input_cdp.MouseButton("left"),
                        )
                    )
                    await tab.sleep(0.015 + random.uniform(0, 0.025))
                await tab.send(
                    input_cdp.dispatch_mouse_event(
                        type_="mouseReleased",
                        x=ex,
                        y=sy,
                        button=input_cdp.MouseButton("left"),
                        click_count=1,
                    )
                )
                print("Slider done (retry)", flush=True)
            except Exception as e:
                print(f"Slider error (retry): {e}", flush=True)
            await tab.sleep(5)
            text = await tab.evaluate("document.body.innerText.substring(0,500)")
            if "验证码" in text and "手机" in text:
                await tab.evaluate(
                    'document.querySelectorAll("button,span,div").forEach(function(e){if(e.textContent.includes("获取验证码")&&e.offsetHeight>0)e.click()})'
                )
                print("SMS sent (retry), waiting 180s...", flush=True)
                for i in range(180):
                    await tab.sleep(1)
                    u = await tab.evaluate("window.location.href")
                    if "login" not in u.lower():
                        print(f"LOGIN OK at {i + 1}s: {u}", flush=True)
                        return tab
                    if i % 20 == 19:
                        print(f"  {i + 1}s...", flush=True)

    print(f"Unknown state: {text[:200]}", flush=True)
    return None


async def capture_apis(tab):
    """Set up network monitoring and navigate to product pages."""
    import nodriver.cdp.network as n
    import nodriver.cdp.page as page_cdp

    await tab.send(n.enable())

    def on_req(e):
        u = e.request.url
        if is_api(u):
            rmap[e.request_id.to_json()] = {
                "url": u,
                "method": e.request.method,
                "postData": getattr(e.request, "post_data", None) or "",
            }
            print(f"  API: {e.request.method} {u[:120]}", flush=True)

    def on_resp(e):
        r = e.request_id.to_json()
        if r in rmap:
            rmap[r]["status"] = e.response.status

    async def on_done(e):
        r = e.request_id.to_json()
        if r in rmap:
            try:
                body = (await tab.send(n.get_response_body(n.RequestId(r))))[0]
            except:
                body = ""
            info = rmap.pop(r)
            info["responseBody"] = body
            captured.append(info)

    tab.add_handler(n.RequestWillBeSent, on_req)
    tab.add_handler(n.ResponseReceived, on_resp)
    tab.add_handler(n.LoadingFinished, lambda e: asyncio.ensure_future(on_done(e)))

    # 1. SPU list page
    print("\n=== SPU list ===", flush=True)
    tab = await tab.browser.get(f"{QNH}/home.html#/unifiedGoods/tenant/spu-list")
    await tab.sleep(20)
    # Re-attach handlers after navigation to new tab
    tab.add_handler(n.RequestWillBeSent, on_req)
    tab.add_handler(n.ResponseReceived, on_resp)
    tab.add_handler(n.LoadingFinished, lambda e: asyncio.ensure_future(on_done(e)))
    await tab.send(n.enable())

    ss = await tab.send(page_cdp.capture_screenshot(format_="png"))
    Path("docs/product-page-screenshot.png").write_bytes(
        base64.b64decode(ss[0] if isinstance(ss, tuple) else ss)
    )

    text = await tab.evaluate("document.body?document.body.innerText.substring(0,1000):''")
    print(f"Page: {text[:500]}", flush=True)

    # Click first product detail
    r = await tab.evaluate("""(function(){
        var links=document.querySelectorAll('a');
        for(var i=0;i<links.length;i++){var t=links[i].textContent||'';
            if(t.includes('编辑')||t.includes('查看')||t.includes('详情')){links[i].click();return 'link:'+t;}}
        var rows=document.querySelectorAll('tr[data-row-key],.ant-table-row');
        if(rows.length>0){var l=rows[0].querySelector('a');if(l){l.click();return 'row_link';}rows[0].click();return 'row_click';}
        return 'nothing';
    })()""")
    print(f"Click: {r}", flush=True)
    if r != "nothing":
        await tab.sleep(15)

    # 2. Category page
    print("\n=== Category list ===", flush=True)
    await tab.evaluate(
        "window.location.hash='#/unifiedGoods/tenant/storeCategory-list';window.dispatchEvent(new HashChangeEvent('hashchange'))"
    )
    await tab.sleep(10)

    # 3. Try order page
    print("\n=== Orders ===", flush=True)
    await tab.evaluate(
        "window.location.hash='#/orderManagement/orderList';window.dispatchEvent(new HashChangeEvent('hashchange'))"
    )
    await tab.sleep(10)

    await tab.sleep(3)

    # Report
    print(f"\n{'=' * 70}", flush=True)
    print(f"CAPTURED {len(captured)} APIs:", flush=True)
    print(f"{'=' * 70}", flush=True)
    seen = set()
    for a in captured:
        path = a["url"].split("?")[0].replace(QNH, "")
        k = f"{a['method']} {path}"
        if k not in seen:
            seen.add(k)
            print(f"  {k} [{a.get('status', '?')}] {len(a.get('responseBody', ''))}b", flush=True)

    # Save report
    lines = [
        "# QNH Product API Capture - VERIFIED",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Total: {len(captured)}",
        "",
    ]
    for a in captured:
        path = a["url"].split("?")[0].replace(QNH, "")
        lines.append(f"## `{a['method']} {path}` [{a.get('status', '?')}]")
        lines.append(f"Full URL: `{a['url'][:300]}`")
        if a.get("postData"):
            lines += ["**Request:**", "```json"]
            try:
                lines.append(
                    json.dumps(json.loads(a["postData"]), indent=2, ensure_ascii=False)[:3000]
                )
            except:
                lines.append(a["postData"][:3000])
            lines += ["```"]
        if a.get("responseBody"):
            lines += ["**Response:**", "```json"]
            try:
                lines.append(
                    json.dumps(json.loads(a["responseBody"]), indent=2, ensure_ascii=False)[:5000]
                )
            except:
                lines.append(a["responseBody"][:3000])
            lines += ["```"]
        lines.append("---")
    Path("docs/product-api-capture.md").write_text("\n".join(lines))
    print("\nReport: docs/product-api-capture.md", flush=True)

    # Save ALL cookies (not just meituan.com domain)
    try:
        cs = await tab.send(n.get_all_cookies())
        cl = cs[0] if isinstance(cs, tuple) else cs
        cd = {}
        for c in cl:
            if hasattr(c, "name") and hasattr(c, "value"):
                d = getattr(c, "domain", "") or ""
                if "meituan" in d or "dianping" in d or "sankuai" in d:
                    cd[f"{d}:{c.name}"] = c.value
        Path("config").mkdir(exist_ok=True)
        Path("config/qnh_cookies_full.json").write_text(json.dumps(cd, indent=2))
        print(f"Saved {len(cd)} cookies (all domains)", flush=True)
    except Exception as e:
        print(f"Cookie err: {e}", flush=True)


async def main():
    import nodriver as uc

    print("Starting...", flush=True)
    browser = await uc.start(
        headless=False,
        user_data_dir=PROFILE,
        browser_args=["--no-first-run", "--no-default-browser-check", "--no-sandbox"],
    )

    # Check login state
    tab = await browser.get(QNH + "/home.html")
    await tab.sleep(8)
    url = await tab.evaluate("window.location.href")
    print(f"URL: {url}", flush=True)

    if "login" in url.lower():
        print("Need login...", flush=True)
        tab = await login(browser)
        if not tab:
            print("FAILED", flush=True)
            browser.stop()
            return
        # After login, navigate to home
        tab = await browser.get(QNH + "/home.html")
        await tab.sleep(8)
    else:
        print("Already logged in!", flush=True)
        # Wait for SPA to load
        await tab.sleep(5)
        text = await tab.evaluate("document.body?document.body.innerText.substring(0,300):''")
        print(f"Home: {text[:200]}", flush=True)

    await capture_apis(tab)
    browser.stop()
    print("DONE", flush=True)


asyncio.run(main())
