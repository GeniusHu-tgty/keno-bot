# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

"""CDP helpers for a real Stake.com tab.

Auth is sniffed from the page's own GraphQL traffic and replayed with
in-page fetch. Tokens stay in process memory and are never written to disk.
"""

import asyncio
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path

DEFAULT_CDP = "http://127.0.0.1:9222"
CHROME_PROFILE = Path(os.environ.get("KENO_CHROME_PROFILE") or (Path.home() / ".keno-bot" / "chrome-profile"))
CHROME_PS1 = Path(os.environ.get("KENO_CHROME_PS1") or (Path.home() / ".keno-bot" / "start-chrome.ps1"))
_CHROME_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)
KENO_URL = "https://stake.com/casino/games/keno"
_GQL_PATH = "/_api/graphql"
_KEEP_HEADERS = (
    "x-access-token",
    "x-lockdown-token",
    "x-language",
    "x-user-agent",
    "x-kpsdk-ct",
    "x-kpsdk-v",
    "x-kpsdk-h",
    "x-kpsdk-a",
    "x-kpsdk-d",
)


def http_json(url: str, timeout: float = 8.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cdp_up(cdp: str = DEFAULT_CDP) -> bool:
    try:
        http_json(f"{cdp.rstrip('/')}/json/version", timeout=2)
        return True
    except Exception:
        return False


def _chrome_exe() -> Path | None:
    for path in _CHROME_CANDIDATES:
        if path.exists():
            return path
    return None


def _wmi_launch_chrome() -> bool:
    browser = _chrome_exe()
    if browser is None:
        return False
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    command = (
        f'"{browser}" --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 '
        f'--remote-allow-origins=* --user-data-dir="{CHROME_PROFILE}" '
        "--no-first-run --no-default-browser-check --disable-session-crashed-bubble about:blank"
    )
    script = (
        "$c = '" + command.replace("'", "''") + "'; "
        "Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        "-Arguments @{ CommandLine = $c } | Out-Null"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            timeout=15,
            check=False,
            capture_output=True,
        )
        return True
    except Exception:
        return False


def ensure_cdp(cdp: str = DEFAULT_CDP) -> bool:
    """Start Chrome on 9222, outside this process job so it stays up."""
    if cdp_up(cdp):
        return True
    launched = False
    if CHROME_PS1.exists():
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(CHROME_PS1),
                ],
                timeout=40,
                check=False,
                capture_output=True,
            )
            launched = True
        except Exception:
            launched = False
    if not cdp_up(cdp):
        launched = _wmi_launch_chrome() or launched
    deadline = time.time() + 20
    while time.time() < deadline:
        if cdp_up(cdp):
            return True
        time.sleep(0.4)
    return cdp_up(cdp)


def list_pages(cdp: str = DEFAULT_CDP) -> list[dict]:
    targets = http_json(f"{cdp.rstrip('/')}/json/list")
    return [t for t in targets if t.get("type") == "page"]


def find_stake_page(cdp: str = DEFAULT_CDP, target_id: str | None = None) -> dict | None:
    pages = list_pages(cdp)
    if target_id:
        for page in pages:
            if page.get("id") == target_id:
                return page
    for page in pages:
        href = page.get("url") or ""
        if "stake.com" in href and "keno" in href.lower():
            return page
    for page in pages:
        if "stake.com" in (page.get("url") or ""):
            return page
    return None


def _put_json(url: str, timeout: float = 10.0) -> dict:
    request = urllib.request.Request(url, method="PUT")
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def open_keno_tab(cdp: str = DEFAULT_CDP, url: str = KENO_URL) -> dict | None:
    existing = find_stake_page(cdp)
    if existing and "keno" in (existing.get("url") or "").lower():
        return existing
    quoted = urllib.parse.quote(url, safe=":/")
    new_url = f"{cdp.rstrip('/')}/json/new?{quoted}"
    for opener in (_put_json, http_json):
        try:
            created = opener(new_url, timeout=10)
        except Exception:
            created = None
        if isinstance(created, dict) and created.get("webSocketDebuggerUrl"):
            return created
    return None


async def create_keno_target(cdp: str = DEFAULT_CDP, url: str = KENO_URL, force_new: bool = True) -> dict:
    """Open Stake Keno in a brand-new Chrome tab. Never hijack the local lab tab."""
    if not force_new:
        existing = open_keno_tab(cdp, url)
        if existing:
            return existing
    pages = [p for p in list_pages(cdp) if "127.0.0.1:8000" not in (p.get("url") or "") and "localhost:8000" not in (p.get("url") or "")]
    if not pages:
        pages = list_pages(cdp)
    if not pages:
        raise RuntimeError("CDP has no page to spawn a Stake tab from")
    host = next((p for p in pages if p.get("webSocketDebuggerUrl")), pages[0])
    import time
    import websockets

    async with websockets.connect(host["webSocketDebuggerUrl"], max_size=None, open_timeout=8) as ws:
        client = Cdp(ws)
        result = await client.call("Target.createTarget", {"url": url, "newWindow": False})
        target_id = str(result.get("targetId") or "")
    deadline = time.time() + 12
    while time.time() < deadline:
        found = find_stake_page(cdp, target_id=target_id)
        if found:
            return found
        await asyncio.sleep(0.25)
    raise RuntimeError("created a tab but Stake target did not appear")


class Cdp:
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

    async def evaluate(self, expression: str, timeout: float = 30.0, await_promise: bool = False) -> object:
        result = await self.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": await_promise, "returnByValue": True},
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            text = ((result["exceptionDetails"].get("exception") or {}).get("description")) or "evaluate failed"
            raise RuntimeError(text)
        return (result.get("result") or {}).get("value")


CHALLENGE_JS = r"""
(() => {
  const blob = ((document.title || '') + ' ' + (document.body && document.body.innerText || '')).slice(0, 2000);
  const challenge = /just a moment|checking your browser|attention required|enable javascript|cf-browser|access denied|kasada/i.test(blob);
  return {challenge, title: document.title, href: location.href};
})()
"""


async def page_challenge(client: Cdp) -> dict:
    try:
        value = await client.evaluate(CHALLENGE_JS, timeout=8)
    except Exception:
        return {"challenge": False}
    return value if isinstance(value, dict) else {"challenge": False}


async def sniff_auth_headers(client: Cdp, timeout: float = 35.0, reload_page: bool = False) -> dict:
    """Prefer existing in-page GraphQL traffic. Reload only as a last resort."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    reloaded = False
    while loop.time() < deadline:
        remaining = deadline - loop.time()
        if remaining < timeout * 0.45 and reload_page and not reloaded:
            await client.call("Page.reload", {"ignoreCache": False}, timeout=15)
            reloaded = True
        try:
            msg = json.loads(await asyncio.wait_for(client.ws.recv(), timeout=min(4, remaining)))
        except asyncio.TimeoutError:
            continue
        if msg.get("method") != "Network.requestWillBeSent":
            continue
        req = msg["params"].get("request") or {}
        if _GQL_PATH not in req.get("url", ""):
            continue
        headers = req.get("headers") or {}
        if headers.get("x-access-token") or headers.get("X-Access-Token"):
            return headers
    raise RuntimeError("no x-access-token; Stake tab is probably not logged in")


async def gql(
    client: Cdp,
    headers: dict,
    query: str,
    variables: dict | None = None,
    timeout: float = 30.0,
    operation_name: str | None = None,
) -> dict:
    hdr = {k: v for k, v in headers.items() if k.lower() in _KEEP_HEADERS}
    hdr["content-type"] = "application/json"
    payload_obj = {"query": query, "variables": variables or {}}
    if operation_name:
        payload_obj["operationName"] = operation_name
    body = json.dumps(payload_obj)
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
    value = await client.evaluate(js, timeout=timeout, await_promise=True)
    if not value:
        raise RuntimeError("graphql transport failure: empty response")
    try:
        payload = json.loads(value.get("body") or "{}", parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"graphql non-json body status={value.get('status')}: {str(value.get('body'))[:240]}") from exc
    errors = payload.get("errors")
    if errors:
        first = errors[0] if isinstance(errors, list) and errors else errors
        message = first.get("message") if isinstance(first, dict) else str(first)
        raise RuntimeError(f"graphql: {message}")
    if value.get("status") != 200:
        raise RuntimeError(f"graphql HTTP {value.get('status')}: {str(value.get('body'))[:240]}")
    return payload.get("data") or {}
