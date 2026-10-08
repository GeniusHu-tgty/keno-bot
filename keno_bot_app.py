"""Keno BOT launcher: start the local workbench and open the browser.

This is also the PyInstaller entry script.  Writable state goes to a per-user
directory (see keno.paths), so the packaged .exe never writes next to itself.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

if not getattr(sys, "frozen", False):
    ROOT = Path(__file__).resolve().parent
    SRC = ROOT / "src"
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

from keno import paths  # noqa: E402
from keno.webapp.server import bind_http_server  # noqa: E402

APP_ID = "keno-bot"
CANDIDATES = (8000, 8001, 8002, 8765, 8787, 18765)


def _probe(port: int) -> str | None:
    """Return the live-page URL if a Keno BOT instance already owns this port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/app", timeout=1.5) as response:
            info = json.loads(response.read(4096).decode("utf-8", "ignore"))
    except Exception:
        return None
    if isinstance(info, dict) and info.get("app") == APP_ID:
        return f"http://127.0.0.1:{port}/live"
    return None


def main() -> int:
    for port in CANDIDATES:
        running = _probe(port)
        if running:
            print(f"Keno BOT 已经在运行，直接打开：{running}")
            webbrowser.open(running)
            return 0

    server = bind_http_server("127.0.0.1", CANDIDATES[0])
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    live_url = f"{base}/live"
    (paths.app_home() / "lab.url").write_text(live_url, encoding="utf-8")
    print("Keno BOT 已启动（本地工作台）")
    print(f"  训练台   : {base}/")
    print(f"  实盘台   : {live_url}")
    print(f"  数据目录 : {paths.app_home()}")
    print("按 Ctrl+C 停止；关掉这个窗口也会一起停掉。")
    threading.Timer(0.8, lambda: webbrowser.open(live_url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
