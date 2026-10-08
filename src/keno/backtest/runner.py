from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from random import Random
from typing import Sequence
from ..data.schema import BetRecord, RoundRecord, jsonable
from ..game.paytable import Paytable
from ..game.engine import settle
from ..reporting.metrics import hits_distribution, longest_loss_streak, max_drawdown
from ..strategies.base import Strategy

@dataclass(frozen=True)
class BacktestResult:
    strategy: str
    strategy_version: str
    rounds: int
    bet_amount: str
    total_bet: str
    total_payout: str
    profit: str
    roi: str
    average_hits: float
    hits_distribution: dict[int, int]
    max_drawdown: str
    longest_loss_streak: int
    bets: list[BetRecord]

def run_paper_backtest(records: Sequence[RoundRecord], strategy: Strategy, paytable: Paytable, pick_count: int = 1, bet_amount: Decimal = Decimal("0.00010000"), seed: int = 1, difficulty: str = "default") -> BacktestResult:
    if not records:
        raise ValueError("records must not be empty")
    if not 1 <= pick_count <= 10:
        raise ValueError("pick_count must be in 1..10")
    rng = Random(seed)
    history: list[RoundRecord] = []
    bets: list[BetRecord] = []
    for record in records:
        selected = strategy.predict(history, pick_count, rng)
        if len(selected) != pick_count or len(set(selected)) != pick_count or any(n < 1 or n > 40 for n in selected):
            raise ValueError(f"strategy returned invalid selection: {selected}")
        settlement = settle(selected, record.numbers, bet_amount, paytable)
        bets.append(BetRecord(record.round_id, selected, pick_count, difficulty, bet_amount, settlement.hits, settlement.multiplier, settlement.payout, settlement.profit, strategy.name, strategy.version, "paper-trade: every round"))
        history.append(record)
        strategy.observe(record)
    total_bet = sum((bet.bet_amount for bet in bets), Decimal("0"))
    total_payout = sum((bet.payout for bet in bets), Decimal("0"))
    profit = total_payout - total_bet
    profits = [bet.profit for bet in bets]
    return BacktestResult(strategy.name, strategy.version, len(bets), str(bet_amount), str(total_bet), str(total_payout), str(profit), str(profit / total_bet if total_bet else Decimal("0")), sum(bet.hits for bet in bets) / len(bets), hits_distribution([bet.hits for bet in bets]), str(max_drawdown(profits)), longest_loss_streak(profits), bets)

def run_strict_splits(records: Sequence[RoundRecord], strategy_factory, paytable: Paytable, pick_count: int = 1, bet_amount: Decimal = Decimal("0.00010000"), seed: int = 1) -> dict: 
    """Run independent chronological train/validation/test windows. No future record enters predict()."""
    n = len(records); train_end = int(n * 0.5); validation_end = int(n * 0.75)
    windows = {"train": records[:train_end], "validation": records[train_end:validation_end], "test": records[validation_end:]}
    result = {name: run_paper_backtest(window, strategy_factory(), paytable, pick_count, bet_amount, seed) for name, window in windows.items()}
    return {name: {k: jsonable(v) for k, v in asdict(value).items() if k != "bets"} for name, value in result.items()}

def write_backtest_report(path: str, summary: dict) -> None:
    from pathlib import Path
    out = Path(path); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
