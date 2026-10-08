# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ..config import load_yaml
from .money import MoneyManager

PROBE = "PROBE"
RECOVERY = "R1"
WINDOW = "R2"
FINAL = "R3"

# Stake minimum bet: 0.0001. Every rung below is a multiple of it, matching the
# reference bot's observed stakes (probe 0.0001, recovery 0.01, profit 0.10/0.60).


class PhaseMachine(MoneyManager):
    """Block/round state machine reconstructed from the reference bot's screenshots.

    Visible structure (captured 2026-09-11): 探针 (probe) rounds at the platform
    minimum 0.0001 run between blocks; each block (B1, B2, ...) plays a 恢复
    (recovery) leg at 0.01 until a win, then a 取利 (profit-extraction) window at
    0.10 for ~12 rounds, then one 收尾 (final) shot at 0.60 that ends the block.
    Success is payout > bet.

    The exact trigger rules are NOT recoverable from screenshots; the rules below
    are an explicit, configurable stand-in calibrated to the observed texture
    (~1.2 probes per real round, ~0.04 wagered per round over 176 rounds). Like
    every staking scheme on an independent-round game it changes variance only,
    never EV.
    """

    name = "phase"

    def __init__(
        self,
        probe_bet: Decimal = Decimal("0.0001"),
        recovery_bet: Decimal = Decimal("0.01"),
        window_bet: Decimal = Decimal("0.10"),
        profit_rounds: int = 12,
        final_bet: Decimal = Decimal("0.60"),
        probes_to_enter: int = 2,
        probe_cooldown: int = 18,
    ) -> None:
        if probes_to_enter < 1:
            raise ValueError("probes_to_enter must be >= 1")
        if probe_cooldown < 0:
            raise ValueError("probe_cooldown must be non-negative")
        if profit_rounds < 1:
            raise ValueError("profit_rounds must be >= 1")
        self.probe_bet = probe_bet
        self.recovery_bet = recovery_bet
        self.window_bet = window_bet
        self.profit_rounds = profit_rounds
        self.final_bet = final_bet
        self.probes_to_enter = probes_to_enter
        self.probe_cooldown = probe_cooldown
        self.block = 1
        self.probe_streak = 0
        self.cooldown = probe_cooldown
        self.window_left = profit_rounds
        self.state = PROBE
        self.blocks_completed = 0

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PhaseMachine":
        data = load_yaml(path)
        return cls(
            probe_bet=Decimal(str(data.get("probe_bet", "0.0001"))),
            recovery_bet=Decimal(str(data.get("recovery_bet", "0.01"))),
            window_bet=Decimal(str(data.get("window_bet", "0.10"))),
            profit_rounds=int(data.get("profit_rounds", 12)),
            final_bet=Decimal(str(data.get("final_bet", "0.60"))),
            probes_to_enter=int(data.get("probes_to_enter", 2)),
            probe_cooldown=int(data.get("probe_cooldown", 18)),
        )

    def clone(self) -> "PhaseMachine":
        return PhaseMachine(
            probe_bet=self.probe_bet,
            recovery_bet=self.recovery_bet,
            window_bet=self.window_bet,
            profit_rounds=self.profit_rounds,
            final_bet=self.final_bet,
            probes_to_enter=self.probes_to_enter,
            probe_cooldown=self.probe_cooldown,
        )

    def next_bet(self, bankroll: Decimal) -> Decimal:
        if self.state == PROBE:
            return self.probe_bet
        if self.state == RECOVERY:
            return self.recovery_bet
        if self.state == WINDOW:
            return self.window_bet
        return self.final_bet

    def observe(self, profit: Decimal) -> None:
        success = profit > 0
        if self.state == PROBE:
            if self.cooldown > 0:
                self.cooldown -= 1
            else:
                self.probe_streak = self.probe_streak + 1 if success else 0
                if self.probe_streak >= self.probes_to_enter:
                    self.state = RECOVERY
        elif self.state == RECOVERY:
            if success:
                self.state = WINDOW
                self.window_left = self.profit_rounds
        elif self.state == WINDOW:
            self.window_left -= 1
            if self.window_left == 0:
                self.state = FINAL
        else:
            self.blocks_completed += 1
            self.block += 1
            self.state = PROBE
            self.probe_streak = 0
            self.cooldown = self.probe_cooldown

    @property
    def phase(self) -> str:
        if self.state == PROBE:
            return f"B{self.block}探针"
        if self.state == RECOVERY:
            return f"B{self.block}恢复"
        if self.state == WINDOW:
            return f"B{self.block}取利"
        return f"B{self.block}收尾"

    @property
    def display_stage(self) -> str:
        """Ladder table label: 探针 / N阶段 恢复 / N阶段 收益1 / N阶段 收益2."""
        if self.state == PROBE:
            return "探针"
        if self.state == RECOVERY:
            return f"{self.block}阶段 恢复"
        if self.state == WINDOW:
            return f"{self.block}阶段 收益1"
        return f"{self.block}阶段 收益2"

    @property
    def is_probe(self) -> bool:
        return self.state == PROBE
