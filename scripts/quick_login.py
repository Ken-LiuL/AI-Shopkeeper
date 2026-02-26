#!/usr/bin/env python3
"""Quick login with SMS code - run with: python3 scripts/quick_login.py <CODE>"""

import asyncio
import base64
import json
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

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

CODE = sys.argv[1] if len(sys.argv) > 1 else None

SKIP = {
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
    if p.hostname in SKIP:
        return False
    path = p.path.lower()
    if any(
        path.endswith(e)
        for e in [".js", ".css", ".png", ".jpg", ".gif", ".svg", ".woff", ".woff2", ".ttf", ".ico"]
    ):
        return False
    if "/s3webstatic/" in path or "/static/" in path:
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


async def do_slider(tab):
    import nodriver.cdp.input_ as inp

    await tab.sleep(2)
    try:
        pos = json.loads(
            await tab.evaluate(
                "(function(){var b=document.getElementById('yodaBox').getBoundingClientRect();"
                "var w=document.getElementById('yodaBoxWrapper').getBoundingClientRect();"
                "return JSON.stringify({bx:b.x,by:b.y,bw:b.width,bh:b.height,wx:w.x,ww:w.width})})()"
            )
        )
        sx, sy = pos["bx"] + pos["bw"] / 2, pos["by"] + pos["bh"] / 2
        ex = pos["wx"] + pos["ww"] - 5
        await tab.send(
            inp.dispatch_mouse_event(
                type_="mousePressed", x=sx, y=sy, button=inp.MouseButton("left"), click_count=1
            )
        )
        await tab.sleep(0.15)
        for i in range(1, 36):
            p = i / 35
            ep = 1 - (1 - p) ** 2.5
            await tab.send(
                inp.dispatch_mouse_event(
                    type_="mouseMoved",
                    x=sx + (ex - sx) * ep,
                    y=sy + random.uniform(-1, 1),
                    button=inp.MouseButton("left"),
                )
            )
            await tab.sleep(0.015 + random.uniform(0, 0.025))
        await tab.send(
            inp.dispatch_mouse_event(
                type_="mouseReleased", x=ex, y=sy, button=inp.MouseButton("left"), click_count=1
            )
        )
        print("Slider OK", flush=True)
    except Exception as e:
        print(f"Slider err: {e}", flush=True)


async def run():
    import nodriver as uc
    import nodriver.cdp.network as net
    import nodriver.cdp.page as page_cdp

    print("Starting...", flush=True)
    browser = await uc.start(
        headless=False,
        user_data_dir=PROFILE,
        browser_args=["--no-first-run", "--no-default-browser-check", "--no-sandbox"],
    )

    tab = await browser.get(EPASSPORT)
    await tab.sleep(6)

    # Fill credentials
    await tab.evaluate(
        '(function(){var i=document.querySelectorAll("input");var a,p;'
        'for(var x=0;x<i.length;x++){if(i[x].type==="password")p=i[x];'
        'else if(i[x].type==="text"||i[x].type==="tel")a=i[x];}'
        'var s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set;'
        f's.call(a,"{U}");a.dispatchEvent(new Event("input",{{bubbles:true}}));'
        f's.call(p,"{P}");p.dispatchEvent(new Event("input",{{bubbles:true}}));'
        'var c=document.querySelectorAll("input[type=checkbox]");'
        "for(var x=0;x<c.length;x++){if(!c[x].checked)c[x].click();}})()"
    )
    await tab.sleep(1)

    # Click login button
    await tab.evaluate(
        'document.querySelectorAll("button").forEach(function(b){'
        'if(b.textContent.includes("登录"))b.click()})'
    )
    print("Login clicked", flush=True)

    # Wait for slider
    for i in range(15):
        await tab.sleep(1)
        if await tab.evaluate("!!document.getElementById('yodaBox')"):
            print(f"Slider at {i + 1}s", flush=True)
            await do_slider(tab)
            break

    await tab.sleep(5)
    text = await tab.evaluate("document.body.innerText.substring(0,500)")

    if "验证码" not in text or "手机" not in text:
        url = await tab.evaluate("window.location.href")
        if "login" not in url.lower():
            print(f"Already logged in: {url}", flush=True)
        else:
            print(f"Unexpected: {text[:200]}", flush=True)
            browser.stop()
            return

    if CODE:
        # We have a code - enter it immediately
        # First click "获取验证码" to request SMS
        print("Requesting SMS...", flush=True)
        await tab.evaluate(
            'document.querySelectorAll("button,span,div").forEach(function(e){'
            'if((e.textContent||"").trim()==="获取验证码"&&e.offsetHeight>0)e.click()})'
        )
        await tab.sleep(3)

        # Check for slider again (SMS request might trigger another slider)
        for i in range(10):
            if await tab.evaluate("!!document.getElementById('yodaBox')"):
                print("Slider for SMS...", flush=True)
                await do_slider(tab)
                await tab.sleep(3)
                break
            await tab.sleep(1)

        await tab.sleep(2)

        # Enter SMS code
        print(f"Entering code: {CODE}", flush=True)
        await tab.evaluate(
            '(function(){var inputs=document.querySelectorAll("input");'
            "for(var i=0;i<inputs.length;i++){"
            'var ph=(inputs[i].placeholder||"").toLowerCase();'
            'if(ph.includes("验证码")||ph.includes("code")){'
            'var s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set;'
            f's.call(inputs[i],"{CODE}");'
            'inputs[i].dispatchEvent(new Event("input",{bubbles:true}));'
            'inputs[i].dispatchEvent(new Event("change",{bubbles:true}));'
            'return "ok";}}'
            'return "not_found";})()'
        )
        await tab.sleep(1)

        # Click the "验证" button (NOT "获取验证码")
        print("Clicking verify...", flush=True)
        await tab.evaluate(
            '(function(){var btns=document.querySelectorAll("button");'
            "for(var i=0;i<btns.length;i++){"
            'var t=(btns[i].textContent||"").trim();'
            'if(t==="验证"){btns[i].click();return "ok";}}'
            'return "not_found";})()'
        )

        # Wait for redirect
        for i in range(30):
            await tab.sleep(1)
            url = await tab.evaluate("window.location.href")
            if "login" not in url.lower():
                print(f"LOGIN SUCCESS at {i + 1}s: {url}", flush=True)
                break
        else:
            t = await tab.evaluate("document.body.innerText.substring(0,300)")
            print(f"Failed: {t[:200]}", flush=True)
            browser.stop()
            return
    else:
        # No code - request SMS and wait
        await tab.evaluate(
            'document.querySelectorAll("button,span,div").forEach(function(e){'
            'if((e.textContent||"").trim()==="获取验证码"&&e.offsetHeight>0)e.click()})'
        )
        print("SMS sent, waiting 180s for manual entry...", flush=True)
        for i in range(180):
            await tab.sleep(1)
            url = await tab.evaluate("window.location.href")
            if "login" not in url.lower():
                print(f"LOGIN OK at {i + 1}s", flush=True)
                break
            if i % 20 == 19:
                print(f"  {i + 1}s...", flush=True)
        else:
            print("Timeout", flush=True)
            browser.stop()
            return

    # ===== CAPTURE APIS =====
    print("\n=== Capturing product APIs ===", flush=True)
    tab2 = await browser.get(f"{QNH}/home.html#/unifiedGoods/tenant/spu-list")
    await tab2.send(net.enable())

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
                body = (await tab2.send(net.get_response_body(net.RequestId(r))))[0]
            except:
                body = ""
            info = rmap.pop(r)
            info["responseBody"] = body
            captured.append(info)

    tab2.add_handler(net.RequestWillBeSent, on_req)
    tab2.add_handler(net.ResponseReceived, on_resp)
    tab2.add_handler(net.LoadingFinished, lambda e: asyncio.ensure_future(on_done(e)))

    print("Waiting 20s for SPU list to load...", flush=True)
    await tab2.sleep(20)

    # Screenshot
    ss = await tab2.send(page_cdp.capture_screenshot(format_="png"))
    Path("docs/product-page-screenshot.png").write_bytes(
        base64.b64decode(ss[0] if isinstance(ss, tuple) else ss)
    )
    text = await tab2.evaluate("document.body?document.body.innerText.substring(0,1000):''")
    print(f"Page: {text[:500]}", flush=True)

    # Click product edit/detail
    r = await tab2.evaluate(
        '(function(){var links=document.querySelectorAll("a");'
        'for(var i=0;i<links.length;i++){var t=links[i].textContent||"";'
        'if(t.includes("编辑")||t.includes("查看")||t.includes("详情")){'
        'links[i].click();return "link:"+t;}}'
        'return "nothing";})()'
    )
    print(f"Click: {r}", flush=True)
    if r != "nothing":
        await tab2.sleep(15)

    # Category
    print("\n=== Category ===", flush=True)
    await tab2.evaluate("window.location.hash='#/unifiedGoods/tenant/storeCategory-list'")
    await tab2.sleep(10)

    await tab2.sleep(3)

    # Summary
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
    print("\nReport saved to docs/product-api-capture.md", flush=True)

    # Save ALL cookies
    try:
        cs = await tab2.send(net.get_all_cookies())
        cl = cs[0] if isinstance(cs, tuple) else cs
        cd = {}
        for c in cl:
            if hasattr(c, "name") and hasattr(c, "value"):
                d = getattr(c, "domain", "") or ""
                if "meituan" in d or "dianping" in d or "sankuai" in d:
                    cd[f"{d}:{c.name}"] = c.value
        Path("config").mkdir(exist_ok=True)
        Path("config/qnh_cookies_full.json").write_text(json.dumps(cd, indent=2))
        print(f"Saved {len(cd)} cookies", flush=True)
    except Exception as e:
        print(f"Cookie err: {e}", flush=True)

    browser.stop()
    print("DONE", flush=True)


asyncio.run(run())
