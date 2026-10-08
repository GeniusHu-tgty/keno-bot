from __future__ import annotations

from collections import Counter
from decimal import Decimal


class BotStats:
    """Running totals for the live dashboard. Fields mirror the external bot's UI.

    All derived metrics (drawdown, loss streaks) are maintained incrementally so
    that 24k-round days stay linear in rounds.
    """

    def __init__(self, starting_bankroll: Decimal) -> None:
        self.starting_bankroll = starting_bankroll
        self.rounds = 0
        self.total_bet = Decimal("0")
        self.total_payout = Decimal("0")
        self.bankroll = starting_bankroll
        self.hits: Counter[int] = Counter()
        self.successes = 0
        self.max_drawdown = Decimal("0")
        self.longest_loss_streak = 0
        self.losses_in_a_row = 0
        self._balance = Decimal("0")
        self._peak = Decimal("0")
        self._loss_streak = 0

    def update(self, bet: Decimal, payout: Decimal, profit: Decimal, hits: int) -> None:
        self.rounds += 1
        self.total_bet += bet
        self.total_payout += payout
        self.bankroll += profit
        self.hits[hits] += 1
        if payout > bet:
            self.successes += 1
        self._balance += profit
        if self._balance > self._peak:
            self._peak = self._balance
        drawdown = self._peak - self._balance
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        if profit < 0:
            self._loss_streak += 1
            if self._loss_streak > self.longest_loss_streak:
                self.longest_loss_streak = self._loss_streak
        else:
            self._loss_streak = 0
        self.losses_in_a_row = self._loss_streak

    @property
    def success_rate(self) -> Decimal:
        return self.successes / self.rounds if self.rounds else Decimal("0")

    @property
    def profit(self) -> Decimal:
        return self.total_payout - self.total_bet

    @property
    def roi(self) -> Decimal:
        return self.profit / self.total_bet if self.total_bet else Decimal("0")

    def hits_line(self, pick_count: int) -> str:
        return "  ".join(f"{k} Hits {self.hits.get(k, 0)}" for k in range(pick_count + 1))

    def render(self, pick_count: int, phase: str) -> str:
        sign = "+" if self.profit >= 0 else ""
        lines = [
            "=" * 62,
            f" KENO PAPER BOT  第 {self.rounds} 局  余额 {self.bankroll}",
            "-" * 62,
            f" 总局数 {self.rounds}   总投注 {self.total_bet}   总回收 {self.total_payout}",
            f" 总收益 {sign}{self.profit}   ROI {self.roi:+.2%}   成功率 {self.success_rate:.1%}",
            f" 最大回撤 {self.max_drawdown}   最长连亏 {self.longest_loss_streak}   当前连亏 {self.losses_in_a_row}",
            f" 命中统计  {self.hits_line(pick_count)}",
            f" 当前阶段 {phase}",
            "=" * 62,
        ]
        return "\n".join(lines)
