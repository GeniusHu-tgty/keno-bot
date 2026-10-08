import json

from keno.research.strategy_grid import run_strategy_grid


def test_strategy_grid_is_reproducible_and_writes_reports(tmp_path):
    out = tmp_path / "grid"
    first = run_strategy_grid(
        sessions=12,
        rounds_per_session=20,
        risk="medium",
        pick_count=10,
        bankroll="10",
        candidates=("flat-min", "fractional", "probe-window"),
        out_prefix=str(out),
    )
    second = run_strategy_grid(
        sessions=12,
        rounds_per_session=20,
        risk="medium",
        pick_count=10,
        bankroll="10",
        candidates=("flat-min", "fractional", "probe-window"),
        out_prefix=str(tmp_path / "grid2"),
    )
    assert first["common_random_numbers"] is True
    assert [r["name"] for r in first["rows"]] == [r["name"] for r in second["rows"]]
    assert first["rows"] == second["rows"]
    assert (tmp_path / "grid.json").exists()
    assert (tmp_path / "grid.md").exists()
    assert json.loads((tmp_path / "grid.json").read_text(encoding="utf-8"))["risk"] == "medium"
