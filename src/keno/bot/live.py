# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from ..data.schema import jsonable
from ..game.paytable import Paytable
from ..strategies import (
    ColdStrategy,
    HotStrategy,
    PatternStrategy,
    RandomStrategy,
    SelectionStrategy,
)
from .bot import KenoBot
from .datasource import iter_replay_rounds, iter_synthetic_rounds
from .money import (
    CappedRecoveryManager,
    AdaptiveFractionalManager,
    FlatMoneyManager,
    FractionalMoneyManager,
    MoneyManager,
    PhaseRecoveryManager,
    ProbeWindowManager,
)
from .phases import PhaseMachine

STRATEGY_FACTORIES = {
    "random": RandomStrategy,
    "hot": HotStrategy,
    "cold": ColdStrategy,
    "pattern": PatternStrategy,
    "block-random": lambda: SelectionStrategy("block-random"),
    "fixed-pattern": lambda: SelectionStrategy("fixed-pattern"),
    "avoid-cold-zone": lambda: SelectionStrategy("avoid-cold-zone"),
    "balanced-random": lambda: SelectionStrategy("balanced-random"),
}


@dataclass
class BotConfig:
    source: str = "synthetic"  # synthetic | replay | ws
    rounds: int = 1000
    strategy: str = "random"
    pick_count: int = 1
    bet: str = "0.00010000"
    bankroll: str = "0.01000000"
    money: str = "flat"  # flat | recovery | phase | fractional | adaptive | probe | capped
    recovery_multiplier: str = "2"
    max_recovery_steps: int = 8
    paytable_path: str = "configs/payout.yaml"
    difficulty: str = "default"
    phase_config: str = "configs/bot_phase.yaml"
    seed: str = "keno-bot-v1"
    rng_seed: int = 7
    interval: float = 0.0  # seconds between rounds when source streams live
    display_every: int = 100
    replay_file: str | None = None
    out_prefix: str = "reports/bot"
    ws_port: int = 8765
    stop_win: str | None = None
    stop_loss: str | None = None
    unattended: bool = False
    hours: float = 0.0
    max_sessions: int = 0
    extra: dict = field(default_factory=dict)

    def validate(self) -> None:
        if self.source not in ("synthetic", "replay", "ws"):
            raise ValueError("source must be synthetic, replay or ws")
        if self.source == "replay" and not self.replay_file:
            raise ValueError("--replay-file is required when source=replay")
        if self.strategy not in STRATEGY_FACTORIES:
            raise ValueError(f"strategy must be one of {sorted(STRATEGY_FACTORIES)}")
        if self.money not in (
            "flat",
            "recovery",
            "phase",
            "fractional",
            "adaptive",
            "probe",
            "capped",
        ):
            raise ValueError("money must be flat, recovery, phase, fractional, adaptive, probe or capped")
        if not 1 <= self.pick_count <= 10:
            raise ValueError("pick_count must be in 1..10")
        if self.rounds <= 0:
            raise ValueError("rounds must be positive")


def build_money_manager(config: BotConfig) -> MoneyManager:
    base = Decimal(config.bet)
    if config.money == "flat":
        return FlatMoneyManager(base)
    if config.money == "phase":
        return PhaseMachine.from_yaml(config.phase_config)
    if config.money == "fractional":
        return FractionalMoneyManager(
            fraction=Decimal("0.0005"),
            min_bet=Decimal("0.0001"),
            max_fraction=Decimal("0.002"),
        )
    if config.money == "adaptive":
        return AdaptiveFractionalManager(
            fraction=Decimal("0.0005"),
            cautious_fraction=Decimal("0.0001"),
            min_bet=Decimal("0.0001"),
            max_fraction=Decimal("0.002"),
        )
    if config.money == "probe":
        return ProbeWindowManager(
            probe_bet=Decimal("0.0001"),
            active_bet=base,
            probe_rounds=30,
            active_rounds=60,
            cooldown_rounds=30,
        )
    if config.money == "capped":
        return CappedRecoveryManager(
            base_bet=base,
            multiplier=Decimal("1.25"),
            max_steps=4,
        )
    return PhaseRecoveryManager(base, Decimal(config.recovery_multiplier), config.max_recovery_steps)


def make_source(config: BotConfig) -> Iterable:
    if config.source == "synthetic":
        return iter_synthetic_rounds(config.rounds, seed=config.seed)
    if config.source == "replay":
        return iter_replay_rounds(config.replay_file, limit=config.rounds)
    raise ValueError("ws source is consumed by run_mock_ws_bot, not make_source")


def build_bot(config: BotConfig, paytable: Paytable) -> KenoBot:
    strategy = STRATEGY_FACTORIES[config.strategy]()
    money = build_money_manager(config)
    return KenoBot(
        strategy,
        money,
        paytable,
        pick_count=config.pick_count,
        bankroll=Decimal(config.bankroll),
        difficulty=config.difficulty,
        rng_seed=config.rng_seed,
        stop_win=Decimal(config.stop_win) if config.stop_win else None,
        stop_loss=Decimal(config.stop_loss) if config.stop_loss else None,
    )


def write_bot_outputs(config: BotConfig, bot: KenoBot, summary: dict) -> None:
    out = Path(config.out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    summary_path = out.with_suffix(".json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    stats = bot.stats
    sign = "+" if stats.profit >= 0 else ""
    lines = [
        "# Keno Paper Bot Report",
        "",
        "- real_money: `false`",
        f"- source: `{config.source}`",
        f"- strategy: `{config.strategy}`",
        f"- money: `{config.money}`",
        f"- pick_count: {config.pick_count}",
        f"- bet: `{config.bet}`",
        f"- starting_bankroll: `{config.bankroll}`",
        f"- rounds: {stats.rounds}" + (f" (stopped early: {bot.stop_reason})" if bot.stop_reason else ""),
        "",
        "| 总局数 | 总投注 | 总回收 | 总收益 | ROI | 成功率 | 最大回撤 | 最长连亏 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {stats.rounds} | {stats.total_bet} | {stats.total_payout} | {sign}{stats.profit} | {stats.roi:+.2%} | {stats.success_rate:.1%} | {stats.max_drawdown} | {stats.longest_loss_streak} |",
        "",
        "## 命中统计",
        "",
    ]
    lines += [f"- {k} Hits: {stats.hits.get(k, 0)}" for k in sorted(stats.hits)]
    lines += ["", f"明细日志: `{out.with_name(out.name + '_rounds.jsonl')}`", ""]
    out.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")


def run_paper_bot(config: BotConfig) -> dict:
    """Run the paper bot over a synthetic or replay stream and persist outputs."""
    if config.unattended:
        return run_unattended_paper_bot(config)
    config.validate()
    paytable = Paytable.from_yaml(config.paytable_path)
    bot = build_bot(config, paytable)
    log_path = Path(config.out_prefix + "_rounds.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")

    def logger(payload: dict) -> None:
        log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    source = make_source(config)
    for record in source:
        bot.handle_round(record, logger)
        if bot.stats.rounds % config.display_every == 0 and bot.stop_reason is None:
            print(bot.stats.render(config.pick_count, bot.money_manager.phase))
        if bot.stop_reason is not None:
            break
        if config.interval > 0:
            import time

            time.sleep(config.interval)
    log_file.close()
    summary = build_summary(config, bot, log_path)
    write_bot_outputs(config, bot, summary)
    print(bot.stats.render(config.pick_count, bot.money_manager.phase))
    print(f"stop_reason={bot.stop_reason or 'rounds completed'}")
    print(f"summary={Path(config.out_prefix).with_suffix('.json')}")
    return summary


def run_unattended_paper_bot(config: BotConfig) -> dict:
    """Cycle paper sessions until hours, max_sessions, or bankroll stop."""
    import time

    config.validate()
    paytable = Paytable.from_yaml(config.paytable_path)
    hours = float(config.hours or 0)
    max_sessions = int(config.max_sessions or 0)
    if max_sessions <= 0 and hours <= 0:
        hours = 24.0
    session_rounds = config.rounds
    estimated = session_rounds * (max_sessions or 100000)
    if hours > 0 and config.interval > 0:
        estimated = max(estimated, int(hours * 3600 / config.interval) + session_rounds)
    if config.source == "replay":
        source_iter = iter(make_source(config))
    else:
        source_iter = iter_synthetic_rounds(estimated, seed=config.seed)
    log_path = Path(config.out_prefix + "_rounds.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    bankroll = Decimal(config.bankroll)
    starting = bankroll
    sessions: list[dict] = []
    wall_start = time.time()
    total_rounds = 0
    stop_all = "sessions completed"

    def logger(payload: dict) -> None:
        log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    try:
        while True:
            if hours and (time.time() - wall_start) >= hours * 3600:
                stop_all = "hours completed"
                break
            if max_sessions and len(sessions) >= max_sessions:
                stop_all = "sessions completed"
                break
            if bankroll <= 0:
                stop_all = "bankroll exhausted"
                break
            session_config = BotConfig(
                source=config.source,
                rounds=session_rounds,
                strategy=config.strategy,
                pick_count=config.pick_count,
                bet=config.bet,
                bankroll=str(bankroll),
                money=config.money,
                recovery_multiplier=config.recovery_multiplier,
                max_recovery_steps=config.max_recovery_steps,
                paytable_path=config.paytable_path,
                difficulty=config.difficulty,
                phase_config=config.phase_config,
                seed=config.seed,
                rng_seed=config.rng_seed + len(sessions) * 17,
                interval=config.interval,
                display_every=config.display_every,
                replay_file=config.replay_file,
                out_prefix=config.out_prefix,
                stop_win=config.stop_win,
                stop_loss=config.stop_loss,
            )
            bot = build_bot(session_config, paytable)
            played = 0
            for record in source_iter:
                bot.handle_round(record, logger)
                played += 1
                total_rounds += 1
                if bot.stats.rounds % config.display_every == 0 and bot.stop_reason is None:
                    print(bot.stats.render(config.pick_count, bot.money_manager.phase))
                if bot.stop_reason is not None or played >= session_rounds:
                    break
                if config.interval > 0:
                    time.sleep(config.interval)
                if hours and (time.time() - wall_start) >= hours * 3600:
                    bot.stop_reason = bot.stop_reason or "hours completed"
                    break
            bankroll = bot.bankroll
            sessions.append({
                "index": len(sessions) + 1,
                "rounds": bot.stats.rounds,
                "profit": str(bot.stats.profit),
                "stop_reason": bot.stop_reason or "rounds completed",
                "bankroll": str(bankroll),
            })
            print(
                f"session {len(sessions)} stop={sessions[-1]['stop_reason']} "
                f"profit={sessions[-1]['profit']} bankroll={bankroll}"
            )
            if bot.stop_reason in ("bankroll exhausted", "insufficient bankroll for next stake"):
                stop_all = bot.stop_reason
                break
            if bot.stop_reason == "hours completed":
                stop_all = "hours completed"
                break
    finally:
        log_file.close()

    summary = {
        "mode": "unattended_paper_bot",
        "real_money": False,
        "source": config.source,
        "strategy": config.strategy,
        "money": config.money,
        "pick_count": config.pick_count,
        "starting_bankroll": str(starting),
        "ending_bankroll": str(bankroll),
        "session_count": len(sessions),
        "green_sessions": sum(1 for row in sessions if Decimal(row["profit"]) > 0),
        "rounds_played": total_rounds,
        "stop_reason": stop_all,
        "hours": hours,
        "sessions": sessions,
        "profit": str(bankroll - starting),
        "log": str(log_path),
    }
    out = Path(config.out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Keno Unattended Paper Bot",
        "",
        "- real_money: `false`",
        f"- sessions: {len(sessions)}",
        f"- green_sessions: {summary['green_sessions']}",
        f"- rounds: {total_rounds}",
        f"- profit: `{summary['profit']}`",
        f"- stop_reason: `{stop_all}`",
        "",
    ]
    out.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(f"unattended stop_reason={stop_all} sessions={len(sessions)} profit={summary['profit']}")
    print(f"summary={out.with_suffix('.json')}")
    return summary


def build_summary(config: BotConfig, bot: KenoBot, log_path: Path) -> dict:
    stats = bot.stats
    return {
        "mode": "paper_bot",
        "real_money": False,
        "source": config.source,
        "strategy": config.strategy,
        "money": config.money,
        "pick_count": config.pick_count,
        "bet": config.bet,
        "starting_bankroll": config.bankroll,
        "seed": config.seed,
        "rounds_requested": config.rounds,
        "rounds_played": stats.rounds,
        "stop_reason": bot.stop_reason,
        "total_bet": str(stats.total_bet),
        "total_payout": str(stats.total_payout),
        "profit": str(stats.profit),
        "roi": str(stats.roi),
        "success_rate": str(stats.success_rate),
        "bankroll": str(stats.bankroll),
        "hits": {str(k): v for k, v in sorted(stats.hits.items())},
        "max_drawdown": str(stats.max_drawdown),
        "longest_loss_streak": stats.longest_loss_streak,
        "log": str(log_path),
    }
