# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from keno.research.risk_grid import run_risk_grid

for candidate in ("flat-min", "phase"):
    report = run_risk_grid(
        sessions=120,
        risk="low",
        pick_count=10,
        bankroll="10",
        candidate=candidate,
        selection_mode="random",
        seed=f"live-opt-20260912-{candidate}",
        selection_seed=20260912,
        stop_wins=(None, "0.05"),
        stop_losses=("0.05", "0.2"),
        session_minutes=(10,),
        out_prefix=f"reports/live_opt_{candidate}",
    )
    print(candidate, "cells", len(report.get("rows") or report.get("cells") or []))
    rows = report.get("rows") or report.get("cells") or []
    for row in rows[:12]:
        print(
            " ",
            row.get("name"),
            "green",
            row.get("green_pct"),
            "ruin",
            row.get("ruin_pct"),
            "profit",
            row.get("mean_profit"),
            "dd",
            row.get("mean_max_drawdown"),
            "stop",
            row.get("stop_win"),
            row.get("stop_loss"),
        )
