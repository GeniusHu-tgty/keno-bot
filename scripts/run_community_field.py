"""Compare public Keno configs on the official paytable. Paper only."""

from keno.research.strategy_grid import run_strategy_grid

CELLS = (
    ("low", 10, "low10"),
    ("classic", 10, "classic10"),
    ("low", 9, "low9"),
    ("classic", 5, "classic5"),
    ("classic", 4, "classic4"),
    ("medium", 10, "medium10"),
    ("low", 5, "low5"),
    ("classic", 8, "classic8"),
)

print("tag\trisk\tpicks\tROI%\tgreen\tdd\tprofit")
for risk, picks, tag in CELLS:
    report = run_strategy_grid(
        sessions=200,
        rounds_per_session=100,
        risk=risk,
        pick_count=picks,
        bankroll="10",
        candidates=("flat-min",),
        selection_modes=("random",),
        seed=f"community-20260912-{tag}",
        selection_seed=120912,
        out_prefix=f"reports/community_{tag}",
    )
    row = report["rows"][0]
    print(
        f"{tag}\t{risk}\t{picks}\t{row['mean_roi_pct']:.3f}\t"
        f"{row['green_pct']:.1%}\t{row['mean_max_drawdown']}\t{row['mean_profit']}"
    )
