# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from keno.research.risk_grid import run_risk_grid


def test_risk_grid_runs_small_reproducible_matrix(tmp_path):
    kwargs = dict(
        sessions=3,
        risk="medium",
        pick_count=10,
        pace_seconds=3.5,
        candidate="flat-min",
        selection_mode="random",
        stop_wins=(None, "0.001"),
        stop_losses=(None,),
        session_minutes=(1,),
        out_prefix=str(tmp_path / "risk"),
    )
    first = run_risk_grid(**kwargs)
    second = run_risk_grid(**{**kwargs, "out_prefix": str(tmp_path / "risk2")})
    assert first["completed_cells"] == 2
    assert first["rows"] == second["rows"]
    assert (tmp_path / "risk.json").exists()
    assert (tmp_path / "risk.md").exists()
