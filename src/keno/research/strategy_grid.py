# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

"""Large, reproducible paper-only strategy grid.

The grid deliberately evaluates staking policies separately from number
selection.  Every candidate sees the same draw stream and the same random
selections, so a short-term winner cannot be mistaken for a predictive edge.
"""

import json
import statistics
import threading
from dataclasses import dataclass
from decimal import Decimal
from math import sqrt
from pathlib import Path
from random import Random

from .. import paths
from ..bot.money import (
    AdaptiveFractionalManager,
    CappedRecoveryManager,
    FlatMoneyManager,
    FractionalMoneyManager,
    MoneyManager,
    ProbeWindowManager,
)
from ..bot.phases import PhaseMachine
from ..game.keno_draw import draw_keno
from ..game.paytable import Paytable
from ..provably_fair.float_generator import FloatGenerator
from ..provably_fair.hmac_rng import HmacSha256Rng
from ..strategies.selection import SELECTION_MODES, select_numbers


MIN_BET = Decimal("0.0001")
QUANT = Decimal("0.00000001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(QUANT)


@dataclass(frozen=True)
class GridCandidate:
    name: str
    kind: str
    description: str
    selection: str = "random"


CANDIDATES = (
    GridCandidate("flat-min", "flat-min", "最低注平注"),
    GridCandidate("flat-001", "flat-001", "0.001u 平注"),
    GridCandidate("fractional", "fractional", "当前余额 0.05%，上限 0.2%"),
    GridCandidate("adaptive", "adaptive", "亏损簇/高波动时降至 0.01%"),
    GridCandidate("probe-window", "probe-window", "30 局探针 + 60 局小额窗口 + 30 局冷却"),
    GridCandidate("capped-recovery", "capped-recovery", "1.25 倍、最多 4 步"),
    GridCandidate("phase", "phase", "阶段机"),
    GridCandidate("martingale", "martingale", "2 倍马丁，仅作失败对照"),
)


def _server_seed(seed: str, session: int, round_index: int) -> str:
    import hashlib

    return hashlib.sha256(f"{seed}:{session}:{round_index}".encode()).hexdigest()


def _draw(seed: str, session: int, round_index: int) -> list[int]:
    server_seed = _server_seed(seed, session, round_index)
    rng = FloatGenerator(
        HmacSha256Rng(server_seed, f"grid-client-{session}", nonce=round_index, cursor=0)
    )
    return draw_keno(rng)


def _manager(candidate: GridCandidate) -> MoneyManager | None:
    if candidate.kind == "flat-min":
        return FlatMoneyManager(MIN_BET)
    if candidate.kind == "flat-001":
        return FlatMoneyManager(Decimal("0.001"))
    if candidate.kind == "fractional":
        return FractionalMoneyManager(
            fraction=Decimal("0.0005"),
            min_bet=MIN_BET,
            max_fraction=Decimal("0.002"),
        )
    if candidate.kind == "adaptive":
        return AdaptiveFractionalManager(
            fraction=Decimal("0.0005"),
            cautious_fraction=Decimal("0.0001"),
            min_bet=MIN_BET,
            max_fraction=Decimal("0.002"),
        )
    if candidate.kind == "probe-window":
        return ProbeWindowManager(
            probe_bet=MIN_BET,
            active_bet=Decimal("0.001"),
            probe_rounds=30,
            active_rounds=60,
            cooldown_rounds=30,
        )
    if candidate.kind == "capped-recovery":
        return CappedRecoveryManager(
            base_bet=MIN_BET,
            multiplier=Decimal("1.25"),
            max_steps=4,
        )
    if candidate.kind == "phase":
        return PhaseMachine.from_yaml(paths.config_file("bot_phase.yaml"))
    if candidate.kind == "martingale":
        return None
    raise ValueError(f"unknown candidate: {candidate.kind}")


def _percentile(values: list[Decimal], q: float) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * Decimal(str(position - low))


def _candidate_summary(
    candidate: GridCandidate,
    profits: list[Decimal],
    staked: list[Decimal],
    rounds_played: list[int],
    drawdowns: list[Decimal],
    min_bankroll_pct: list[Decimal],
    blocks: dict[int, dict],
    ruined: int,
    pace_seconds: float,
    selection: str = "random",
) -> dict:
    count = len(profits)
    roi_values = [
        float(profit / wager) if wager > 0 else 0.0
        for profit, wager in zip(profits, staked)
    ]
    total_wager = sum(staked, Decimal("0"))
    total_profit = sum(profits, Decimal("0"))
    mean_roi = float(total_profit / total_wager) if total_wager > 0 else 0.0
    sample_sd = statistics.stdev(roi_values) if len(roi_values) > 1 else 0.0
    ci = 1.96 * sample_sd / sqrt(len(roi_values)) if roi_values else 0.0
    ordered_profit = sorted(profits, reverse=True)
    top_n = max(1, (len(ordered_profit) + 99) // 100) if ordered_profit else 0
    top_profit = sum(ordered_profit[:top_n], Decimal("0")) if top_n else Decimal("0")
    positive_sessions = sum(p > 0 for p in profits)
    return {
        "name": candidate.name,
        "kind": candidate.kind,
        "description": candidate.description,
        "selection": selection,
        "sessions": count,
        "total_staked": str(_q(total_wager)),
        "total_profit": str(_q(total_profit)),
        "mean_roi_pct": mean_roi * 100,
        "roi_ci95_pct": ci * 100,
        "mean_profit": str(_q(total_profit / count)) if count else "0",
        "median_profit": str(_percentile(profits, 0.5)),
        "p05_profit": str(_percentile(profits, 0.05)),
        "p95_profit": str(_percentile(profits, 0.95)),
        "green_pct": sum(p > 0 for p in profits) / count if count else 0.0,
        "positive_sessions": positive_sessions,
        "top_1pct_profit_share": float(top_profit / total_profit)
        if total_profit > 0 else 0.0,
        "ruin_pct": ruined / count if count else 0.0,
        "mean_rounds": statistics.fmean(rounds_played) if rounds_played else 0.0,
        "median_hours": float(_percentile(
            [Decimal(str(r * pace_seconds / 3600)) for r in rounds_played], 0.5
        )),
        "mean_max_drawdown": str(_q(sum(drawdowns, Decimal("0")) / count)) if count else "0",
        "min_bankroll_pct": float(min(min_bankroll_pct)) if min_bankroll_pct else 0.0,
        "below_50_pct": sum(x < Decimal("0.5") for x in min_bankroll_pct) / count if count else 0.0,
        "below_25_pct": sum(x < Decimal("0.25") for x in min_bankroll_pct) / count if count else 0.0,
        "blocks": [
            {
                "block_index": index,
                "rounds": data["rounds"],
                "sessions": data["sessions"],
                "total_staked": str(_q(data["staked"])),
                "total_profit": str(_q(data["profit"])),
                "roi_pct": float(data["profit"] / data["staked"] * 100)
                if data["staked"] > 0 else 0.0,
                "mean_max_drawdown": str(_q(data["drawdown"] / data["sessions"]))
                if data["sessions"] else "0",
            }
            for index, data in sorted(blocks.items())
        ],
    }


def run_strategy_grid(
    sessions: int = 5000,
    rounds_per_session: int = 176,
    risk: str = "medium",
    pick_count: int = 10,
    bankroll: str = "10",
    seed: str = "keno-grid-2026-09-11",
    selection_seed: int = 9911,
    pace_seconds: float = 3.5,
    candidates: tuple[str, ...] | None = None,
    selection_modes: tuple[str, ...] = ("random",),
    stop_win: str | None = None,
    stop_loss: str | None = None,
    max_drawdown: str | None = None,
    progress_callback=None,
    cancel_event: threading.Event | None = None,
    out_prefix: str | None = None,
) -> dict:
    out_prefix = out_prefix or paths.report_prefix("strategy_grid")
    if sessions <= 0 or rounds_per_session <= 0:
        raise ValueError("sessions and rounds_per_session must be positive")
    if not 1 <= pick_count <= 10:
        raise ValueError("pick_count must be in 1..10")
    if pace_seconds <= 0:
        raise ValueError("pace_seconds must be positive")
    official = json.loads(paths.official_payouts().read_text(encoding="utf-8"))
    if risk not in official["risks"]:
        raise ValueError(f"unknown risk: {risk}")
    for mode in selection_modes:
        if mode not in SELECTION_MODES:
            raise ValueError(f"unknown selection mode: {mode}")
    table = {
        int(k): {h: Decimal(str(v)) for h, v in enumerate(values)}
        for k, values in official["risks"][risk].items()
    }
    selected_names = set(candidates or [c.name for c in CANDIDATES])
    active_money = [c for c in CANDIDATES if c.name in selected_names]
    if not active_money:
        raise ValueError("at least one candidate is required")
    active = [
        GridCandidate(
            name=c.name if len(selection_modes) == 1 else f"{mode}/{c.name}",
            kind=c.kind,
            description=c.description,
            selection=mode,
        )
        for mode in selection_modes
        for c in active_money
    ]
    win_limit = Decimal(stop_win) if stop_win is not None else None
    loss_limit = abs(Decimal(stop_loss)) if stop_loss is not None else None
    drawdown_limit = abs(Decimal(max_drawdown)) if max_drawdown is not None else None

    starting_bankroll = Decimal(bankroll)
    block_size = max(1, round(15 * 60 / pace_seconds))
    results: dict[str, dict[str, list]] = {
        c.name: {
            "profits": [],
            "staked": [],
            "rounds": [],
            "drawdowns": [],
            "min_bankroll_pct": [],
            "blocks": {},
            "ruined": 0,
        }
        for c in active
    }

    # Common random numbers: all candidates get the same draws and selections.
    for session in range(sessions):
        if cancel_event is not None and cancel_event.is_set():
            break
        draws = [_draw(seed, session, r) for r in range(rounds_per_session)]
        selections_by_mode: dict[str, list[list[int]]] = {}
        for mode_index, mode in enumerate(selection_modes):
            mode_rng = Random(selection_seed + session * 1000 + mode_index)
            history = []
            block_picks: list[int] | None = None
            selections: list[list[int]] = []
            for r in range(rounds_per_session):
                block_size = max(1, round(15 * 60 / pace_seconds))
                if mode == "block-random":
                    block = r // block_size
                    if block_picks is None or r % block_size == 0:
                        block_picks = select_numbers(mode, history, pick_count, mode_rng, block_index=block)
                    current = list(block_picks)
                else:
                    current = select_numbers(
                        mode,
                        history,
                        pick_count,
                        mode_rng,
                        block_index=r,
                    )
                selections.append(current)
                history.append(type("_Record", (), {"numbers": draws[r]})())
            selections_by_mode[mode] = selections
        for candidate in active:
            manager = _manager(candidate)
            bankroll_now = starting_bankroll
            profit = Decimal("0")
            wagered = Decimal("0")
            peak = Decimal("0")
            max_dd = Decimal("0")
            min_bankroll = starting_bankroll
            played = 0
            mart_step = 0
            ruined = False
            history = []
            selections = selections_by_mode[candidate.selection]
            for r, drawn in enumerate(draws):
                if manager is not None:
                    if manager.should_pause():
                        ruined = False
                        break
                    bet = manager.next_bet(bankroll_now)
                elif candidate.kind == "martingale":
                    bet = MIN_BET * (Decimal("2") ** mart_step)
                else:
                    raise AssertionError(candidate.kind)
                if bet < MIN_BET or bet > bankroll_now:
                    ruined = True
                    break
                hits = len(set(selections[r]) & set(drawn))
                payout = _q(bet * table[pick_count][hits])
                round_profit = payout - bet
                bankroll_now = _q(bankroll_now + round_profit)
                profit += round_profit
                wagered += bet
                played += 1
                if manager is not None:
                    manager.observe(round_profit)
                if candidate.kind == "martingale":
                    mart_step = mart_step + 1 if payout == 0 else 0
                peak = max(peak, profit)
                max_dd = max(max_dd, peak - profit)
                min_bankroll = min(min_bankroll, bankroll_now)
                block = r // block_size
                block_data = results[candidate.name]["blocks"].setdefault(
                    block,
                    {
                        "rounds": 0,
                        "sessions": 0,
                        "staked": Decimal("0"),
                        "profit": Decimal("0"),
                        "drawdown": Decimal("0"),
                    },
                )
                block_data["rounds"] += 1
                block_data["staked"] += bet
                block_data["profit"] += round_profit
                block_data["drawdown"] = max(block_data["drawdown"], max_dd)
                if win_limit is not None and profit >= win_limit:
                    break
                if loss_limit is not None and profit <= -loss_limit:
                    break
                if drawdown_limit is not None and max_dd >= drawdown_limit:
                    break
            row = results[candidate.name]
            row["profits"].append(profit)
            row["staked"].append(wagered)
            row["rounds"].append(played)
            row["drawdowns"].append(max_dd)
            row["min_bankroll_pct"].append(min_bankroll / starting_bankroll if starting_bankroll > 0 else Decimal("0"))
            row["ruined"] += int(ruined)
            for block_data in results[candidate.name]["blocks"].values():
                if block_data["rounds"] and block_data["sessions"] < session + 1:
                    block_data["sessions"] += 1
        if progress_callback is not None:
            progress_callback(session + 1, sessions)

    rows = [
        _candidate_summary(
            c,
            results[c.name]["profits"],
            results[c.name]["staked"],
            results[c.name]["rounds"],
            results[c.name]["drawdowns"],
            results[c.name]["min_bankroll_pct"],
            results[c.name]["blocks"],
            results[c.name]["ruined"],
            pace_seconds,
            c.selection,
        )
        for c in active
    ]
    rows.sort(key=lambda row: row["mean_roi_pct"], reverse=True)
    report = {
        "mode": "strategy_grid",
        "real_money": False,
        "generated_at": "2026-09-11",
        "sessions": sessions,
        "rounds_per_session": rounds_per_session,
        "risk": risk,
        "pick_count": pick_count,
        "bankroll": str(starting_bankroll),
        "pace_seconds": pace_seconds,
        "block_rounds": block_size,
        "seed": seed,
        "selection_seed": selection_seed,
        "selection_modes": list(selection_modes),
        "stop_win": str(win_limit) if win_limit is not None else None,
        "stop_loss": str(loss_limit) if loss_limit is not None else None,
        "max_drawdown": str(drawdown_limit) if drawdown_limit is not None else None,
        "common_random_numbers": True,
        "cancelled": bool(cancel_event is not None and cancel_event.is_set()),
        "rows": rows,
        "note": "所有候选共享同一开奖流和同一批随机选号；ROI 只用于统计比较，不代表预测优势。",
    }
    out = Path(out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Strategy Grid（纸面大规模对照）",
        "",
        f"- {sessions} 会话 × {rounds_per_session} 局，{risk} / {pick_count} 选，节奏 {pace_seconds}s/局",
        "- 所有候选共享同一开奖流和同一批随机选号。",
        "- `roi_ci95_pct` 是会话 ROI 的近似 95% 置信区间，仅作比较。",
        "",
        "| 候选 | 选号 | 总投注 | 总收益 | ROI | 95% CI半宽 | 绿色率 | 爆仓率 | 中位收益 | 平均回撤 | 最低余额 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['selection']} | {row['total_staked']} | {row['total_profit']} | "
            f"{row['mean_roi_pct']:.3f}% | +/-{row['roi_ci95_pct']:.3f}% | "
            f"{row['green_pct']:.1%} | {row['ruin_pct']:.1%} | {row['median_profit']} | "
            f"{row['mean_max_drawdown']} | {row['min_bankroll_pct']:.1%} |"
        )
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
