# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

"""Stake.com keno collector over CDP — read-only.

Connects to a real Chrome (started with --remote-debugging-port, logged into
stake.com), sniffs the app's own x-access-token from its GraphQL traffic, then
replays read-only GraphQL queries from inside the page:

  MyBetList     house bet history (paged offset/limit, filtered to keno)
  KenoPreview   drawnNumbers / selectedNumbers / risk per bet
  BetVerify     nonce / clientSeed / serverSeed(seed + hash) per bet
  UserSeedPair  currently active seed pair snapshot

Outputs:
  <out>.jsonl             RoundRecord lines with seed fields (source=stake-cdp)
                          plus a "bet" side block (picks/risk/amount/payout)
  <out stem>.seeds.json   per-round verification data + active pair snapshot

Read-only by design: navigation, DOM/network reads and capture of
page-originated traffic only. No bets, no mutations.
"""

import asyncio
import json
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from .data.schema import RoundRecord, jsonable

DEFAULT_CDP = "http://127.0.0.1:9222"
_GQL_PATH = "/_api/graphql"


def is_graphql_url(url: str) -> bool:
    """True for any Stake GraphQL endpoint (/_api/graphql or /_api/v1/graphql)."""
    u = (url or "").lower()
    if "graphql" not in u:
        return False
    return "/_api/" in u or "/graphql" in u
_KEEP_HEADERS = ("x-access-token", "x-lockdown-token", "x-language", "x-user-agent")

QUERIES = {
    "UserSeedPair": (
        "query UserSeedPair { user { id "
        "activeClientSeed { id seed __typename } "
        "activeServerSeed { id nonce seedHash nextSeedHash __typename } "
        "__typename } }"
    ),
    "MyBetList": (
        "query MyBetList($offset: Int = 0, $limit: Int = 50) { user { id "
        "houseBetList(offset: $offset, limit: $limit) { "
        "__typename id iid type "
        "game { __typename name slug } "
        "bet { __typename ... on CasinoBet { id active payoutMultiplier "
        "amountMultiplier amount payout updatedAt currency game __typename } } } "
        "__typename } }"
    ),
    "KenoPreview": (
        "query KenoPreview($iid: String!) { bet(iid: $iid) { id iid bet { "
        "... on CasinoBet { ...CasinoBet state { __typename ...CasinoGameKeno } } } } } "
        "fragment CasinoBet on CasinoBet { __typename id active payoutMultiplier "
        "amountMultiplier amount payout updatedAt currency game user { __typename id name } } "
        "fragment CasinoGameKeno on CasinoGameKeno { drawnNumbers selectedNumbers risk }"
    ),
    "BetVerify": (
        "query BetVerify($iid: String!) { bet(iid: $iid) { __typename id iid type bet { "
        "__typename ... on CasinoBet { __typename id game nonce "
        "clientSeed { __typename id seed } "
        "serverSeed { __typename id seed seedHash } "
        "user { __typename id } } } } }"
    ),
}


def _http_json(url: str, timeout: float = 6.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _default_seeds_path(out_path: str | Path) -> Path:
    p = Path(out_path)
    return p.with_name(p.stem + ".seeds.json")


class _Cdp:
    """Minimal CDP client over a websocket."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self._next_id = 0

    async def send(self, method: str, params: dict | None = None) -> int:
        self._next_id += 1
        await self.ws.send(json.dumps({"id": self._next_id, "method": method, "params": params or {}}))
        return self._next_id

    async def wait(self, msg_id: int, timeout: float = 30.0) -> dict:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"cdp call {msg_id} timed out")
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=remaining))
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result", {})

    async def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return await self.wait(await self.send(method, params), timeout=timeout)


async def _sniff_auth_headers(client: _Cdp, timeout: float = 45.0) -> dict:
    """Reload the page and capture the headers of the app's first authenticated
    /_api/graphql request. Returns the raw header dict (values stay in memory)."""
    await client.call("Page.reload", {"ignoreCache": True}, timeout=10)
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            msg = json.loads(await asyncio.wait_for(client.ws.recv(), timeout=4))
        except asyncio.TimeoutError:
            continue
        if msg.get("method") != "Network.requestWillBeSent":
            continue
        req = msg["params"]["request"]
        if not is_graphql_url(req.get("url", "")):
            continue
        headers = req.get("headers") or {}
        if headers.get("x-access-token") or headers.get("X-Access-Token"):
            return headers
    raise RuntimeError("could not sniff x-access-token from page traffic; is the CDP Chrome logged into stake.com?")


async def _gql(client: _Cdp, headers: dict, query_name: str, variables: dict, timeout: float = 30.0) -> dict:
    """Replay a GraphQL query from inside the page with sniffed auth headers."""
    hdr = {k: v for k, v in headers.items() if k.lower() in _KEEP_HEADERS}
    hdr["content-type"] = "application/json"
    body = json.dumps({"query": QUERIES[query_name], "variables": variables})
    js = (
        "(async () => {"
        "  const r = await fetch('/_api/graphql', {"
        "    method: 'POST',"
        f"    headers: {json.dumps(hdr)},"
        f"    body: {json.dumps(body)}"
        "  });"
        "  const t = await r.text();"
        "  return {status: r.status, body: t};"
        "})()"
    )
    res = await client.call(
        "Runtime.evaluate",
        {"expression": js, "awaitPromise": True, "returnByValue": True},
        timeout=timeout,
    )
    value = (res.get("result") or {}).get("value")
    if not value or value.get("status") != 200:
        raise RuntimeError(f"{query_name} transport failure: {value}")
    payload = json.loads(value["body"])
    if payload.get("errors"):
        raise RuntimeError(f"{query_name} graphql errors: {payload['errors']}")
    return payload.get("data") or {}


async def _fetch_house_bets(client: _Cdp, headers: dict, page_size: int = 50, max_bets: int = 2000) -> list[dict]:
    bets: list[dict] = []
    offset = 0
    while True:
        data = await _gql(client, headers, "MyBetList", {"offset": offset, "limit": page_size})
        nodes = ((data.get("user") or {}).get("houseBetList")) or []
        bets.extend(nodes)
        if len(nodes) < page_size or len(bets) >= max_bets:
            break
        offset += page_size
        await asyncio.sleep(0.2)
    return [b for b in bets if ((b.get("game") or {}).get("slug") == "keno")]


def _assemble(iid: str, bet_node: dict, preview: dict, verify: dict) -> dict | None:
    """Build one round entry from the three per-bet payloads."""
    state = ((((preview.get("bet") or {}).get("bet")) or {}).get("state")) or {}
    # Stake's API reports 0-based board indices (0..39); the UI and this project use 1..40.
    numbers = [int(n) + 1 for n in (state.get("drawnNumbers") or [])]
    if not iid or len(numbers) != 10:
        return None

    casino = bet_node.get("bet") or {}
    vb = (verify.get("bet") or {}).get("bet") or {}
    client_seed = (vb.get("clientSeed") or {}).get("seed")
    server_seed = (vb.get("serverSeed") or {}).get("seed")
    server_seed_hash = (vb.get("serverSeed") or {}).get("seedHash")
    nonce = vb.get("nonce")

    updated = casino.get("updatedAt")
    try:
        ts = parsedate_to_datetime(updated) if updated else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        ts = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    record = RoundRecord(
        round_id=iid,
        timestamp=ts,
        numbers=numbers,
        server_seed_hash=server_seed_hash,
        server_seed=server_seed,
        client_seed=client_seed,
        nonce=nonce,
        cursor=0,
        source="stake-cdp",
    )
    extras = {
        "selected_numbers": [int(n) + 1 for n in (state.get("selectedNumbers") or [])],
        "risk": state.get("risk"),
        "bet_amount": casino.get("amount"),
        "payout": casino.get("payout"),
        "payout_multiplier": casino.get("payoutMultiplier"),
        "currency": casino.get("currency"),
    }
    line = {"type": "round", **jsonable(record), "bet": extras}
    seed = {
        "round_id": iid,
        "nonce": nonce,
        "client_seed": client_seed,
        "server_seed": server_seed,
        "server_seed_hash": server_seed_hash,
    }
    return {"line": line, "seed": seed}


def write_merged_jsonl(out_path: Path, lines: list[dict]) -> tuple[int, int]:
    """Merge round lines into the JSONL file, de-duplicated by round_id.
    Returns (total_rounds, newly_added)."""
    existing: dict[str, str] = {}
    order: list[str] = []
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rid = str(json.loads(line).get("round_id"))
            except json.JSONDecodeError:
                continue
            if rid not in existing:
                order.append(rid)
            existing[rid] = line
    added = 0
    for obj in lines:
        rid = str(obj.get("round_id"))
        if rid not in existing:
            order.append(rid)
            added += 1
        existing[rid] = json.dumps(obj, ensure_ascii=False)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for rid in order:
            f.write(existing[rid] + "\n")
    return len(order), added


async def _collect(cdp_url: str, page_size: int = 50, max_bets: int = 2000, gap: float = 0.15) -> dict:
    import websockets

    targets = _http_json(f"{cdp_url}/json/list")
    page = next(
        (t for t in targets if t.get("type") == "page" and "stake.com" in (t.get("url") or "")),
        None,
    )
    if page is None:
        raise RuntimeError(
            "no stake.com page found on the CDP endpoint; open stake.com in the CDP Chrome first"
        )
    ws_url = page["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, max_size=None, open_timeout=10) as ws:
        client = _Cdp(ws)
        version = _http_json(f"{cdp_url}/json/version")
        print(f"[collect --cdp] browser={version.get('Browser', '?')} page={page.get('url', '')}")
        await client.call("Network.enable")
        await client.call("Page.enable")
        headers = await _sniff_auth_headers(client)
        print(f"[collect --cdp] auth sniffed (x-access-token {len(headers.get('x-access-token', ''))} chars)")

        active = await _gql(client, headers, "UserSeedPair", {})
        bet_nodes = await _fetch_house_bets(client, headers, page_size, max_bets)
        print(f"[collect --cdp] keno bets found: {len(bet_nodes)}")

        rounds: list[dict] = []
        for node in bet_nodes:
            iid = str(node.get("iid") or "")
            preview = await _gql(client, headers, "KenoPreview", {"iid": iid})
            verify = await _gql(client, headers, "BetVerify", {"iid": iid})
            entry = _assemble(iid, node, preview, verify)
            if entry is None:
                print(f"[collect --cdp] skipped {iid}: missing draws")
                continue
            rounds.append(entry)
            revealed = "revealed" if entry["seed"]["server_seed"] else "unrevealed"
            print(
                f"[collect --cdp] round {iid}: nonce={entry['seed']['nonce']} "
                f"server_seed={revealed} draws={len(entry['line']['numbers'])}"
            )
            await asyncio.sleep(gap)

    return {"rounds": rounds, "active": active, "page": page.get("url", "")}


def collect_from_cdp(
    out_path: str | Path,
    cdp: str = DEFAULT_CDP,
    seeds_out: str | Path | None = None,
) -> int:
    try:
        import websockets  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "collect --cdp requires the 'websockets' package (pip install websockets)"
        ) from exc

    out = Path(out_path)
    seeds_path = Path(seeds_out) if seeds_out else _default_seeds_path(out)

    data = asyncio.run(_collect(cdp))
    rounds = data["rounds"]

    total, added = write_merged_jsonl(out, [r["line"] for r in rounds])

    active = data.get("active") or {}
    user = active.get("user") or {}
    active_pair = {
        "client_seed": ((user.get("activeClientSeed") or {}).get("seed")),
        "server_seed_hash": ((user.get("activeServerSeed") or {}).get("seedHash")),
        "active_nonce": ((user.get("activeServerSeed") or {}).get("nonce")),
        "next_server_seed_hash": ((user.get("activeServerSeed") or {}).get("nextSeedHash")),
    }
    payload = {
        "game": "keno",
        "source": "stake-cdp",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user.get("id"),
        "page": data.get("page"),
        "active_seed_pair": active_pair,
        "rounds": [r["seed"] for r in rounds],
    }
    seeds_path.parent.mkdir(parents=True, exist_ok=True)
    seeds_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    revealed = sum(1 for r in rounds if r["seed"]["server_seed"])
    print(f"[collect --cdp] rounds written: {len(rounds)} ({added} new, {total} total) -> {out}")
    print(f"[collect --cdp] seeds -> {seeds_path} (server seed revealed for {revealed}/{len(rounds)})")
    return len(rounds)
