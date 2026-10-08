# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..bot.bot import KenoBot
from ..bot.datasource import iter_synthetic_rounds
from ..bot.money import FlatMoneyManager
from ..bot.phases import PhaseMachine
from ..game.paytable import Paytable
from ..strategies import PatternStrategy


@dataclass(frozen=True)
class SessionOutcome:
    profit: Decimal
    rounds: int
    stop_reason: str | None

    @property
    def day_over(self) -> bool:
        # A bankroll that cannot cover the next stake can never recover.
        return self.stop_reason in ("bankroll exhausted", "insufficient bankroll for next stake")


@dataclass(frozen=True)
class DayOutcome:
    day: int
    net: Decimal
    wagered: Decimal
    sessions: int
    winning_sessions: int
    rounds: int
    bust: bool


def _play_one_session(
    stream,
    bot: KenoBot,
    max_rounds: int,
) -> SessionOutcome:
    played = 0
    for record in stream:
        bot.handle_round(record)
        played += 1
        if bot.stop_reason is not None or played >= max_rounds:
            break
    # Count CONSUMED records (played), not stats.rounds: a round that ends in
    # bankruptcy is consumed without incrementing the bot's own counter.
    return SessionOutcome(bot.stats.profit, played, bot.stop_reason)


def _run_days(
    days: int,
    rounds_per_day: int,
    money_factory,
    paytable: Paytable,
    pick_count: int,
    starting_bankroll: Decimal,
    stop_win: Decimal | None,
    stop_loss: Decimal | None,
    seed: str,
    rng_seed: int,
    use_stops: bool,
) -> list[DayOutcome]:
    outcomes: list[DayOutcome] = []
    for day in range(days):
        stream = iter_synthetic_rounds(rounds_per_day, seed=seed, client_seed=f"day-{day}")
        bankroll = starting_bankroll
        day_start = bankroll
        wagered = Decimal("0")
        sessions = winning = 0
        played_total = 0
        bust = False
        while played_total < rounds_per_day and not bust:
            bot = KenoBot(
                PatternStrategy(),
                money_factory(),
                paytable,
                pick_count=pick_count,
                bankroll=bankroll,
                rng_seed=rng_seed + day * 1000 + sessions,
                stop_win=stop_win if use_stops else None,
                stop_loss=stop_loss if use_stops else None,
            )
            outcome = _play_one_session(stream, bot, rounds_per_day - played_total)
            played_total += outcome.rounds
            bankroll = bot.bankroll
            wagered += bot.stats.total_bet
            sessions += 1
            winning += 1 if outcome.profit > 0 else 0
            if outcome.day_over:
                bust = True
        outcomes.append(
            DayOutcome(
                day=day,
                net=bankroll - day_start,
                wagered=wagered,
                sessions=sessions,
                winning_sessions=winning,
                rounds=played_total,
                bust=bust,
            )
        )
    return outcomes


def _day_summary(label: str, days: list[DayOutcome]) -> dict:
    nets = sorted(d.net for d in days)
    positive = sum(1 for n in nets if n > 0)

    def pct(q: float) -> Decimal:
        pos = (len(nets) - 1) * q
        low = int(pos)
        high = min(low + 1, len(nets) - 1)
        return nets[low] + (nets[high] - nets[low]) * Decimal(str(pos - low))

    return {
        "label": label,
        "days": len(days),
        "positive_days_pct": positive / len(days) if days else 0.0,
        "median_day": str(pct(0.5)),
        "p05_day": str(pct(0.05)),
        "p95_day": str(pct(0.95)),
        "best_day": str(nets[-1] if nets else Decimal("0")),
        "worst_day": str(nets[0] if nets else Decimal("0")),
        "mean_sessions_per_day": statistics.fmean(d.sessions for d in days) if days else 0.0,
        "session_win_rate": (sum(d.winning_sessions for d in days) / sum(d.sessions for d in days)) if days and sum(d.sessions for d in days) else 0.0,
        "mean_rounds_per_day": statistics.fmean(d.rounds for d in days) if days else 0.0,
        "bust_days": sum(1 for d in days if d.bust),
    }


def run_daily_simulation(
    days: int = 30,
    hours: float = 24.0,
    pace_seconds: float = 3.5,
    stop_win: str = "0.5",
    stop_loss: str = "2.0",
    paytable_path: str = "configs/payout.yaml",
    phase_config: str = "configs/bot_phase.yaml",
    pick_count: int = 10,
    bankroll: str = "10.00000000",
    seed: str = "keno-daily-v1",
    rng_seed: int = 23,
    out_prefix: str = "reports/daily",
) -> dict:
    """Simulate full days of unattended operation at the reference bot's real pace.

    The reference's screenshots show ~3.5s per round (~24,700 rounds/day). The phase
    arm cycles sessions that bank profits at stop-win and cut at stop-loss; the
    flat arm plays the same rounds without stops. This quantifies what "run it
    for 24 hours" actually produces on a -1% EV random game.
    """
    if days <= 0 or hours <= 0 or pace_seconds <= 0:
        raise ValueError("days, hours and pace_seconds must be positive")
    paytable = Paytable.from_yaml(paytable_path)
    phase = PhaseMachine.from_yaml(phase_config)
    rounds_per_day = int(hours * 3600 / pace_seconds)
    win = Decimal(stop_win) if stop_win else None
    loss = Decimal(stop_loss) if stop_loss else None

    phase_days = _run_days(
        days, rounds_per_day, phase.clone, paytable, pick_count,
        Decimal(bankroll), win, loss, seed, rng_seed, use_stops=True,
    )
    flat_days = _run_days(
        days, rounds_per_day, lambda: FlatMoneyManager(Decimal("0.01")), paytable, pick_count,
        Decimal(bankroll), win, loss, seed, rng_seed, use_stops=False,
    )

    report = {
        "mode": "daily_simulation",
        "real_money": False,
        "days": days,
        "hours_per_day": hours,
        "pace_seconds": pace_seconds,
        "rounds_per_day": rounds_per_day,
        "stop_win": stop_win,
        "stop_loss": stop_loss,
        "pick_count": pick_count,
        "bankroll": bankroll,
        "seed": seed,
        "phase_arm": _day_summary("phase+stops", phase_days),
        "flat_arm": _day_summary("flat continuous", flat_days),
    }

    out = Path(out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def arm_lines(arm: dict) -> list[str]:
        return [
            f"## {arm['label']}",
            "",
            f"- 盈利天数占比: {arm['positive_days_pct']:.1%}（{arm['days']} 天）",
            f"- 单日收益 中位 / P5 / P95: {arm['median_day']} / {arm['p05_day']} / {arm['p95_day']}",
            f"- 最好 / 最差一天: {arm['best_day']} / {arm['worst_day']}",
            f"- 每天会话数: {arm['mean_sessions_per_day']:.1f}，会话胜率: {arm['session_win_rate']:.1%}",
            f"- 每天局数: {arm['mean_rounds_per_day']:.0f}，爆仓天数: {arm['bust_days']}",
            "",
        ]

    md = [
        "# 24 小时连续运行模拟",
        "",
        f"- {days} 天 × {hours} 小时，节奏 {pace_seconds} 秒/局 ≈ 每天 {rounds_per_day} 局（参考 bot 实测节奏）",
        f"- phase 臂：复刻结构 + 止盈 {stop_win} / 止损 {stop_loss}，赢了入袋开新会话",
        "- flat 臂：同一开奖流，flat 0.01 连续不停",
        "",
    ]
    md += arm_lines(report["phase_arm"])
    md += arm_lines(report["flat_arm"])
    out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return report
