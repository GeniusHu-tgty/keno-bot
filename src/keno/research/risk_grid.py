from __future__ import annotations

"""Paper-only stop/target/session-duration parameter grid.

This module deliberately delegates every round to ``run_strategy_grid``.  It
does not search for a winning rule from future draws; it compares predefined
risk-control settings on the same reproducible draw stream.
"""

import json
import threading
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .strategy_grid import run_strategy_grid


# Ratios of the initial bankroll, matching the plan's 0.1%, 0.25%, 0.5%
# and 1% take-profit / 0.25%, 0.5%, 1% and 2% stop-loss grid.
STOP_WINS = (None, "0.001", "0.0025", "0.005", "0.01")
STOP_LOSSES = (None, "0.0025", "0.005", "0.01", "0.02")
SESSION_MINUTES = (30, 60, 240, 720, 1440)


def _duration_rounds(minutes: int, pace_seconds: float) -> int:
    return max(1, round(minutes * 60 / max(0.1, pace_seconds)))


def run_risk_grid(
    *,
    sessions: int = 1000,
    risk: str = "medium",
    pick_count: int = 10,
    bankroll: str = "10",
    pace_seconds: float = 3.5,
    candidate: str = "flat-min",
    selection_mode: str = "random",
    seed: str = "keno-risk-grid-2026-09-11",
    selection_seed: int = 9911,
    stop_wins: Iterable[str | None] = STOP_WINS,
    stop_losses: Iterable[str | None] = STOP_LOSSES,
    session_minutes: Iterable[int] = SESSION_MINUTES,
    progress_callback=None,
    cancel_event: threading.Event | None = None,
    out_prefix: str = "reports/risk_grid",
) -> dict:
    """Run a bounded, reproducible risk-control grid.

    ``sessions`` is the number of sessions per cell.  The total number of
    cells is normally 125; callers can pass smaller tuples for smoke tests.
    """
    if sessions <= 0:
        raise ValueError("sessions must be positive")
    wins = tuple(stop_wins)
    losses = tuple(stop_losses)
    durations = tuple(int(x) for x in session_minutes)
    if not wins or not losses or not durations:
        raise ValueError("risk grid dimensions must not be empty")
    total = len(wins) * len(losses) * len(durations)
    rows: list[dict] = []
    bankroll_decimal = Decimal(bankroll)
    completed = 0
    for win in wins:
        for loss in losses:
            for minutes in durations:
                if cancel_event is not None and cancel_event.is_set():
                    break
                rounds = _duration_rounds(minutes, pace_seconds)
                absolute_win = (
                    str(bankroll_decimal * Decimal(win)) if win is not None else None
                )
                absolute_loss = (
                    str(bankroll_decimal * Decimal(loss)) if loss is not None else None
                )
                report = run_strategy_grid(
                    sessions=sessions,
                    rounds_per_session=rounds,
                    risk=risk,
                    pick_count=pick_count,
                    bankroll=bankroll,
                    # Common Random Numbers: every cell receives the same
                    # underlying draw stream; only its risk controls differ.
                    seed=seed,
                    selection_seed=selection_seed,
                    pace_seconds=pace_seconds,
                    candidates=(candidate,),
                    selection_modes=(selection_mode,),
                    stop_win=absolute_win,
                    stop_loss=absolute_loss,
                    out_prefix=f"{out_prefix}_cell_{completed:03d}",
                )
                row = dict(report["rows"][0])
                row.update({
                    "stop_win": absolute_win,
                    "stop_loss": absolute_loss,
                    "stop_win_pct": win,
                    "stop_loss_pct": loss,
                    "session_minutes": minutes,
                    "rounds_per_session": rounds,
                })
                rows.append(row)
                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, total)
            if cancel_event is not None and cancel_event.is_set():
                break
        if cancel_event is not None and cancel_event.is_set():
            break

    rows.sort(key=lambda row: (
        row["mean_roi_pct"],
        -float(row["ruin_pct"]),
        -float(row["mean_max_drawdown"]),
    ), reverse=True)
    report = {
        "mode": "risk_grid",
        "real_money": False,
        "sessions_per_cell": sessions,
        "risk": risk,
        "pick_count": pick_count,
        "bankroll": bankroll,
        "pace_seconds": pace_seconds,
        "candidate": candidate,
        "selection_mode": selection_mode,
        "stop_wins": list(wins),
        "stop_losses": list(losses),
        "session_minutes": list(durations),
        "completed_cells": completed,
        "total_cells": total,
        "cancelled": bool(cancel_event is not None and cancel_event.is_set()),
        "rows": rows,
        "conclusion": (
            "B：参数只改变风险形状；未证明正收益"
            if rows else "C：数据不足，需要继续采集和验证"
        ),
    }
    out = Path(out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Risk Grid（纸面止盈 / 止损 / 会话长度对照）",
        "",
        f"- 每格 {sessions} 会话 · {risk} / {pick_count} 选 · {pace_seconds}s/局",
        "- 仅比较风险控制形状，不把绿色率或短期 ROI 当作可预测优势。",
        "",
        "| 止盈 | 止损 | 会话 | 局数上限 | ROI | CI半宽 | 绿色率 | 爆仓率 | 平均回撤 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['stop_win_pct'] or '关闭'} | {row['stop_loss_pct'] or '关闭'} | "
            f"{row['session_minutes']}m | {row['rounds_per_session']} | "
            f"{row['mean_roi_pct']:.3f}% | +/-{row['roi_ci95_pct']:.3f}% | "
            f"{row['green_pct']:.1%} | {row['ruin_pct']:.1%} | "
            f"{row['mean_max_drawdown']} |"
        )
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
