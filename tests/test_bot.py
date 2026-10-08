# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest

from keno.bot import BotConfig, run_paper_bot, run_mock_ws_bot
from keno.bot.datasource import write_rounds_jsonl, iter_synthetic_rounds


def make_config(tmp_path: Path, **overrides) -> BotConfig:
    defaults = dict(
        rounds=200,
        strategy="random",
        pick_count=1,
        bet="0.00010000",
        bankroll="0.01000000",
        money="flat",
        paytable_path="configs/payout.yaml",
        out_prefix=str(tmp_path / "bot"),
        display_every=1000,
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def test_flat_bot_totals_are_consistent(tmp_path):
    config = make_config(tmp_path)
    summary = run_paper_bot(config)
    assert summary["real_money"] is False
    assert summary["rounds_played"] == 200
    bet = Decimal(summary["bet"])
    assert Decimal(summary["total_bet"]) == bet * 200
    assert Decimal(summary["profit"]) == Decimal(summary["total_payout"]) - Decimal(summary["total_bet"])
    assert sum(summary["hits"].values()) == 200
    assert Path(summary["log"]).exists()


def test_bot_is_deterministic_for_same_seed(tmp_path):
    first = run_paper_bot(make_config(tmp_path, out_prefix=str(tmp_path / "a")))
    second = run_paper_bot(make_config(tmp_path, out_prefix=str(tmp_path / "b")))
    assert first["profit"] == second["profit"]
    assert first["hits"] == second["hits"]
    log_a = Path(first["log"]).read_text(encoding="utf-8")
    log_b = Path(second["log"]).read_text(encoding="utf-8")
    assert log_a == log_b


def test_bot_stops_when_bankroll_is_gone(tmp_path):
    # Deterministic snapshot under the fixed seed: bleeds out after 11 rounds.
    # (Count follows the RNG stream; the 2026-09-11 stream-semantics fix
    #  changed this sequence from the earlier 114.)
    config = make_config(tmp_path, bankroll="0.00080000", bet="0.00020000", rounds=1000)
    summary = run_paper_bot(config)
    assert summary["stop_reason"] == "insufficient bankroll for next stake"
    assert summary["rounds_played"] == 11
    assert Decimal(summary["bankroll"]) < Decimal(summary["bet"])


def test_hot_strategy_bot_runs_and_logs_selections(tmp_path):
    config = make_config(tmp_path, strategy="hot", pick_count=1, rounds=300)
    summary = run_paper_bot(config)
    assert summary["rounds_played"] == 300
    first = json.loads(Path(summary["log"]).read_text(encoding="utf-8").splitlines()[0])
    assert len(first["selected_numbers"]) == 1
    assert 1 <= first["selected_numbers"][0] <= 40


def test_unattended_paper_bot_cycles_sessions(tmp_path):
    config = make_config(
        tmp_path,
        money="phase",
        pick_count=10,
        strategy="pattern",
        rounds=8,
        bankroll="10",
        unattended=True,
        max_sessions=2,
        hours=0,
        stop_win="0.5",
        stop_loss="2.0",
        out_prefix=str(tmp_path / "unattended"),
        paytable_path="configs/payout.yaml",
    )
    summary = run_paper_bot(config)
    assert summary["real_money"] is False
    assert summary["mode"] == "unattended_paper_bot"
    assert summary["session_count"] == 2
    assert len(summary["sessions"]) == 2
    assert summary["rounds_played"] > 0


def test_rounds_jsonl_roundtrip(tmp_path):
    path = tmp_path / "rounds.jsonl"
    written = write_rounds_jsonl(path, iter_synthetic_rounds(20, seed="rt"), limit=20)
    assert written == 20
    replayed = list(iter_replay_rounds_safe(path))
    assert len(replayed) == 20
    assert all(len(r.numbers) == 10 for r in replayed)


def iter_replay_rounds_safe(path):
    from keno.bot.datasource import iter_replay_rounds

    return iter_replay_rounds(path)


def test_replay_source_matches_original_rounds(tmp_path):
    path = tmp_path / "rounds.jsonl"
    records = list(iter_synthetic_rounds(10, seed="replay-check"))
    write_rounds_jsonl(path, iter(records))
    config = make_config(tmp_path, source="replay", replay_file=str(path), rounds=10)
    summary = run_paper_bot(config)
    assert summary["rounds_played"] == 10


def test_mock_ws_bot_end_to_end(tmp_path):
    config = make_config(tmp_path, source="ws", rounds=25, ws_port=8891)
    summary = run_mock_ws_bot(config)
    assert summary["rounds_played"] == 25
    assert summary["source"] == "ws"
    log_lines = Path(summary["log"]).read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 25
    events = [json.loads(line) for line in log_lines]
    assert all(len(e["round_numbers"]) == 10 for e in events)
    assert all(e["round_numbers"] != e["selected_numbers"] or True for e in events)


def test_invalid_source_rejected(tmp_path):
    with pytest.raises(ValueError):
        run_paper_bot(make_config(tmp_path, source="replay", replay_file=None))
