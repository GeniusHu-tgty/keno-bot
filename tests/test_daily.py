# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from decimal import Decimal

from keno.bot import BotConfig, run_paper_bot
from keno.bot.stats import BotStats
from keno.research import run_daily_simulation
from keno.reporting.metrics import longest_loss_streak, max_drawdown
from random import Random


def test_incremental_stats_match_reference_metrics():
    rng = Random(99)
    profits = [Decimal(str(round(rng.uniform(-0.2, 0.3), 4))) for _ in range(2000)]
    stats = BotStats(Decimal("1"))
    for index, profit in enumerate(profits, start=1):
        stats.update(Decimal("0.01"), Decimal("0.01") + profit, profit, hits=2)
        # spot-check against the O(n) reference every 250 rounds and at the end
        if index % 250 == 0 or index == len(profits):
            assert stats.max_drawdown == max_drawdown(profits[:index])
            assert stats.longest_loss_streak == longest_loss_streak(profits[:index])


def make_config(tmp_path, **overrides):
    defaults = dict(
        rounds=500,
        pick_count=10,
        bankroll="10.00000000",
        out_prefix=str(tmp_path / "bot"),
        display_every=100000,
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def test_stop_win_ends_session(tmp_path):
    config = make_config(tmp_path, stop_win="0.000005", stop_loss=None)
    summary = run_paper_bot(config)
    assert summary["stop_reason"] == "stop-win reached"
    assert Decimal(summary["profit"]) >= Decimal("0.000005")


def test_stop_loss_ends_session(tmp_path):
    # stop-loss is a magnitude: "0.0005" cuts the session at profit <= -0.0005.
    config = make_config(tmp_path, stop_win=None, stop_loss="0.0005")
    summary = run_paper_bot(config)
    assert summary["stop_reason"] == "stop-loss reached"
    assert Decimal(summary["profit"]) <= Decimal("-0.0005")


def test_daily_simulation_small(tmp_path):
    report = run_daily_simulation(
        days=2,
        hours=0.05,
        pace_seconds=3.5,
        stop_win="0.5",
        stop_loss="2.0",
        pick_count=10,
        bankroll="10.00000000",
        seed="daily-test",
        rng_seed=1,
        out_prefix=str(tmp_path / "daily"),
    )
    assert report["rounds_per_day"] == int(0.05 * 3600 / 3.5)
    for arm in (report["phase_arm"], report["flat_arm"]):
        assert arm["days"] == 2
        assert arm["mean_rounds_per_day"] > 0
        assert 0.0 <= arm["session_win_rate"] <= 1.0
    assert (tmp_path / "daily.json").exists()
    assert (tmp_path / "daily.md").exists()
