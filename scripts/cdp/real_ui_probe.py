#!/usr/bin/env python3
# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only probe of the real Stake keno game UI over raw CDP."""
import asyncio
import base64
import json
import sys
import urllib.request

import websockets

CDP = "http://127.0.0.1:9222"


def http_json(url):
    with urllib.request.urlopen(url, timeout=6) as resp:
        return json.loads(resp.read().decode("utf-8"))


JS = r"""
(() => {
  const t = (e) => (e.innerText || '').trim();
  let ctrl = null;
  for (const e of document.querySelectorAll('div,section,aside')) {
    const x = t(e);
    if (x.includes('手动投注') && x.includes('投注额') && x.length < 1500) { ctrl = e; break; }
  }
  const ctrlText = ctrl ? t(ctrl).slice(0, 800) : '(not found)';
  const ctrlButtons = ctrl ? [...ctrl.querySelectorAll('button')].map(b => t(b)).filter(Boolean).slice(0, 30) : [];
  const cells = [...document.querySelectorAll('button')].filter(b => {
    const x = t(b);
    return /^\d{1,2}$/.test(x) && Number(x) >= 1 && Number(x) <= 40;
  });
  const sample = cells.slice(0, 3).map(b => {
    const cs = getComputedStyle(b);
    return {n: t(b), bg: cs.backgroundColor, color: cs.color, radius: cs.borderRadius, font: cs.fontSize};
  });
  let bar = null;
  for (const e of document.querySelectorAll('div')) {
    const x = t(e);
    if (x.includes('公平性') && x.length < 80) { bar = e.parentElement; break; }
  }
  const barButtons = bar ? [...bar.querySelectorAll('button')].map(b => (b.getAttribute('aria-label') || t(b) || '(icon)')).slice(0, 14) : [];
  const inputs = [...document.querySelectorAll('input')].slice(0, 8).map(i => ({value: i.value, ph: i.placeholder}));
  const selects = [...document.querySelectorAll('select')].map(s => ({v: s.value, opts: [...s.options].map(o => o.text).slice(0, 8)}));
  return {ctrlText, ctrlButtons, cellCount: cells.length, sample, barButtons, inputs, selects, url: location.href};
})()
"""


async def main() -> int:
    targets = http_json(f"{CDP}/json/list")
    page = next(
        (x for x in targets if x.get("type") == "page" and "casino/games/keno" in (x.get("url") or "")),
        None,
    )
    if page is None:
        print("no keno page target")
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
            out = "/tmp/opencode/real_keno_cdp.jpg"
            with open(out, "wb") as fh:
                fh.write(base64.b64decode(data))
            print("screenshot saved:", out, len(data), "b64 chars")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
