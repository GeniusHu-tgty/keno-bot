#!/usr/bin/env python3
"""Read-only: pull kenoBet GraphQL snippets from the open Stake tab."""
from __future__ import annotations

import asyncio
import urllib.request

from keno.bot.stake_cdp import Cdp, DEFAULT_CDP, find_stake_page


JS = r"""
(async () => {
  const srcs = [...document.querySelectorAll('script[src]')].map(s => s.src);
  const keys = ['kenoBet', 'KenoBet', 'CasinoGameKeno', 'drawnNumbers'];
  const hits = [];
  for (const url of srcs) {
    let text = '';
    try {
      const r = await fetch(url, {credentials: 'include'});
      text = await r.text();
    } catch (e) {
      continue;
    }
    if (!keys.some((k) => text.includes(k))) continue;
    const idx = Math.max(...keys.map((k) => text.indexOf(k)).filter((i) => i >= 0));
    hits.push({url: url.slice(-140), snip: text.slice(Math.max(0, idx - 280), idx + 900)});
    if (hits.length >= 6) break;
  }
  return {scriptCount: srcs.length, hits};
})()
"""


async def main() -> int:
    page = find_stake_page(DEFAULT_CDP)
    print("page", None if page is None else page.get("url"))
    if page is None:
        return 2
    import websockets

    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None, open_timeout=8) as ws:
        client = Cdp(ws)
        result = await client.evaluate(JS, timeout=60, await_promise=True)
    print("scriptCount", (result or {}).get("scriptCount"))
    hits = (result or {}).get("hits") or []
    print("hits", len(hits))
    for hit in hits:
        print("URL", hit.get("url"))
        print(hit.get("snip"))
        print("---")
    return 0 if hits else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
