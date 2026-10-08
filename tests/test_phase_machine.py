# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from decimal import Decimal

import pytest

from keno.bot.phases import PhaseMachine, PROBE, RECOVERY, WINDOW, FINAL
from keno.strategies import PatternStrategy
from random import Random


def profit(bet: Decimal, multiplier: str) -> Decimal:
    return bet * Decimal(multiplier) - bet


def test_cooldown_and_probe_streak_gate_entry():
    machine = PhaseMachine(probe_cooldown=3, probes_to_enter=2)
    assert machine.phase == "B1探针"
    assert machine.next_bet(Decimal("1")) == Decimal("0.0001")
    # Cooldown consumes probes even when they win.
    for _ in range(3):
        machine.observe(profit(Decimal("0.0001"), "1.10"))
    assert machine.state == PROBE
    machine.observe(profit(Decimal("0.0001"), "0"))  # streak reset after cooldown
    machine.observe(profit(Decimal("0.0001"), "1.10"))
    assert machine.state == PROBE
    machine.observe(profit(Decimal("0.0001"), "1.10"))  # 2nd consecutive win
    assert machine.state == RECOVERY
    assert machine.phase == "B1恢复"
    assert machine.next_bet(Decimal("1")) == Decimal("0.01")


def test_display_stage_matches_ladder_table_labels():
    machine = PhaseMachine(probe_cooldown=0, probes_to_enter=1, profit_rounds=1)
    assert machine.display_stage == "探针"
    assert machine.is_probe is True
    machine.observe(profit(Decimal("0.0001"), "1.10"))
    assert machine.display_stage == "1阶段 恢复"
    machine.observe(profit(Decimal("0.01"), "1.20"))
    assert machine.display_stage == "1阶段 收益1"
    machine.observe(profit(Decimal("0.10"), "1.10"))
    assert machine.display_stage == "1阶段 收益2"
    machine.observe(profit(Decimal("0.60"), "1.10"))
    assert machine.display_stage == "探针"
    assert machine.block == 2


def test_recovery_then_window_then_final_shot_ends_block():
    machine = PhaseMachine(probe_cooldown=0, probes_to_enter=1, profit_rounds=2)
    machine.observe(profit(Decimal("0.0001"), "1.10"))  # probe -> R1
    machine.observe(profit(Decimal("0.01"), "0"))       # R1 loss stays
    assert machine.state == RECOVERY
    machine.observe(profit(Decimal("0.01"), "1.20"))    # R1 win -> R2
    assert machine.state == WINDOW
    assert machine.phase == "B1取利"
    assert machine.next_bet(Decimal("1")) == Decimal("0.10")
    machine.observe(profit(Decimal("0.10"), "0"))       # window continues through losses
    assert machine.state == WINDOW
    machine.observe(profit(Decimal("0.10"), "2.00"))    # window done -> R3
    assert machine.state == FINAL
    assert machine.next_bet(Decimal("1")) == Decimal("0.60")
    machine.observe(profit(Decimal("0.60"), "1.10"))    # final shot ends block
    assert machine.blocks_completed == 1
    assert machine.block == 2
    assert machine.state == PROBE
    assert machine.phase == "B2探针"


def test_pattern_strategy_holds_selection_between_rerolls():
    strategy = PatternStrategy(reroll_every=3)
    rng = Random(5)
    first = strategy.predict([], 10, rng)
    second = strategy.predict([], 10, rng)
    assert first == second
    assert len(first) == 10 and len(set(first)) == 10
    assert all(1 <= n <= 40 for n in first)
    other = PatternStrategy(reroll_every=3)
    assert other.predict([], 10, Random(5)) == first


def test_all_stakes_are_platform_minimum_multiples():
    machine = PhaseMachine()
    minimum = Decimal("0.0001")
    for state_feed in range(0, 40):
        bet = machine.next_bet(Decimal("1000"))
        assert bet > 0 and (bet / minimum) == (bet / minimum).to_integral_value()
        machine.observe(Decimal("0.01"))  # any positive profit advances states
    machine2 = PhaseMachine()
    machine2.observe(Decimal("0"))
    assert machine2.next_bet(Decimal("1000")) == Decimal("0.0001")


def test_phase_machine_from_yaml(tmp_path):
    path = tmp_path / "phase.yaml"
    path.write_text(
        "probe_bet: \"0.0002\"\nrecovery_bet: \"0.02\"\nwindow_bet: \"0.2\"\n"
        "profit_rounds: 5\nfinal_bet: \"1.2\"\nprobes_to_enter: 3\nprobe_cooldown: 7\n",
        encoding="utf-8",
    )
    machine = PhaseMachine.from_yaml(path)
    assert machine.probe_bet == Decimal("0.0002")
    assert machine.recovery_bet == Decimal("0.02")
    assert machine.window_bet == Decimal("0.2")
    assert machine.profit_rounds == 5
    assert machine.final_bet == Decimal("1.2")
    assert machine.probes_to_enter == 3
    assert machine.probe_cooldown == 7
    assert machine.clone().window_bet == machine.window_bet
    with pytest.raises(ValueError):
        PhaseMachine(probes_to_enter=0)
    with pytest.raises(ValueError):
        PhaseMachine(profit_rounds=0)
