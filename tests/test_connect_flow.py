"""Regression tests for the 'click connect -> log in -> nothing happens' bug.

The bug: the token sniffing was passive only, so a tab that was already loaded and
logged in (the normal warm-profile case) never produced a request we could see, and
the connection stayed on "need_login" until it timed out.

These tests pin the two mechanisms that fix it: an active reload nudge issued from
inside the watching connection, and the choice of which open tab to attach to.
"""
from __future__ import annotations

import asyncio

import keno.bot.stake_cdp as stake_cdp
import keno.bot.stake_session as stake_session
from keno.bot.stake_cdp import sniff_auth_headers
from keno.bot.stake_session import _pick_stake_page


class _FakeWs:
    def __init__(self, messages):
        self._messages = list(messages)

    async def recv(self):
        await asyncio.sleep(0)
        if not self._messages:
            raise RuntimeError("fake websocket is empty")
        return self._messages.pop(0)


class _FakeCdp:
    def __init__(self, ws):
        self.ws = ws
        self.calls: list[str] = []

    async def call(self, method, params=None, timeout=30.0):
        self.calls.append(method)
        return {}


def _request(url: str, headers: dict) -> str:
    return _json_message({"method": "Network.requestWillBeSent", "params": {"request": {"url": url, "headers": headers}}})


def _json_message(payload: dict) -> str:
    import json

    return json.dumps(payload)


def test_sniff_reloads_the_tab_then_picks_up_the_token():
    ws = _FakeWs([
        _request("https://stake.com/_api/graphql", {}),  # noise, no token
        _request("https://stake.com/_api/graphql", {"x-access-token": "tok"}),
    ])
    client = _FakeCdp(ws)
    headers = asyncio.run(
        sniff_auth_headers(client, timeout=2.0, reload_after=0.0, max_reloads=1)
    )
    assert headers["x-access-token"] == "tok"
    assert "Page.reload" in client.calls, "a silent tab has to be woken up by a reload"


def test_sniff_never_reloads_without_a_nudge_request():
    """Reloading is opt-in: it would wipe a half-typed login form."""
    ws = _FakeWs([_request("https://stake.com/_api/graphql", {"x-access-token": "tok"})])
    client = _FakeCdp(ws)
    headers = asyncio.run(sniff_auth_headers(client, timeout=2.0))
    assert headers["x-access-token"] == "tok"
    assert client.calls == []


def test_pick_stake_page_prefers_the_keno_tab():
    pages = [
        {"id": "1", "url": "https://stake.com/casino/home"},
        {"id": "2", "url": "https://stake.com/casino/games/keno"},
    ]
    assert _pick_stake_page(pages)["id"] == "2"
    assert _pick_stake_page([{"id": "9", "url": "https://stake.com/"}])["id"] == "9"


def test_sniff_any_stake_tab_without_pages_returns_nothing():
    original = stake_cdp.list_pages
    stake_cdp.list_pages = lambda cdp=None: []
    try:
        headers, page = asyncio.run(stake_cdp.sniff_any_stake_tab(timeout=0.5))
    finally:
        stake_cdp.list_pages = original
    assert headers is None and page is None


def test_stake_session_uses_the_shared_sniffer():
    """The connect path must watch all tabs, not just the one it opened."""
    assert stake_session.sniff_any_stake_tab is stake_cdp.sniff_any_stake_tab
    assert stake_session.MAX_LOGIN_NUDGES >= 1
