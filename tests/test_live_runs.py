# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
import json
import time
from decimal import Decimal

import keno.bot.ledger as ledger


def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ledger, "LIVE_PATH", tmp_path / "live_records.jsonl")
    monkeypatch.setattr(ledger, "LIVE_STATE_PATH", tmp_path / "live_state.json")
    monkeypatch.setattr(ledger, "LIVE_RUNS_PATH", tmp_path / "live_runs.json")
    ledger._LIVE_META.update(
        {
            "batch": 1,
            "run": 1,
            "start_index": 0,
            "started_at": time.time(),
            "conversation_id": 1,
        }
    )


def test_rotate_rename_and_detail(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    ledger.new_live_session(
        name="第一次",
        settings={"risk": "low", "custom_amounts": "0.0001", "keep_on_win": True, "pick_count": 10},
    )
    ledger.append_record(
        "live",
        {
            "bet": "0.0001",
            "payout": "0.00011",
            "hits": 2,
            "picks": [1, 2],
            "drawn": [1, 2],
            "profit": "0.00001",
        },
    )
    ledger.new_live_session(
        name="第二次",
        settings={"risk": "medium", "custom_amounts": "0.0001", "keep_on_win": True, "pick_count": 10},
    )
    ledger.append_record("live", {"bet": "0.0001", "payout": "0", "hits": 0, "profit": "-0.0001"})
    runs = ledger.list_live_runs()
    names = [r["name"] for r in runs]
    assert "第一次" in names
    assert "第二次" in names
    first = next(r for r in runs if r["name"] == "第一次")
    assert first["open"] is False
    assert first["rounds"] == 1
    assert "低等10选" in first["brief"]
    detail = ledger.get_live_run(first["id"])
    assert detail is not None
    assert len(detail["records"]) == 1
    dash = detail["dashboard"]
    assert Decimal(dash["curve"][0]["cum"]) == Decimal("0.00001")
    assert dash["levels"]
    assert dash["streaks"] is not None
    renamed = ledger.rename_live_run(first["id"], "低等留号 0.0001")
    assert renamed["name"] == "低等留号 0.0001"
    names = [r["name"] for r in ledger.list_live_runs()]
    assert "第二次" in names
    assert "低等留号 0.0001" in names


def test_delete_run_and_timer_not_started(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    ledger.new_live_session(name="空的")
    info = ledger.live_session_info()
    assert info["duration_sec"] == 0
    assert info.get("playing") in (False, 0, None)
    runs = ledger.list_live_runs()
    rid = next(r["id"] for r in runs if r["name"] == "空的")
    assert ledger.delete_live_run(rid) is True
    names = [r["name"] for r in ledger.list_live_runs()]
    assert "空的" not in names


def test_recover_catalog_from_records(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    ledger.append_record(
        "live",
        {
            "bet": "0.001",
            "payout": "0.0011",
            "hits": 2,
            "risk": "low",
            "pick_count": 10,
            "run_id": "old-aaa",
            "ts": "2026-09-12 10:00:00",
            "session": "L1B1R1",
        },
    )
    ledger.append_record(
        "live",
        {
            "bet": "0.01",
            "payout": "0",
            "hits": 0,
            "risk": "medium",
            "pick_count": 10,
            "run_id": "old-bbb",
            "ts": "2026-09-12 11:00:00",
            "session": "L1B1R2",
        },
    )
    (tmp_path / "live_runs.json").write_text(json.dumps({"runs": [], "current_id": None}), encoding="utf-8")
    added = ledger.recover_missing_runs()
    assert added >= 2
    runs = ledger.list_live_runs()
    ids = [r["id"] for r in runs]
    assert "old-aaa" in ids
    assert "old-bbb" in ids


def test_fix_mismatched_run_names(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    data = {
        "current_id": "x",
        "runs": [
            {
                "id": "ok",
                "name": "录像低等四档",
                "settings": {"risk": "low", "custom_amounts": "0.001,0.011,0.12,1.33"},
                "started_at": time.time(),
                "open": False,
                "start_index": 0,
                "end_index": 0,
            },
            {
                "id": "bad",
                "name": "录像低等四档",
                "settings": {"risk": "medium", "custom_amounts": "0.01,0.02,0.06,0.16,0.43"},
                "started_at": time.time(),
                "open": False,
                "start_index": 0,
                "end_index": 0,
            },
        ],
    }
    (tmp_path / "live_runs.json").write_text(json.dumps(data), encoding="utf-8")
    assert ledger.fix_mismatched_run_names() == 1
    by_id = {r["id"]: r for r in json.loads((tmp_path / "live_runs.json").read_text(encoding="utf-8"))["runs"]}
    assert by_id["ok"]["name"] == "录像低等四档"
    assert by_id["bad"]["name"] != "录像低等四档"
    assert "中等" in by_id["bad"]["name"]


def test_mode_brief_keep_and_recon():
    text = ledger.mode_brief(
        {"risk": "low", "pick_count": 10, "custom_amounts": "0.0001", "keep_on_win": True, "recon_on": False}
    )
    assert "低等10选" in text
    assert "赢了留号" in text
    assert "侦察关" in text
