from __future__ import annotations

"""Connect the local bot to a real Stake.com Chrome session.

Uses the already-logged-in CDP profile when possible. If the tab shows a
login wall, it opens the login UI and waits for the user to finish captcha.
Tokens never go to disk or logs.
"""

import asyncio
import time
from decimal import Decimal

from .ledger import read_records, viability
from .stake_cdp import (
    DEFAULT_CDP,
    KENO_URL,
    Cdp,
    cdp_up,
    create_keno_target,
    ensure_cdp,
    find_stake_page,
    gql,
    page_challenge,
    sniff_auth_headers,
)

USER_QUERY = (
    "query LiveUser { user { id name "
    "activeClientSeed { seed } "
    "activeServerSeed { nonce seedHash nextSeedHash } "
    "balances { available { amount currency } } } }"
)

BET_LIST_QUERY = (
    "query MyBetList($offset: Int = 0, $limit: Int = 50) { user { id "
    "houseBetList(offset: $offset, limit: $limit) { "
    "id iid type game { name slug } "
    "bet { ... on CasinoBet { id payoutMultiplier amount payout updatedAt currency game } } } } }"
)

LOGIN_JS = r"""
(() => {
  const text = (el) => (el && (el.innerText || el.textContent) || '').trim();
  const nodes = [...document.querySelectorAll('button,a')];
  const login = nodes.find((el) => /^(log in|login|sign in|登录)$/i.test(text(el)) && text(el).length < 24);
  const userChip = nodes.find((el) => /wallet|wallet|余额|vault|保险库/i.test(text(el)))
    || document.querySelector('[data-testid="user-menu"], [href*="/settings/account"]');
  return {
    url: location.href,
    title: document.title,
    loginText: login ? text(login) : null,
    hasUserChrome: Boolean(userChip),
    bodyStart: (document.body && document.body.innerText || '').slice(0, 240)
  };
})()
"""

CLICK_LOGIN_JS = r"""
(() => {
  const text = (el) => (el && (el.innerText || el.textContent) || '').trim();
  const login = [...document.querySelectorAll('button,a')].find((el) =>
    /^(log in|login|sign in|登录)$/i.test(text(el)) && text(el).length < 24
  );
  if (!login) return {clicked: false};
  login.click();
  return {clicked: true, text: text(login)};
})()
"""

PAGE_BALANCE_JS = r"""
(() => {
  const blob = (document.body && document.body.innerText) || '';
  const match = blob.match(/([0-9]+\.[0-9]{4,8})\s*USDT/i);
  return match ? match[1] : null;
})()
"""

# In-memory only. Never serialize this dict to disk.
_AUTH_HEADERS: dict | None = None
_LIVE_STATUS: dict = {
    "status": "disconnected",
    "user_id": None,
    "user_name": None,
    "balances": [],
    "currency": None,
    "balance": None,
    "balance_page": None,
    "balance_mismatch": None,
    "synced_at": None,
    "nonce": None,
    "server_seed_hash": None,
    "page": None,
    "error": None,
    "need_login": False,
    "connected_at": None,
    "target_id": None,
    "client_seed": None,
    "next_server_seed_hash": None,
    "challenge": False,
    "viability": None,
    "recent_bets": [],
}


def live_status() -> dict:
    return dict(_LIVE_STATUS)


def auth_headers() -> dict | None:
    return _AUTH_HEADERS


def public_status() -> dict:
    """Safe to send to the web UI: no tokens."""
    data = live_status()
    data.pop("error_detail", None)
    return data


def mark_error(message: str) -> dict:
    return _set_status(status="error", error=message, need_login=False)


def _set_status(**kwargs) -> dict:
    _LIVE_STATUS.update(kwargs)
    return live_status()


def money_str(value) -> str | None:
    """Format a Stake amount without float junk. 8 decimal places like the cashier."""
    if value is None or value == "":
        return None
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    text = format(number.quantize(Decimal("0.00000001")), "f")
    if "." in text:
        whole, frac = text.split(".", 1)
        frac = (frac + "00000000")[:8]
        text = f"{whole}.{frac}"
    return text


def _normalize_balances(raw) -> list[dict]:
    rows: list[dict] = []
    if isinstance(raw, dict):
        raw = raw.get("available") or raw.get("list") or []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, dict):
            continue
        if "amount" in item and "currency" in item:
            rows.append({"amount": money_str(item.get("amount")), "currency": item.get("currency")})
        elif isinstance(item.get("available"), dict):
            inner = item["available"]
            rows.append(
                {
                    "amount": money_str(inner.get("amount")),
                    "currency": inner.get("currency") or item.get("currency"),
                }
            )
    return rows


def _pick_balance(balances: list[dict]) -> tuple[str | None, str | None]:
    if not balances:
        return None, None
    preferred = ("usdt", "usd", "usdc")
    by_currency = {str(row.get("currency") or "").lower(): row for row in balances}
    for key in preferred:
        if key in by_currency:
            row = by_currency[key]
            return money_str(row.get("amount")), str(row.get("currency"))
    row = balances[0]
    return money_str(row.get("amount")), str(row.get("currency"))


def to_stake_numbers(picks_1_based: list[int]) -> list[int]:
    numbers = []
    for n in picks_1_based:
        if not 1 <= int(n) <= 40:
            raise ValueError(f"keno number out of range: {n}")
        numbers.append(int(n) - 1)
    if len(set(numbers)) != len(numbers):
        raise ValueError("duplicate keno numbers")
    return numbers


def from_stake_numbers(numbers_0_based: list[int]) -> list[int]:
    return [int(n) + 1 for n in numbers_0_based]


async def _connect_async(cdp: str, wait_login: float) -> dict:
    global _AUTH_HEADERS
    if not cdp_up(cdp):
        _set_status(status="opening", error="正在启动猎手 Chrome（9222）…", need_login=False)
        if not ensure_cdp(cdp):
            return _set_status(
                status="error",
                error="CDP Chrome 未启动。已尝试拉起 Chrome，9222 仍无响应。",
                need_login=False,
            )
    _set_status(status="opening", error=None, need_login=False, page=KENO_URL, challenge=False)
    page = await create_keno_target(cdp, force_new=True)
    import websockets

    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None, open_timeout=12) as ws:
        client = Cdp(ws)
        await client.call("Network.enable")
        await client.call("Page.enable")
        await client.call("Page.bringToFront")
        await asyncio.sleep(3.0)
        challenge = await page_challenge(client)
        if challenge.get("challenge"):
            _set_status(
                status="need_login",
                need_login=True,
                challenge=True,
                target_id=page.get("id"),
                page=challenge.get("href") or page.get("url"),
                error="Stake 风控页（Cloudflare/Kasada）。请在新开的 Chrome 标签里过完挑战，不要关那个窗口。",
            )
            deadline = time.time() + max(20.0, wait_login)
            while time.time() < deadline:
                await asyncio.sleep(5)
                challenge = await page_challenge(client)
                if not challenge.get("challenge"):
                    break
            else:
                return live_status()
        snapshot = await client.evaluate(LOGIN_JS)
        headers = None
        try:
            headers = await sniff_auth_headers(client, timeout=20, reload_page=False)
        except Exception:
            headers = None
        if headers is None:
            await client.evaluate(CLICK_LOGIN_JS)
            _set_status(
                status="need_login",
                need_login=True,
                challenge=False,
                target_id=page.get("id"),
                page=(snapshot or {}).get("url") if isinstance(snapshot, dict) else page.get("url"),
                error="新开的 Stake 标签未登录。请在那个窗口完成登录（验证码要你点），不要用本地全自动页。",
            )
            deadline = time.time() + max(15.0, wait_login)
            while time.time() < deadline:
                await asyncio.sleep(4)
                try:
                    headers = await sniff_auth_headers(client, timeout=10, reload_page=False)
                except Exception:
                    headers = None
                if headers:
                    break
            if headers is None:
                return live_status()
        _AUTH_HEADERS = headers
        return await _apply_user_snapshot(client, headers, page)


async def _apply_user_snapshot(client, headers: dict, page: dict) -> dict:
    data = await gql(client, headers, USER_QUERY, {})
    user = data.get("user") or {}
    if not user.get("id"):
        return _set_status(
            status="need_login",
            need_login=True,
            target_id=page.get("id"),
            error="新标签已打开但没有用户。请在 Chrome 里登录账号。",
        )
    available = _normalize_balances(user.get("balances"))
    amount, currency = _pick_balance(available)
    nonzero = []
    for row in available:
        try:
            if Decimal(str(row.get("amount") or "0")) != 0:
                nonzero.append({"amount": money_str(row.get("amount")), "currency": row.get("currency")})
        except Exception:
            continue
    if currency and amount and not any(str(r.get("currency")).lower() == str(currency).lower() for r in nonzero):
        nonzero.insert(0, {"amount": money_str(amount), "currency": currency})
    server = user.get("activeServerSeed") or {}
    client_seed = (user.get("activeClientSeed") or {}).get("seed")
    recent = []
    try:
        bets_data = await gql(client, headers, BET_LIST_QUERY, {"offset": 0, "limit": 50})
        nodes = ((bets_data.get("user") or {}).get("houseBetList")) or []
        keno_nodes = [n for n in nodes if ((n.get("game") or {}).get("slug") == "keno")]
        for node in keno_nodes[:20]:
            casino = node.get("bet") or {}
            bet_amt = Decimal(str(casino.get("amount") or "0"))
            payout = Decimal(str(casino.get("payout") or "0"))
            recent.append(
                {
                    "iid": node.get("iid") or casino.get("id"),
                    "amount": money_str(casino.get("amount")),
                    "payout": money_str(casino.get("payout")),
                    "multiplier": str(casino.get("payoutMultiplier")),
                    "currency": casino.get("currency"),
                    "updated_at": casino.get("updatedAt"),
                    "win": payout > bet_amt,
                }
            )
    except Exception:
        recent = []
    page_balance = None
    try:
        raw = await client.evaluate(PAGE_BALANCE_JS, timeout=8)
        page_balance = money_str(raw) if raw else None
    except Exception:
        page_balance = None
    live_rows = read_records("live")
    live_for_streak = (
        [{"bet": r["amount"], "payout": r["payout"]} for r in reversed(recent)]
        if recent
        else live_rows
    )
    verdict = viability(live_for_streak, read_records("paper"))
    mismatch = None
    if page_balance and amount and money_str(page_balance) != money_str(amount):
        mismatch = f"GraphQL {money_str(amount)} {currency} · 页面 {page_balance} USDT"
    return _set_status(
        status="connected",
        need_login=False,
        challenge=False,
        error=None,
        user_id=user.get("id"),
        user_name=user.get("name"),
        balances=nonzero[:8],
        currency=currency,
        balance=money_str(amount),
        balance_page=page_balance,
        balance_mismatch=mismatch,
        nonce=server.get("nonce"),
        server_seed_hash=(server.get("seedHash") or "")[:16],
        next_server_seed_hash=(server.get("nextSeedHash") or "")[:16],
        client_seed=client_seed,
        page=page.get("url"),
        target_id=page.get("id"),
        connected_at=_LIVE_STATUS.get("connected_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
        synced_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        recent_bets=recent,
        viability=verdict,
    )


async def _refresh_async(cdp: str) -> dict:
    if _AUTH_HEADERS is None or _LIVE_STATUS.get("status") != "connected":
        return _set_status(status="error", error="还没连上，请先在实盘台点连接")
    page = find_stake_page(cdp, target_id=_LIVE_STATUS.get("target_id"))
    if page is None:
        return _set_status(status="error", error="Stake 标签不见了，请重新连接")
    import websockets

    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None, open_timeout=12) as ws:
        client = Cdp(ws)
        return await _apply_user_snapshot(client, _AUTH_HEADERS, page)


def connect_stake(cdp: str = DEFAULT_CDP, wait_login: float = 180.0) -> dict:
    return asyncio.run(_connect_async(cdp, wait_login))


def refresh_stake(cdp: str = DEFAULT_CDP) -> dict:
    return asyncio.run(_refresh_async(cdp))


KENO_BET_MUTATION = """
mutation KenoBet($amount: Float!, $currency: CurrencyEnum!, $identifier: String, $risk: CasinoGameKenoRiskEnum!, $numbers: [Int!]!) {
  kenoBet(amount: $amount, currency: $currency, identifier: $identifier, risk: $risk, numbers: $numbers) {
    id
    active
    payoutMultiplier
    amountMultiplier
    amount
    payout
    updatedAt
    currency
    game
    user { id name }
    state {
      ... on CasinoGameKeno {
        drawnNumbers
        selectedNumbers
        risk
      }
    }
  }
}
"""


def _nonce_and_balance(user: dict, currency: str) -> tuple[int | None, str | None]:
    server = (user or {}).get("activeServerSeed") or {}
    nonce = server.get("nonce")
    try:
        nonce = int(nonce) if nonce is not None else None
    except (TypeError, ValueError):
        nonce = None
    available = _normalize_balances((user or {}).get("balances"))
    amount, _cur = _pick_balance(available)
    key = str(currency or "").lower()
    if key:
        by_currency = {str(row.get("currency") or "").lower(): row for row in available}
        if key in by_currency:
            amount = money_str(by_currency[key].get("amount"))
    return nonce, amount


async def place_keno_bet_async(
    *,
    picks_1_based: list[int],
    amount: Decimal,
    currency: str,
    risk: str,
    identifier: str,
    cdp: str = DEFAULT_CDP,
) -> dict:
    if _AUTH_HEADERS is None:
        raise RuntimeError("not connected; run connect first")
    page = find_stake_page(cdp, target_id=_LIVE_STATUS.get("target_id"))
    if page is None:
        raise RuntimeError("Stake 专用标签不见了，请在实盘页重新连接")
    import websockets

    numbers = to_stake_numbers(picks_1_based)
    variables = {
        "amount": float(amount),
        "currency": str(currency).lower(),
        "identifier": identifier,
        "risk": str(risk).lower(),
        "numbers": numbers,
    }
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None, open_timeout=12) as ws:
        client = Cdp(ws)
        await client.call("Runtime.enable")
        before = ((await gql(client, _AUTH_HEADERS, USER_QUERY, {})) or {}).get("user") or {}
        nonce_before, balance_before = _nonce_and_balance(before, currency)
        data = await gql(client, _AUTH_HEADERS, KENO_BET_MUTATION, variables, timeout=40, operation_name="KenoBet")
        bet = data.get("kenoBet") or {}
        state = bet.get("state") or {}
        bet_id = bet.get("id")
        drawn = state.get("drawnNumbers") or []
        if not bet_id:
            raise RuntimeError("Stake 未返回注单 id，资金未动")
        if not drawn:
            raise RuntimeError("Stake 未返回开奖号码，注单无效")
        after = ((await gql(client, _AUTH_HEADERS, USER_QUERY, {})) or {}).get("user") or {}
        nonce_after, balance_after = _nonce_and_balance(after, currency)
        on_book = False
        try:
            listed = await gql(client, _AUTH_HEADERS, BET_LIST_QUERY, {"offset": 0, "limit": 10})
            nodes = ((listed.get("user") or {}).get("houseBetList")) or []
            on_book = any((node.get("bet") or {}).get("id") == bet_id or node.get("id") == bet_id for node in nodes)
        except Exception:
            on_book = False
    nonce_moved = nonce_before is not None and nonce_after is not None and nonce_after != nonce_before
    balance_moved = bool(balance_before and balance_after and balance_before != balance_after)
    confirmed = bool(on_book or nonce_moved or balance_moved)
    if not confirmed:
        raise RuntimeError("Stake 未入账：nonce、余额、注单列表都没变")
    _LIVE_STATUS["balance"] = balance_after or _LIVE_STATUS.get("balance")
    _LIVE_STATUS["nonce"] = nonce_after if nonce_after is not None else _LIVE_STATUS.get("nonce")
    _LIVE_STATUS["synced_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "iid": bet_id,
        "amount": money_str(bet.get("amount") or amount),
        "payout": money_str(bet.get("payout") or "0"),
        "payout_multiplier": str(bet.get("payoutMultiplier") or "0"),
        "nonce": nonce_after,
        "nonce_before": nonce_before,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "confirmed": True,
        "on_book": on_book,
        "currency": bet.get("currency") or currency,
        "risk": state.get("risk"),
        "selected": from_stake_numbers(state.get("selectedNumbers") or numbers),
        "drawn": from_stake_numbers(drawn),
    }


def place_keno_bet(**kwargs) -> dict:
    return asyncio.run(place_keno_bet_async(**kwargs))
