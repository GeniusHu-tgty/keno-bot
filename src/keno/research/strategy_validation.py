from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from pathlib import Path

from .strategy_grid import run_strategy_grid


DEFAULT_CANDIDATES = (
    "flat-min",
    "flat-001",
    "fractional",
    "adaptive",
    "probe-window",
    "capped-recovery",
    "phase",
    "martingale",
)
DEFAULT_SELECTIONS = (
    "random",
    "block-random",
    "fixed-pattern",
    "hot",
    "cold",
    "avoid-cold-zone",
    "balanced-random",
)


def _aggregate(rows_by_seed: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for rows in rows_by_seed:
        for row in rows:
            grouped[row["name"]].append(row)
    output = []
    for name, rows in grouped.items():
        test_seed_rois = [float(r["mean_roi_pct"]) for r in rows]
        positive_seeds = sum(value > 0 for value in test_seed_rois)
        output.append({
            "name": name,
            "selection": rows[0]["selection"],
            "mean_roi_pct": sum(r["mean_roi_pct"] for r in rows) / len(rows),
            "mean_roi_ci95_half_pct": sum(r["roi_ci95_pct"] for r in rows) / len(rows),
            "mean_green_pct": sum(r["green_pct"] for r in rows) / len(rows),
            "mean_ruin_pct": sum(r["ruin_pct"] for r in rows) / len(rows),
            "mean_profit": sum(float(r["mean_profit"]) for r in rows) / len(rows),
            "mean_max_drawdown": sum(float(r["mean_max_drawdown"]) for r in rows) / len(rows),
            "seeds": len(rows),
            "positive_seed_count": positive_seeds,
            "positive_seed_pct": positive_seeds / len(rows) if rows else 0.0,
            "max_ruin_pct": max(float(r["ruin_pct"]) for r in rows),
            "max_top_1pct_profit_share": max(float(r.get("top_1pct_profit_share", 0.0)) for r in rows),
        })
    return sorted(output, key=lambda row: row["mean_roi_pct"], reverse=True)


def _run_split(
    seeds: list[int],
    *,
    sessions: int,
    rounds_per_session: int,
    risk: str,
    pick_count: int,
    bankroll: str,
    candidates: tuple[str, ...],
    selection_modes: tuple[str, ...],
    pace_seconds: float,
    stop_win: str | None,
    stop_loss: str | None,
    max_drawdown: str | None,
) -> list[dict]:
    reports = []
    with tempfile.TemporaryDirectory(prefix="keno-validation-") as tmp:
        for seed_index, seed in enumerate(seeds):
            report = run_strategy_grid(
                sessions=sessions,
                rounds_per_session=rounds_per_session,
                risk=risk,
                pick_count=pick_count,
                bankroll=bankroll,
                seed=f"keno-validation-{seed}",
                selection_seed=seed,
                pace_seconds=pace_seconds,
                candidates=candidates,
                selection_modes=selection_modes,
                stop_win=stop_win,
                stop_loss=stop_loss,
                max_drawdown=max_drawdown,
                out_prefix=str(Path(tmp) / f"split-{seed_index}"),
            )
            reports.append(report["rows"])
    return reports


def run_strategy_validation(
    *,
    train_seeds: tuple[int, ...] = tuple(range(10)),
    validation_seeds: tuple[int, ...] = tuple(range(10, 20)),
    test_seeds: tuple[int, ...] = tuple(range(20, 30)),
    sessions_per_seed: int = 1000,
    rounds_per_session: int = 176,
    risk: str = "medium",
    pick_count: int = 10,
    bankroll: str = "10",
    candidates: tuple[str, ...] = DEFAULT_CANDIDATES,
    selection_modes: tuple[str, ...] = DEFAULT_SELECTIONS,
    pace_seconds: float = 3.5,
    stop_win: str | None = None,
    stop_loss: str | None = None,
    max_drawdown: str | None = None,
    out_prefix: str = "reports/strategy_validation",
) -> dict:
    if not train_seeds or not validation_seeds or not test_seeds:
        raise ValueError("each split must contain at least one seed")
    train_runs = _run_split(
        list(train_seeds),
        sessions=sessions_per_seed,
        rounds_per_session=rounds_per_session,
        risk=risk,
        pick_count=pick_count,
        bankroll=bankroll,
        candidates=candidates,
        selection_modes=selection_modes,
        pace_seconds=pace_seconds,
        stop_win=stop_win,
        stop_loss=stop_loss,
        max_drawdown=max_drawdown,
    )
    train_summary = _aggregate(train_runs)
    winner = train_summary[0]["name"]
    if "/" in winner:
        winner_selection, selected_candidate = winner.split("/", 1)
    else:
        winner_selection, selected_candidate = selection_modes[0], winner

    def evaluate_selected(seeds: tuple[int, ...]) -> list[dict]:
        runs = _run_split(
            list(seeds),
            sessions=sessions_per_seed,
            rounds_per_session=rounds_per_session,
            risk=risk,
            pick_count=pick_count,
            bankroll=bankroll,
            candidates=(selected_candidate,),
            selection_modes=(winner_selection,),
            pace_seconds=pace_seconds,
            stop_win=stop_win,
            stop_loss=stop_loss,
            max_drawdown=max_drawdown,
        )
        return _aggregate(runs)

    validation_summary = evaluate_selected(validation_seeds)
    test_summary = evaluate_selected(test_seeds)
    test_winner = test_summary[0] if test_summary else {}
    validation_winner = validation_summary[0] if validation_summary else {}
    test_ci_lower = (
        test_winner.get("mean_roi_pct", 0.0) - test_winner.get("mean_roi_ci95_half_pct", 0.0)
    )
    stable_split = (
        bool(validation_winner)
        and bool(test_winner)
        and abs(validation_winner["mean_roi_pct"] - test_winner["mean_roi_pct"]) <= 1.0
    )
    admission_checks = {
        "test_roi_positive": bool(test_winner and test_winner["mean_roi_pct"] > 0),
        "test_ci_lower_positive": bool(test_winner and test_ci_lower > 0),
        "test_positive_seed_pct_at_least_70": bool(
            test_winner and test_winner.get("positive_seed_pct", 0.0) >= 0.70
        ),
        "test_max_ruin_at_most_5pct": bool(
            test_winner and test_winner.get("max_ruin_pct", 1.0) <= 0.05
        ),
        "validation_test_stable_within_1pct": stable_split,
        "not_concentrated_in_top_1pct_sessions": bool(
            test_winner and test_winner.get("max_top_1pct_profit_share", 1.0) <= 0.50
        ),
    }
    admission_passed = all(admission_checks.values())
    conclusion = (
        "A：样本外存在稳定正收益候选"
        if admission_passed
        else ("B：没有证明正收益，但可比较最低损耗和风险控制" if test_winner else "C：数据不足，需要继续采集和验证")
    )
    report = {
        "mode": "strategy_validation",
        "real_money": False,
        "splits": {
            "train": list(train_seeds),
            "validation": list(validation_seeds),
            "test": list(test_seeds),
        },
        "sessions_per_seed": sessions_per_seed,
        "rounds_per_session": rounds_per_session,
        "risk": risk,
        "pick_count": pick_count,
        "bankroll": bankroll,
        "pace_seconds": pace_seconds,
        "selected_train_winner": winner,
        "train": train_summary,
        "validation": validation_summary,
        "test": test_summary,
        "admission": {
            **admission_checks,
            "passed": admission_passed,
            "test_ci_lower_pct": test_ci_lower,
            "conclusion": conclusion,
            "note": "必须同时满足全部检查，才可进入真实只读影子运行；不满足时只保留纸面研究。",
        },
    }
    out = Path(out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Strategy Validation（Train / Validation / Test）",
        "",
        f"- {len(train_seeds)}/{len(validation_seeds)}/{len(test_seeds)} 个随机种子",
        f"- 每种子 {sessions_per_seed} 会话 × {rounds_per_session} 局",
        f"- Train 选择赢家：`{winner}`",
        "",
        "## Train Top 10",
        "",
        "| 候选 | 平均 ROI | 平均 CI 半宽 | 跨种子正收益率 | 平均绿色率 | 平均爆仓率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in train_summary[:10]:
        lines.append(
            f"| {row['name']} | {row['mean_roi_pct']:.3f}% | "
            f"+/-{row['mean_roi_ci95_half_pct']:.3f}% | {row['positive_seed_pct']:.1%} | "
            f"{row['mean_green_pct']:.1%} | {row['mean_ruin_pct']:.1%} |"
        )
    for label, rows in (("Validation", validation_summary), ("Test", test_summary)):
        lines += ["", f"## {label}", "", "| 候选 | 平均 ROI | 平均 CI 半宽 | 跨种子正收益率 | 平均绿色率 | 平均爆仓率 |", "|---|---:|---:|---:|---:|---:|"]
        for row in rows:
            lines.append(
                f"| {row['name']} | {row['mean_roi_pct']:.3f}% | "
                f"+/-{row['mean_roi_ci95_half_pct']:.3f}% | {row['positive_seed_pct']:.1%} | "
                f"{row['mean_green_pct']:.1%} | {row['mean_ruin_pct']:.1%} |"
            )
    lines += ["", "## 准入结论", "", f"- {conclusion}"]
    for key, value in admission_checks.items():
        lines.append(f"- `{key}`: {'PASS' if value else 'FAIL'}")
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
