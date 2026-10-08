# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
import json
import socket
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

from keno.webapp.server import Handler, bind_http_server


def _request(base: str, path: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_job(base: str, job_id: str) -> dict:
    for _ in range(400):
        status = _request(base, f"/api/run/status?job_id={job_id}")
        if status["status"] in {"completed", "cancelled", "failed"}:
            return status
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_stage_table_groups_probe_and_block_subtotals():
    from keno.webapp.server import _stage_table

    records = [
        {"stage": "探针", "bet": "0.0001", "payout": "0.00011", "profit": "0.00001", "hits": 2},
        {"stage": "1阶段 恢复", "bet": "0.01", "payout": "0.011", "profit": "0.001", "hits": 2},
        {"stage": "1阶段 收益1", "bet": "0.10", "payout": "0.11", "profit": "0.01", "hits": 2},
        {"stage": "1阶段 收益2", "bet": "0.60", "payout": "0", "profit": "-0.60", "hits": 0},
        {"stage": "探针", "bet": "0.0001", "payout": "0", "profit": "-0.0001", "hits": 0},
        {"stage": "2阶段 恢复", "bet": "0.01", "payout": "0.011", "profit": "0.001", "hits": 2},
    ]
    rows = _stage_table(records)
    labels = [row["stage"] for row in rows]
    assert labels[0] == "探针"
    assert labels.count("探针") == 1
    assert "1阶段 小计" in labels
    assert "2阶段 小计" in labels
    assert labels[-1] == "合计"
    assert rows[-1]["role"] == "total"
    assert rows[-1]["rounds"] == 6


def test_app_handshake_identifies_the_instance():
    """The launcher relies on /api/app to tell an existing instance from another local server."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        info = _request(base, "/api/app")
        assert info["app"] == "keno-bot"
        assert info["brand"] == "Keno BOT"
    finally:
        server.shutdown()
        server.server_close()


def test_live_page_is_separate_from_lab():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(base + "/live", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "Keno BOT" in html
        assert "虚拟盘" in html
        assert "允许真钱" in html
        assert "一键 · 灵魂托管" in html
        assert "开始托管" in html
        assert "host-bar" in html
        assert "灵魂收口" in html
        assert "肥尾倍率收口" in html
        assert "本轮止盈" in html
        assert "本轮止损" in html
        assert "当天止损" in html
        assert "run-page-size" in html
        assert "hist-page-size" in html
        assert "资金看板" in html
        assert "pnl-chart" in html
        assert "近7天" in html
        assert "近30天" in html
        assert "投资金" in html or "pnl-kpis" in html
        assert "实战连败几把回探针" in html
        hist = _request(base, "/api/history?book=live&scope=session")
        assert hist["book"] == "live"
        assert "records" in hist
        from keno.bot.stake_live import reset_live_engine

        reset_live_engine()
        preview = _request(
            base,
            "/api/live/preview",
            "POST",
            {
                "money": "flat",
                "picks": "fixed-pattern",
                "base_bet": "0.01",
                "max_bet": "0.01",
                "force_min": False,
            },
        )
        assert preview["ok"] is True
        assert preview["picks"] == [3, 6, 14, 16, 22, 25, 29, 36, 37, 38]
        assert preview["amount"].startswith("0.01")
        assert preview["money_label"] == "平注"
        assert "每局固定" in preview["money_why"]
        again = _request(base, "/api/live/preview")
        assert again["picks"] == preview["picks"]
        assert again["amount"] == preview["amount"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_async_lab_and_auto_http_endpoints():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        lab = _request(
            base,
            "/api/lab",
            "POST",
            {
                "async": True,
                "sessions": 10,
                "rounds": 20,
                "risk": "medium",
                "pick_count": 10,
                "candidates": ["flat-min"],
                "selection_modes": ["random"],
            },
        )
        assert lab["ok"] is True
        lab_status = _wait_job(base, lab["job_id"])
        assert lab_status["status"] == "completed"
        assert lab_status["result"]["rows"]

        auto = _request(
            base,
            "/api/auto",
            "POST",
            {
                "async": True,
                "kind": "flat",
                "picks": "random",
                "rounds": 2,
                "base_bet": "0.0001",
                "session_bankroll": "0.001",
                "risk": "low",
                "pick_count": 10,
                "realtime": False,
            },
        )
        assert auto["ok"] is True
        auto_status = _wait_job(base, auto["job_id"])
        assert auto_status.get("ok") is True
        assert auto_status["status"] == "completed"
        assert auto_status["result"]["rounds"] == 2

        cycle = _request(
            base,
            "/api/auto",
            "POST",
            {
                "async": True,
                "kind": "phase",
                "picks": "pattern",
                "rounds": 2,
                "base_bet": "0.0001",
                "session_bankroll": "10",
                "risk": "low",
                "pick_count": 10,
                "realtime": False,
                "unattended": True,
                "max_sessions": 2,
                "hours": 0,
            },
        )
        assert cycle["ok"] is True
        cycle_status = _wait_job(base, cycle["job_id"])
        assert cycle_status["status"] == "completed"
        result = cycle_status["result"]
        assert result["unattended"] is True
        assert result["session_count"] == 2
        assert len(result["sessions"]) == 2
        assert any(row["role"] == "total" for row in result["stage_table"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_bind_falls_back_when_port_busy(monkeypatch):
    import keno.webapp.server as server_module

    # A port that is already *serving* must never be taken over: on Windows a
    # SO_REUSEADDR bind would happily steal it, so the blocker listens.
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    busy = blocker.getsockname()[1]

    # Pin the fallback list to a port nobody else uses, so the test never talks
    # to an unrelated local instance.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    spare = probe.getsockname()[1]
    probe.close()
    monkeypatch.setattr(server_module, "FALLBACK_PORTS", (spare,))

    try:
        server = bind_http_server("127.0.0.1", busy)
        try:
            assert server.server_address[1] == spare
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_address[1]}/live", timeout=5
            ) as response:
                html = response.read().decode("utf-8")
            assert "Keno BOT" in html
        finally:
            server.shutdown()
            server.server_close()
    finally:
        blocker.close()
