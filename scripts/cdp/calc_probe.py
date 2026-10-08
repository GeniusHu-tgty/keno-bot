#!/usr/bin/env python3
# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only probe of the Stake provably-fair calculation page over raw CDP."""
import asyncio
import base64
import json
import sys
import urllib.request

import websockets

CDP = "http://127.0.0.1:9222"

JS = r"""
(() => {
  const t = document.body.innerText;
  const i = t.indexOf("客户端种子");
  const slice = i >= 0 ? t.slice(Math.max(0, i - 400), i + 2600) : t.slice(0, 2200);
  const inputs = [...document.querySelectorAll("input")].map(x => x.value).slice(0, 12);
  const selects = [...document.querySelectorAll("select")].map(s => s.value).slice(0, 4);
  return {slice, inputs, selects, url: location.href, title: document.title};
})()
"""


def http_json(url):
    with urllib.request.urlopen(url, timeout=6) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def main() -> int:
    targets = http_json(f"{CDP}/json/list")
    page = next(
        (x for x in targets if x.get("type") == "page" and "provably-fair/calculation" in (x.get("url") or "")),
        None,
    )
    if page is None:
        print("no calculation page found")
        return 2
    ws_url = page["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, max_size=None, open_timeout=8) as ws:
        mid = 0

        async def call(method, params=None, timeout=30):
            nonlocal mid
            mid += 1
            await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            loop = asyncio.get_event_loop()
            deadline = loop.time() + timeout
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError(method)
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(str(msg["error"]))
                    return msg.get("result", {})

        res = await call("Runtime.evaluate", {"expression": JS, "returnByValue": True}, timeout=25)
        val = (res.get("result") or {}).get("value")
        print(json.dumps(val, ensure_ascii=False, indent=1))

        shot = await call("Page.captureScreenshot", {"format": "jpeg", "quality": 85}, timeout=30)
        data = shot.get("data", "")
        if data:
            out = "/tmp/opencode/calc_real_page.jpg"
            with open(out, "wb") as fh:
                fh.write(base64.b64decode(data))
            print("screenshot saved:", out)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
