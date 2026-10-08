from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from random import Random
from typing import Iterator

from ..bot.bot import KenoBot
from ..bot.datasource import iter_synthetic_rounds
from ..bot.money import FlatMoneyManager
from ..bot.phases import PhaseMachine
from ..data.schema import RoundRecord
from ..game.paytable import Paytable
from ..strategies import PatternStrategy


@dataclass(frozen=True)
class SessionResult:
    profit: Decimal
    wagered: Decimal
    rounds: int
    success_rate: float
    max_drawdown: Decimal

    @classmethod
    def from_bot(cls, bot: KenoBot) -> "SessionResult":
        s = bot.stats
        return cls(s.profit, s.total_bet, s.rounds, float(s.success_rate), s.max_drawdown)


def _run_stream(
    records: Iterator[RoundRecord],
    rounds_per_session: int,
    sessions: int,
    money_factory,
    paytable: Paytable,
    pick_count: int,
    bankroll: Decimal,
    rng_seed: int,
) -> list[SessionResult]:
    results = []
    for index in range(sessions):
        strategy = PatternStrategy()
        money = money_factory()
        bot = KenoBot(strategy, money, paytable, pick_count=pick_count, bankroll=bankroll, rng_seed=rng_seed + index)
        played = 0
        for record in records:
            bot.handle_round(record)
            played += 1
            if bot.bankrupt or played >= rounds_per_session:
                break
        results.append(SessionResult.from_bot(bot))
    return results


def _percentile(sorted_values: list[Decimal], q: float) -> Decimal:
    if not sorted_values:
        return Decimal("0")
    position = (len(sorted_values) - 1) * q
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    frac = Decimal(str(position - low))
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac


def _summarize(label: str, results: list[SessionResult], benchmark_profit: Decimal | None) -> dict:
    profits = sorted(r.profit for r in results)
    count = len(profits)
    profitable = sum(1 for p in profits if p > 0)
    summary = {
        "label": label,
        "sessions": count,
        "profitable_pct": profitable / count if count else 0.0,
        "mean_profit": str(sum(profits, Decimal("0")) / count if count else Decimal("0")),
        "median_profit": str(_percentile(profits, 0.5)),
        "p05_profit": str(_percentile(profits, 0.05)),
        "p25_profit": str(_percentile(profits, 0.25)),
        "p75_profit": str(_percentile(profits, 0.75)),
        "p95_profit": str(_percentile(profits, 0.95)),
        "max_profit": str(profits[-1] if profits else Decimal("0")),
        "min_profit": str(profits[0] if profits else Decimal("0")),
        "mean_wagered": str(sum((r.wagered for r in results), Decimal("0")) / count if count else Decimal("0")),
        "mean_success_rate": statistics.fmean(r.success_rate for r in results) if results else 0.0,
        "mean_max_drawdown": str(sum((r.max_drawdown for r in results), Decimal("0")) / count if count else Decimal("0")),
    }
    if benchmark_profit is not None and profits:
        below = sum(1 for p in profits if p < benchmark_profit)
        summary["benchmark_profit"] = str(benchmark_profit)
        summary["benchmark_percentile"] = below / count
    return summary


def run_session_monte_carlo(
    sessions: int = 1000,
    rounds_per_session: int = 176,
    paytable_path: str = "configs/payout.yaml",
    phase_config: str = "configs/bot_phase.yaml",
    pick_count: int = 10,
    bankroll: str = "1.00000000",
    seed: str = "keno-sessions-v1",
    rng_seed: int = 11,
    benchmark_profit: str | None = "0.7129",
    benchmark_rounds: int = 176,
    flat_control_bet: str | None = "0.01",
    out_prefix: str = "reports/sessions",
) -> dict:
    """Monte Carlo over independent bot sessions on true-random synthetic rounds.

    Two arms on identical streams: the reconstructed phase machine and a flat
    control. This measures what the phase-style session distribution looks like
    when there is no predictive edge at all - the null model for reading his
    screenshots.
    """
    if sessions <= 0 or rounds_per_session <= 0:
        raise ValueError("sessions and rounds_per_session must be positive")
    paytable = Paytable.from_yaml(paytable_path)
    phase = PhaseMachine.from_yaml(phase_config)
    benchmark = Decimal(benchmark_profit) if benchmark_profit is not None else None

    total = sessions * rounds_per_session
    # Same seed for both arms: each arm replays an identical round stream.
    phase_results = _run_stream(
        iter_synthetic_rounds(total, seed=seed), rounds_per_session, sessions,
        phase.clone,
        paytable, pick_count, Decimal(bankroll), rng_seed,
    )
    flat_results = []
    if flat_control_bet is not None:
        flat_results = _run_stream(
            iter_synthetic_rounds(total, seed=seed), rounds_per_session, sessions,
            lambda: FlatMoneyManager(Decimal(flat_control_bet)),
            paytable, pick_count, Decimal(bankroll), rng_seed,
        )

    report = {
        "mode": "session_monte_carlo",
        "real_money": False,
        "sessions": sessions,
        "rounds_per_session": rounds_per_session,
        "pick_count": pick_count,
        "seed": seed,
        "phase_config": str(phase_config),
        "benchmark": {"profit": str(benchmark) if benchmark else None, "rounds": benchmark_rounds},
        "phase_arm": _summarize("phase", phase_results, benchmark),
        "flat_arm": _summarize("flat", flat_results, None) if flat_results else None,
    }

    out = Path(out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def arm_table(arm: dict | None) -> list[str]:
        if arm is None:
            return []
        lines = [
            f"## {arm['label']} arm",
            "",
            f"- 会话数: {arm['sessions']}",
            f"- 盈利会话占比: {arm['profitable_pct']:.1%}",
            f"- 平均投注额: {arm['mean_wagered']}",
            f"- 平均成功率: {arm['mean_success_rate']:.1%}",
            f"- 收益分位数 P5/P25/中位/P75/P95: {arm['p05_profit']} / {arm['p25_profit']} / {arm['median_profit']} / {arm['p75_profit']} / {arm['p95_profit']}",
            f"- 最好/最差会话: {arm['max_profit']} / {arm['min_profit']}",
            f"- 平均最大回撤: {arm['mean_max_drawdown']}",
        ]
        if "benchmark_percentile" in arm:
            lines.append(f"- 基准收益 {arm['benchmark_profit']} 的分位位置: {arm['benchmark_percentile']:.1%}")
        lines.append("")
        return lines

    md = [
        "# Session Monte Carlo（零优势零模型）",
        "",
        f"- 会话数 {sessions}，每会话 {rounds_per_session} 局，pick {pick_count}，seed `{seed}`",
        "- 数据流为真随机 synthetic；两臂使用完全相同的开奖流。",
        "- 目的：在没有任何预测优势时，阶段机式会话收益分布长什么样。",
        "",
    ]
    md += arm_table(report["phase_arm"])
    md += arm_table(report["flat_arm"])
    out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return report
