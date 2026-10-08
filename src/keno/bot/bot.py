from __future__ import annotations

from decimal import Decimal
from random import Random
from typing import Callable

from ..data.schema import BetRecord, RoundRecord
from ..game.engine import settle
from ..game.paytable import Paytable
from ..strategies.base import Strategy
from .money import MoneyManager
from .stats import BotStats


class KenoBot:
    """Per-round decision loop: stake -> pick numbers -> settle -> update state.

    Pure paper trading: nothing here talks to a real account or places real bets.
    """

    def __init__(
        self,
        strategy: Strategy,
        money_manager: MoneyManager,
        paytable: Paytable,
        pick_count: int = 1,
        bankroll: Decimal = Decimal("0.01000000"),
        difficulty: str = "default",
        rng_seed: int = 7,
        stop_win: Decimal | None = None,
        stop_loss: Decimal | None = None,
    ) -> None:
        """stop_win banks the session at that cumulative profit; stop_loss is a
        loss magnitude and cuts the session at profit <= -abs(stop_loss)."""
        if not 1 <= pick_count <= 10:
            raise ValueError("pick_count must be in 1..10")
        self.strategy = strategy
        self.money_manager = money_manager
        self.paytable = paytable
        self.pick_count = pick_count
        self.bankroll = bankroll
        self.difficulty = difficulty
        self.rng = Random(rng_seed)
        self.stats = BotStats(bankroll)
        self.history: list[RoundRecord] = []
        self.bankrupt = False
        self.stop_reason: str | None = None
        self.stop_win = stop_win
        self.stop_loss = abs(stop_loss) if stop_loss is not None else None

    def handle_round(self, record: RoundRecord, logger: Callable[[dict], None] | None = None) -> BetRecord | None:
        if self.bankrupt:
            return None
        bet = self.money_manager.next_bet(self.bankroll)
        if bet <= 0:
            self.bankrupt = True
            self.stop_reason = "bankroll exhausted"
            return None
        if bet > self.bankroll:
            self.bankrupt = True
            self.stop_reason = "insufficient bankroll for next stake"
            return None
        selected = self.strategy.predict(self.history, self.pick_count, self.rng)
        if len(selected) != self.pick_count or len(set(selected)) != self.pick_count or any(n < 1 or n > 40 for n in selected):
            raise ValueError(f"strategy returned invalid selection: {selected}")
        settlement = settle(selected, record.numbers, bet, self.paytable)
        bet_record = BetRecord(
            record.round_id,
            selected,
            self.pick_count,
            self.difficulty,
            bet,
            settlement.hits,
            settlement.multiplier,
            settlement.payout,
            settlement.profit,
            self.strategy.name,
            self.strategy.version,
            f"phase={self.money_manager.phase}",
        )
        self.bankroll += settlement.profit
        self.stats.update(bet, settlement.payout, settlement.profit, settlement.hits)
        self.history.append(record)
        self.strategy.observe(record)
        self.money_manager.observe(settlement.profit)
        if self.bankroll <= 0:
            self.bankrupt = True
            self.stop_reason = "bankroll exhausted"
        elif self.stop_win is not None and self.stats.profit >= self.stop_win:
            self.stop_reason = "stop-win reached"
        elif self.stop_loss is not None and self.stats.profit <= -self.stop_loss:
            self.stop_reason = "stop-loss reached"
        if logger is not None:
            from ..data.schema import jsonable

            logger({"type": "bet", **jsonable(bet_record), "round_numbers": record.numbers, "bankroll": str(self.bankroll)})
        return bet_record
