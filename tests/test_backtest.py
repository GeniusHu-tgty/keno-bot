# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from decimal import Decimal

from keno.backtest.runner import run_paper_backtest, run_strict_splits
from keno.game.paytable import Paytable
from keno.strategies.base import Strategy
from keno.synthetic import generate_rounds


class HistoryLengthStrategy(Strategy):
    name = "history-length"

    def __init__(self):
        self.seen_lengths = []

    def predict(self, history, pick_count, rng):
        self.seen_lengths.append(len(history))
        return [1]


def test_backtest_does_not_expose_current_round():
    records = generate_rounds(8)
    strategy = HistoryLengthStrategy()
    table = Paytable.from_yaml("configs/payout.yaml")
    run_paper_backtest(records, strategy, table)
    assert strategy.seen_lengths == list(range(8))


def test_strict_splits_have_expected_sizes():
    records = generate_rounds(20)
    table = Paytable.from_yaml("configs/payout.yaml")
    result = run_strict_splits(records, HistoryLengthStrategy, table)
    assert [result[name]["rounds"] for name in ("train", "validation", "test")] == [10, 5, 5]
    assert result["train"]["total_bet"] == str(Decimal("0.00100000"))
    assert result["validation"]["total_bet"] == str(Decimal("0.00050000"))
    assert result["test"]["total_bet"] == str(Decimal("0.00050000"))
