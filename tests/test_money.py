# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from decimal import Decimal

from keno.bot.money import (
    CappedRecoveryManager,
    FlatMoneyManager,
    FractionalMoneyManager,
    PhaseRecoveryManager,
    ProbeWindowManager,
)


def test_flat_manager_returns_base_bet():
    manager = FlatMoneyManager(Decimal("0.0001"))
    assert manager.next_bet(Decimal("1")) == Decimal("0.0001")
    assert manager.phase == "flat"


def test_flat_manager_ignores_bankroll_capping():
    # The bot stops when the bankroll cannot cover the stake; the manager never shrinks it.
    manager = FlatMoneyManager(Decimal("0.0001"))
    assert manager.next_bet(Decimal("0.00001")) == Decimal("0.0001")


def test_recovery_raises_after_loss_and_resets_after_win():
    manager = PhaseRecoveryManager(Decimal("0.0001"), Decimal("2"))
    assert manager.next_bet(Decimal("1")) == Decimal("0.0001")
    manager.observe(Decimal("-0.0001"))
    assert manager.next_bet(Decimal("1")) == Decimal("0.0002")
    manager.observe(Decimal("-0.0002"))
    assert manager.next_bet(Decimal("1")) == Decimal("0.0004")
    manager.observe(Decimal("0.0005"))
    assert manager.next_bet(Decimal("1")) == Decimal("0.0001")
    assert manager.phase == "base"


def test_recovery_capped_at_max_steps():
    manager = PhaseRecoveryManager(Decimal("0.0001"), Decimal("2"), max_recovery_steps=3)
    for _ in range(10):
        manager.observe(Decimal("-0.0001"))
    assert manager.next_bet(Decimal("100")) == Decimal("0.0008")
    assert manager.phase == "recovery(10)"


def test_recovery_break_even_keeps_step():
    manager = PhaseRecoveryManager(Decimal("0.0001"), Decimal("2"))
    manager.observe(Decimal("-0.0001"))
    manager.observe(Decimal("0"))
    assert manager.next_bet(Decimal("1")) == Decimal("0.0002")


def test_fractional_manager_has_floor_and_cap():
    manager = FractionalMoneyManager(
        fraction=Decimal("0.01"),
        min_bet=Decimal("0.0001"),
        max_fraction=Decimal("0.02"),
    )
    assert manager.next_bet(Decimal("0.001")) == Decimal("0.0001")
    assert manager.next_bet(Decimal("10")) == Decimal("0.1")
    assert manager.phase == "fractional(0.01)"


def test_probe_window_cycles_without_using_profit_as_prediction():
    manager = ProbeWindowManager(
        probe_bet=Decimal("0.0001"),
        active_bet=Decimal("0.001"),
        probe_rounds=2,
        active_rounds=2,
        cooldown_rounds=2,
    )
    stakes = []
    for _ in range(6):
        stakes.append(manager.next_bet(Decimal("10")))
        manager.observe(Decimal("-1"))
    assert stakes == [
        Decimal("0.0001"),
        Decimal("0.0001"),
        Decimal("0.001"),
        Decimal("0.001"),
        Decimal("0.0001"),
        Decimal("0.0001"),
    ]
    assert manager.phase == "probe"


def test_capped_recovery_does_not_exceed_configured_step():
    manager = CappedRecoveryManager(
        base_bet=Decimal("0.0001"),
        multiplier=Decimal("1.25"),
        max_steps=2,
    )
    for _ in range(10):
        manager.observe(Decimal("-0.0001"))
    assert manager.next_bet(Decimal("10")) == Decimal("0.00015625")
