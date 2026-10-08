# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from decimal import Decimal

from keno.bot.stake_live import SESSION_ROTATE_REASONS, next_bet_blows_stop, plan_live_run


def test_recovery_bets_always_place_if_bank_covers():
    # 两连败后第3档 1.21 必须打，止损再紧也不能拦
    assert next_bet_blows_stop(Decimal("-0.12"), Decimal("1.21"), Decimal("0.20"), 3, 3, Decimal("10")) is False
    assert next_bet_blows_stop(Decimal("-0.12"), Decimal("1.21"), Decimal("1.40"), 3, 3, Decimal("10")) is False


def test_unplayable_only_when_bet_exceeds_bank():
    assert next_bet_blows_stop(Decimal("-1.33"), Decimal("13.3"), Decimal("1.50"), 4, 4, Decimal("10")) is True
    assert next_bet_blows_stop(Decimal("-1.33"), Decimal("13.3"), Decimal("1.50"), 4, 4, Decimal("20")) is False


def test_loop_plan_uses_session_cap_not_job_rounds():
    plan = plan_live_run(
        {
            "loop_sessions": True,
            "session_rounds": 200,
            "rounds": 0,
            "hours": 0,
            "pace_seconds": 3,
        }
    )
    assert plan["loop_sessions"] is True
    assert plan["session_cap"] == 200
    assert plan["target"] > 200
    assert plan["unattended"] is True


def test_loop_does_not_rotate_through_stop_loss():
    assert "stop-loss hit" not in SESSION_ROTATE_REASONS
    assert "max-streak" not in SESSION_ROTATE_REASONS
    assert "max-level-win" in SESSION_ROTATE_REASONS
    assert "stop-win hit" in SESSION_ROTATE_REASONS


def test_soul_lock_covers_green_reasons():
    from keno.bot.stake_live import SOUL_BANK_STOPS

    assert "session-take-profit" in SOUL_BANK_STOPS
    assert "session-fat-hit" in SOUL_BANK_STOPS
    assert "stop-loss hit" not in SESSION_ROTATE_REASONS


def test_single_run_plan_caps_at_rounds():
    plan = plan_live_run({"rounds": 200, "hours": 0, "pace_seconds": 3})
    assert plan["loop_sessions"] is False
    assert plan["target"] == 200
    assert plan["session_cap"] == 200
