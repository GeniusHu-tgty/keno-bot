from keno.research.strategy_validation import run_strategy_validation


def test_strategy_validation_freezes_train_winner_and_emits_report(tmp_path):
    report = run_strategy_validation(
        train_seeds=(1,),
        validation_seeds=(2,),
        test_seeds=(3,),
        sessions_per_seed=10,
        rounds_per_session=20,
        candidates=("flat-min", "probe-window"),
        selection_modes=("random", "block-random"),
        out_prefix=str(tmp_path / "validation"),
    )
    assert report["selected_train_winner"]
    assert len(report["validation"]) == 1
    assert len(report["test"]) == 1
    assert (tmp_path / "validation.json").exists()
    assert (tmp_path / "validation.md").exists()
