# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from decimal import Decimal

import pytest

from keno.bot.stake_session import (
    _normalize_balances,
    from_stake_numbers,
    live_status,
    to_stake_numbers,
)
from keno.bot.stake_live import MIN_BET, run_stake_live


def test_stake_number_conversion_roundtrip():
    picks = [1, 10, 40]
    zero = to_stake_numbers(picks)
    assert zero == [0, 9, 39]
    assert from_stake_numbers(zero) == picks


def test_stake_number_rejects_out_of_range():
    with pytest.raises(ValueError):
        to_stake_numbers([0, 1])
    with pytest.raises(ValueError):
        to_stake_numbers([1, 1])


def test_normalize_balances_accepts_list_or_available_wrapper():
    listed = _normalize_balances([{"amount": "1.2", "currency": "usdt"}])
    assert listed == [{"amount": "1.20000000", "currency": "usdt"}]
    wrapped = _normalize_balances({"available": [{"amount": "3", "currency": "btc"}]})
    assert wrapped[0]["currency"] == "btc"


def test_live_status_has_no_token_fields():
    status = live_status()
    assert "x-access-token" not in status
    assert status["status"] == "disconnected"


def test_ensure_cdp_is_true_when_port_already_up():
    from keno.bot.stake_cdp import cdp_up, ensure_cdp

    if not cdp_up():
        return
    assert ensure_cdp() is True


def test_money_str_does_not_keep_float_junk():
    from keno.bot.stake_session import money_str

    assert money_str("9.9949800") == "9.99498000"
    assert money_str("9.99505") == "9.99505000"
    assert "." in money_str(Decimal("9.99498"))
    assert "000000065" not in money_str(Decimal("9.99505"))


def test_keno_bet_mutation_does_not_query_iid_on_casino_bet():
    from keno.bot.stake_session import KENO_BET_MUTATION

    assert "kenoBet(" in KENO_BET_MUTATION
    assert "payoutMultiplier" in KENO_BET_MUTATION
    assert "\n    iid\n" not in KENO_BET_MUTATION
    assert "drawnNumbers" in KENO_BET_MUTATION


def test_place_bet_result_requires_confirmation_fields():
    from keno.bot.stake_session import KENO_BET_MUTATION, money_str

    assert "iid" not in KENO_BET_MUTATION.split("kenoBet", 1)[1].split("state", 1)[0]
    assert money_str("0.00011000000000000002") == "0.00011000"


def test_run_stake_live_requires_explicit_flag():
    with pytest.raises(ValueError):
        run_stake_live({"rounds": 1, "live_bets": False})
    assert MIN_BET == Decimal("0.0001")


def test_session_should_end_banks_spike_and_caps_giveback():
    from keno.bot.stake_live import playbook_from_payload, session_should_end

    off = playbook_from_payload({})
    assert session_should_end(Decimal("0.008"), 10, Decimal("15"), off) is None
    book = playbook_from_payload(
        {
            "playbook": True,
            "session_stop_win": "0.005",
            "stop_on_mult": "8",
            "session_max_rounds": 400,
        }
    )
    assert session_should_end(Decimal("0.001"), 10, Decimal("15"), book) == "session-fat-hit"
    assert session_should_end(Decimal("0.008"), 80, Decimal("1.1"), book) == "session-take-profit"
    assert session_should_end(Decimal("0.001"), 400, Decimal("1.1"), book) == "session-round-cap"
    assert session_should_end(Decimal("0.001"), 80, Decimal("1.1"), book) is None


def test_playbook_hard_stop_locks_green_in_soul_mode():
    from keno.bot.stake_live import playbook_from_payload, playbook_hard_stop

    soul = playbook_from_payload(
        {
            "playbook": True,
            "after_bank": "stop",
            "session_stop_win": "0.15",
            "stop_on_mult": "8",
        }
    )
    assert soul["after_bank"] == "stop"
    assert soul["daily_stop_win"] is None
    assert playbook_hard_stop("session-take-profit", soul) is True
    assert playbook_hard_stop("session-fat-hit", soul) is True
    assert playbook_hard_stop("session-round-cap", soul) is True
    grind = playbook_from_payload({"playbook": True, "after_bank": "grind"})
    assert playbook_hard_stop("session-take-profit", grind) is False
    assert playbook_hard_stop("session-stop-loss", grind) is True
    rest = playbook_from_payload({"playbook": True, "after_bank": "rest", "session_stop_win": "0.15"})
    assert playbook_hard_stop("session-take-profit", rest) is True
    from keno.bot.stake_live import rest_seconds_for, HOST_RESUME_REASONS

    assert rest_seconds_for("session-take-profit", rest) == 180
    assert rest_seconds_for("stop-loss hit", rest) == 900
    assert "stop-loss hit" in HOST_RESUME_REASONS
    from keno.bot.stake_live import DAY_REST_REASONS

    assert "max-level-loss" in DAY_REST_REASONS
    assert "max-level-win" not in DAY_REST_REASONS
    assert rest_seconds_for("max-level-loss", rest) >= 60


def test_session_and_daily_stop_loss():
    from keno.bot.stake_live import (
        DAY_REST_REASONS,
        HOST_RESUME_REASONS,
        playbook_from_payload,
        rest_seconds_for,
        session_should_end,
    )

    book = playbook_from_payload(
        {
            "playbook": True,
            "after_bank": "rest",
            "session_stop_win": "0.15",
            "session_stop_loss": "1.50",
            "daily_stop_win": "0.50",
            "daily_stop_loss": "3",
            "stop_on_mult": "8",
            "session_max_rounds": 400,
        }
    )
    assert book["session_stop_loss"] == Decimal("1.50")
    assert book["daily_stop_loss"] == Decimal("3")
    assert session_should_end(Decimal("-1.50"), 10, Decimal("0"), book) == "session-stop-loss"
    assert session_should_end(Decimal("-1.49"), 10, Decimal("0"), book) is None
    assert "daily-stop-loss" in DAY_REST_REASONS
    assert "daily-stop-loss" in HOST_RESUME_REASONS
    assert rest_seconds_for("daily-stop-loss", book) >= 60


def test_plan_live_run_splits_thousand_rounds_into_slices():
    from keno.bot.stake_live import plan_live_run

    short = plan_live_run({"rounds": 20})
    assert short["target"] == 20
    assert short["slices"] == 1
    long = plan_live_run({"rounds": 1000, "slice_rounds": 100, "unattended": True, "pace_seconds": 3.5})
    assert long["target"] == 1000
    assert long["slices"] == 10
    assert long["cooldown"] >= 3
    day = plan_live_run({"hours": 24, "rounds": 0, "pace_seconds": 3.5, "slice_rounds": 100})
    assert day["unattended"] is True
    assert day["target"] == int(24 * 3600 / 3.5)
    assert day["slices"] == (day["target"] + 99) // 100


def test_live_engine_preview_matches_next_ticket_and_caps():
    from keno.bot.stake_live import LiveEngine, reset_live_engine

    reset_live_engine()
    engine = LiveEngine(
        {
            "money": "flat",
            "picks": "fixed-pattern",
            "base_bet": "0.01",
            "max_bet": "0.01",
            "force_min": False,
        }
    )
    first = engine.preview(Decimal("10"))
    second = engine.preview(Decimal("10"))
    assert first["picks"] == second["picks"] == [3, 6, 14, 16, 22, 25, 29, 36, 37, 38]
    assert first["amount"] == "0.01000000"
    assert first["money_label"] == "平注"
    assert "每局固定" in first["money_why"]
    assert "固定号码" in first["picks_why"]
    engine.commit(Decimal("-0.01"), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    after = engine.preview(Decimal("9.99"))
    assert after["picks"] == first["picks"]

    capped = LiveEngine({"money": "flat", "picks": "pattern", "base_bet": "0.10", "max_bet": "0.01"})
    plan = capped.preview(Decimal("10"))
    assert plan["amount"] == "0.01000000"
    assert "单注上限" in (plan.get("cap_note") or plan["money_why"])

    probe = LiveEngine({"money": "flat", "picks": "pattern", "base_bet": "0.10", "force_min": True, "max_bet": "0.10"})
    assert probe.preview(Decimal("10"))["amount"] == "0.00010000"


def test_live_lab_shadow_is_causal_and_scores_fixed_pattern():
    from keno.research.live_lab import hypergeometric_p, shadow_for_draw, theoretical_rtp

    rtp = theoretical_rtp()
    assert Decimal("0.98") < rtp < Decimal("1")
    assert abs(sum(hypergeometric_p(k) for k in range(11)) - 1) < 1e-9
    drawn = [3, 6, 14, 16, 22, 25, 29, 36, 37, 38]
    shadow = shadow_for_draw(drawn, [], 10)
    assert shadow["fixed-pattern"] == 10


def test_live_engine_keeps_pattern_until_commit():
    from keno.bot.stake_live import LiveEngine, reset_live_engine

    reset_live_engine()
    engine = LiveEngine({"money": "flat", "picks": "pattern", "base_bet": "0.0001"})
    a = engine.preview(Decimal("10"))["picks"]
    b = engine.preview(Decimal("10"))["picks"]
    assert a == b
    engine.commit(Decimal("0"), list(range(1, 11)))
    c = engine.preview(Decimal("10"))["picks"]
    assert c == a
