# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from .backtest.runner import run_strict_splits
from .game.paytable import Paytable
from .strategies import RandomStrategy, HotStrategy, ColdStrategy
from .synthetic import generate_rounds

def run_paper_experiment(rounds: int, pick_count: int, bet_amount: Decimal, paytable_path: str | Path, seed: str = "keno-synthetic-v1") -> dict:
    records = generate_rounds(rounds, seed=seed)
    paytable = Paytable.from_yaml(paytable_path)
    factories = {"random": RandomStrategy, "hot": HotStrategy, "cold": ColdStrategy}
    result = {name: run_strict_splits(records, factory, paytable, pick_count, bet_amount) for name, factory in factories.items()}
    return {"mode": "paper_trade", "real_money": False, "rounds": rounds, "pick_count": pick_count, "bet_amount": str(bet_amount), "seed": seed, "strategies": result}
