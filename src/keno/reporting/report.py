# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

import csv
import json
from pathlib import Path
from .metrics import chi_square, hits_distribution, hypergeom_pmf

def write_simulation_report(out_dir: str | Path, hits: list[int], pick_count: int, board_size: int = 40, draw_count: int = 10, seed: str = "") -> dict:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    observed = hits_distribution(hits)
    probabilities = {k: hypergeom_pmf(board_size, draw_count, pick_count, k) for k in range(pick_count + 1)}
    total = len(hits)
    rows = []
    for k in range(pick_count + 1):
        rows.append({"hits": k, "observed": observed.get(k, 0), "expected_probability": probabilities[k], "expected_count": total * probabilities[k], "difference": observed.get(k, 0) - total * probabilities[k]})
    with (out / "hits_distribution.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    summary = {"rounds": total, "pick_count": pick_count, "board_size": board_size, "draw_count": draw_count, "seed": seed, "observed": observed, "chi_square": chi_square(observed, probabilities, total), "rows": rows}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# Keno Synthetic Simulation Report", "", f"- rounds: {total}", f"- pick_count: {pick_count}", f"- seed: `{seed}`", f"- chi-square: {summary['chi_square']:.4f}", "", "| Hits | Observed | Expected | Probability |", "|---:|---:|---:|---:|"]
    lines += [f"| {r['hits']} | {r['observed']} | {r['expected_count']:.2f} | {r['expected_probability']:.6%} |" for r in rows]
    (out / "simulation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
