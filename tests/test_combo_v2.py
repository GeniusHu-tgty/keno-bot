# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
import time
from decimal import Decimal
from random import Random

from keno.bot.combo_v2 import (
    ComboV2,
    analyze_numbers,
    current_real_loss_streak,
    dashboard,
    is_win,
    parse_amounts,
    recommend,
)


def test_parse_and_ladder_climbs_on_loss_resets_on_win():
    c = ComboV2(parse_amounts("0.001,0.011,0.12,1.33"), start_level=1, max_level=4)
    assert c.next_bet() == Decimal("0.001")
    c.observe(Decimal("-0.001"))
    assert c.level == 2
    assert c.next_bet() == Decimal("0.011")
    c.observe(Decimal("-0.011"))
    assert c.level == 3
    c.observe(Decimal("0.012"))
    assert c.level == 1
    assert c.next_bet() == Decimal("0.001")


def test_low_1_1x_counts_as_win():
    assert is_win(Decimal("0.0011"), Decimal("0.001")) is True
    assert is_win(Decimal("0"), Decimal("0.001")) is False


def test_recon_two_losses_then_real():
    c = ComboV2(
        parse_amounts("0.01,0.1"),
        recon_on=True,
        recon_n_loss=2,
        recon_n_win=0,
        recon_real_n=4,
        recon_min=Decimal("0.0001"),
    )
    assert c.next_bet() == Decimal("0.0001")
    c.observe(Decimal("-0.0001"))
    c.observe(Decimal("-0.0001"))
    assert c.in_recon is False
    assert c.next_bet() == Decimal("0.01")


def test_recon_wins_are_consecutive_not_cumulative():
    c = ComboV2(
        parse_amounts("0.01,0.11"),
        recon_on=True,
        recon_n_loss=0,
        recon_n_win=2,
        recon_min=Decimal("0.0001"),
    )
    c.observe(Decimal("0.00001"))
    c.observe(Decimal("-0.0001"))
    c.observe(Decimal("0.00001"))
    assert c.in_recon is True
    c.observe(Decimal("0.00001"))
    assert c.in_recon is False
    assert c.next_bet() == Decimal("0.01")


def test_recon_win_then_real_climb_then_return():
    c = ComboV2(
        parse_amounts("0.01,0.11,1.21,1.33"),
        recon_on=True,
        recon_n_loss=0,
        recon_n_win=1,
        recon_min=Decimal("0.0001"),
        recon_return_on_real_win=True,
    )
    assert c.next_bet() == Decimal("0.0001")
    c.observe(Decimal("0.00001"))
    assert c.in_recon is False
    assert c.next_bet() == Decimal("0.01")
    c.observe(Decimal("-0.01"))
    assert c.in_recon is False
    assert c.level == 2
    assert c.next_bet() == Decimal("0.11")
    c.observe(Decimal("0.011"))
    assert c.in_recon is True
    assert c.level == 1
    assert c.next_bet() == Decimal("0.0001")


def test_recon_max_level_loss_returns():
    c = ComboV2(
        parse_amounts("0.01,0.11"),
        recon_on=True,
        recon_n_win=1,
        recon_n_loss=0,
        recon_return_on_real_win=True,
        recon_min=Decimal("0.0001"),
    )
    c.observe(Decimal("0.00001"))
    c.observe(Decimal("-0.01"))
    assert c.level == 2
    c.observe(Decimal("-0.11"))
    assert c.in_recon is True
    assert c.level == 1


def test_recon_abort_on_real_loss_skips_climb():
    c = ComboV2(
        parse_amounts("0.01,0.11"),
        recon_on=True,
        recon_n_win=1,
        recon_n_loss=0,
        recon_abort_on_real_loss=True,
        recon_min=Decimal("0.0001"),
    )
    c.observe(Decimal("0.00001"))
    c.observe(Decimal("-0.01"))
    assert c.in_recon is True
    assert c.level == 1
    assert c.next_bet() == Decimal("0.0001")


def test_l4_budget_two_per_six_hours_and_five_hit_freeze():
    c = ComboV2(
        parse_amounts("0.001,0.011,0.12,1.33"),
        recon_on=True,
        recon_n_win=1,
        recon_n_loss=0,
        recon_return_on_real_win=True,
        recon_min=Decimal("0.0001"),
        max_level=4,
    )
    c.in_recon = False
    c.level = 4
    c.observe(Decimal("1.064"), hits=5)
    assert c.freeze_l4_until > time.time()
    assert c.l4_allowed() is False
    c.in_recon = False
    c.level = 2
    c.observe(Decimal("-0.011"))
    assert c.in_recon is True
    assert c.next_bet() == Decimal("0.0001")


def test_l4_loss_goes_probe_not_immediate_retry():
    c = ComboV2(
        parse_amounts("0.001,0.011,0.12,1.33"),
        recon_on=True,
        recon_n_win=1,
        recon_n_loss=0,
        recon_return_on_real_win=True,
        recon_min=Decimal("0.0001"),
        max_level=4,
    )
    c.in_recon = False
    c.level = 4
    c.observe(Decimal("-1.33"), hits=1)
    assert c.in_recon is True
    assert c.probe_work >= 40
    assert c.next_bet() == Decimal("0.0001")
    assert len(c.l4_times) == 1


def test_recon_abort_after_two_real_losses_allows_one_climb():
    c = ComboV2(
        parse_amounts("0.001,0.011,0.12,1.33"),
        recon_on=True,
        recon_n_win=1,
        recon_n_loss=0,
        recon_abort_after=2,
        recon_min=Decimal("0.0001"),
    )
    c.observe(Decimal("0.00001"))
    assert c.in_recon is False
    assert c.next_bet() == Decimal("0.001")
    c.observe(Decimal("-0.001"))
    assert c.in_recon is False
    assert c.level == 2
    assert c.next_bet() == Decimal("0.011")
    c.observe(Decimal("-0.011"))
    assert c.in_recon is True
    assert c.level == 1
    assert c.next_bet() == Decimal("0.0001")


def test_dashboard_recon_bucket_and_real_streaks():
    rows = [
        {"bet": "0.0001", "payout": "0", "hits": 0, "level": 0, "recon": True, "stage": "侦察"},
        {"bet": "0.0001", "payout": "0.00011", "hits": 2, "level": 0, "recon": True, "stage": "侦察"},
        {"bet": "0.01", "payout": "0", "hits": 0, "level": 1},
        {"bet": "0.11", "payout": "0.121", "hits": 2, "level": 2},
    ]
    dash = dashboard(rows)
    assert dash["recon_rounds"] == 2
    assert dash["levels"][0]["label"] == "侦察"
    assert dash["real_max_streak"] == 1
    assert current_real_loss_streak(rows) == 0


def test_keep_on_win_and_heatmap_recommend():
    draws = [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10] for _ in range(40)]
    draws += [[31, 32, 33, 34, 35, 36, 37, 38, 39, 40] for _ in range(40)]
    analysis = analyze_numbers(draws)
    assert analysis[1]["freq"] > analysis[20]["freq"]
    picks = recommend(analysis, 10, Random(1))
    assert len(picks) == 10
    assert len(set(picks)) == 10
    c = ComboV2(parse_amounts("0.001"), keep_on_win=True)
    first = c.choose_picks(draws, 10, Random(2), None)
    again = c.choose_picks(draws, 10, Random(3), True)
    assert first == again


def test_dashboard_running_curve_peak_trough():
    rows = [
        {"bet": "0.01", "payout": "0.016", "hits": 3, "level": 1, "n": 1},
        {"bet": "0.01", "payout": "0", "hits": 0, "level": 1, "n": 2},
        {"bet": "0.02", "payout": "0.14", "hits": 6, "level": 2, "n": 3},
    ]
    dash = dashboard(rows)
    assert len(dash["curve"]) == 3
    assert Decimal(dash["curve"][-1]["cum"]) == Decimal(dash["profit"])
    assert Decimal(dash["peak"]) == Decimal(dash["curve"][-1]["cum"])
    assert Decimal(dash["trough"]) < 0
    assert dash["trough_n"] == 2
    assert dash["peak_n"] == 3
    assert dash["levels"][0]["n"] == 2
    assert dash["levels"][1]["level"] == 2


def test_dashboard_success_rate_uses_payout_ge_bet():
    rows = [
        {"bet": "0.01", "payout": "0.011", "hits": 2, "level": 1},
        {"bet": "0.01", "payout": "0", "hits": 1, "level": 1},
        {"bet": "0.11", "payout": "0.132", "hits": 3, "level": 2},
    ]
    dash = dashboard(rows)
    assert dash["rounds"] == 3
    assert dash["wins"] == 2
    assert dash["levels"][0]["level"] == 1
    assert Decimal(dash["profit"]) > 0
    assert Decimal(dash["win_profit"]) > 0
    assert Decimal(dash["lose_profit"]) < 0
