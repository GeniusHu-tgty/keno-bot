#!/usr/bin/env python3
# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
"""Validate: CDP header sniff -> in-page GraphQL replay for stake.com.

1. Connect to the stake.com page target over CDP (WSL -> Windows Chrome).
2. Enable Network, reload the page, sniff the first authenticated
   /_api/graphql request's headers (x-access-token etc.).
3. Replay a UserSeedPair query from inside the page using those headers.
Token values never leave memory; stdout carries metadata only.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

CDP = "http://127.0.0.1:9222"


def http_json(url):
    with urllib.request.urlopen(url, timeout=6) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def main() -> int:
    targets = http_json(f"{CDP}/json/list")
    page = next(
        (t for t in targets if t.get("type") == "page" and "stake.com" in (t.get("url") or "")),
        None,
    )
    if page is None:
        print(json.dumps({"ok": False, "err": "no stake.com page target"}))
        return 2
    ws_url = page["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, max_size=None, open_timeout=8) as ws:
        mid = [0]

        async def send(method, params=None):
            mid[0] += 1
            await ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
            return mid[0]

        async def wait_for(my_id, timeout=30):
            loop = asyncio.get_event_loop()
            deadline = loop.time() + timeout
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError(f"wait_for {my_id}")
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
                if msg.get("id") == my_id:
                    if "error" in msg:
                        raise RuntimeError(str(msg["error"]))
                    return msg.get("result", {})
                # else: event, ignore here

        await wait_for(await send("Network.enable"))
        await wait_for(await send("Page.enable"))
        await wait_for(await send("Page.reload", {"ignoreCache": True}), timeout=10)

        # sniff app-originated authenticated graphql request
        headers = None
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 40
        while loop.time() < deadline and headers is None:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except asyncio.TimeoutError:
                continue
            if msg.get("method") == "Network.requestWillBeSent":
                req = msg["params"]["request"]
                if "graphql" in req.get("url", "").lower():
                    h = req.get("headers", {}) or {}
                    tok = h.get("x-access-token") or h.get("X-Access-Token")
                    if tok:
                        headers = h
                        break

        if headers is None:
            print(json.dumps({"ok": False, "step": "sniff", "err": "no authenticated graphql request captured in 40s"}))
            return 3

        print(json.dumps({
            "ok": True,
            "step": "sniff",
            "header_keys": sorted(headers.keys()),
            "x_access_token_len": len(headers.get("x-access-token", "")),
            "x_lockdown_token_len": len(headers.get("x-lockdown-token", "")),
        }, ensure_ascii=False))

        # build replay JS with sniffed headers (values stay in memory)
        keep = ("x-access-token", "x-lockdown-token", "x-language", "x-user-agent")
        hdr = {k: v for k, v in headers.items() if k.lower() in keep}
        hdr["content-type"] = "application/json"

        js = (
            "(async () => {"
            "  const r = await fetch('/_api/graphql', {"
            "    method: 'POST',"
            "    headers: " + json.dumps(hdr) + ","
            "    body: JSON.stringify({query: 'query UserSeedPair { user { id activeClientSeed { id seed } activeServerSeed { id nonce seedHash nextSeedHash } } }', variables: {}})"
            "  });"
            "  const t = await r.text();"
            "  return {status: r.status, body: t.slice(0, 800)};"
            "})()"
        )

        res = await wait_for(await send("Runtime.evaluate", {
            "expression": js, "awaitPromise": True, "returnByValue": True,
        }), timeout=30)
        val = (res.get("result") or {}).get("value")
        print(json.dumps({"ok": True, "step": "replay", "result": val}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
