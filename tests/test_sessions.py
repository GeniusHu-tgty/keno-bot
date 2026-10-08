# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from decimal import Decimal

from keno.research import run_session_monte_carlo


def test_session_monte_carlo_small_run(tmp_path):
    report = run_session_monte_carlo(
        sessions=12,
        rounds_per_session=40,
        pick_count=10,
        bankroll="1.00000000",
        seed="mc-test",
        rng_seed=3,
        benchmark_profit="0.01",
        flat_control_bet="0.01",
        out_prefix=str(tmp_path / "mc"),
    )
    phase = report["phase_arm"]
    flat = report["flat_arm"]
    assert phase["sessions"] == 12
    assert flat["sessions"] == 12
    # Both arms replayed the same stream -> identical round counts overall.
    assert phase["mean_success_rate"] > 0
    # Percentiles must be ordered.
    profits = [Decimal(phase[k]) for k in ("min_profit", "p05_profit", "p25_profit", "median_profit", "p75_profit", "p95_profit", "max_profit")]
    assert profits == sorted(profits)
    # Benchmark placement present for the phase arm.
    assert 0.0 <= phase["benchmark_percentile"] <= 1.0
    assert (tmp_path / "mc.json").exists()
    assert (tmp_path / "mc.md").exists()


def test_session_monte_carlo_phase_structure_inflates_turnover(tmp_path):
    report = run_session_monte_carlo(
        sessions=8,
        rounds_per_session=60,
        pick_count=10,
        seed="mc-wager",
        rng_seed=9,
        benchmark_profit=None,
        flat_control_bet="0.01",
        out_prefix=str(tmp_path / "mcw"),
    )
    phase_wagered = Decimal(report["phase_arm"]["mean_wagered"])
    flat_wagered = Decimal(report["flat_arm"]["mean_wagered"])
    # The profit ladder stakes up to 0.78, so despite 0.0001 probes it must
    # wager far MORE than flat 0.01/round. This is exactly why phase-bot
    # sessions swing harder than flat betting at the same win rate.
    assert phase_wagered > flat_wagered
    success = report["phase_arm"]["mean_success_rate"]
    assert 0.70 <= success <= 0.90
