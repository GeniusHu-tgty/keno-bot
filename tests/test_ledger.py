from keno.bot.ledger import append_record, loss_p_pick10, scoped_records, summarize, viability


def test_paper_and_live_are_separate_books(tmp_path, monkeypatch):
    import keno.bot.ledger as ledger

    monkeypatch.setattr(ledger, "PAPER_PATH", tmp_path / "paper.jsonl")
    monkeypatch.setattr(ledger, "LIVE_PATH", tmp_path / "live.jsonl")
    monkeypatch.setattr(ledger, "LIVE_STATE_PATH", tmp_path / "live_state.json")
    monkeypatch.setattr(ledger, "DATA_DIR", tmp_path)
    append_record("paper", {"id": 1, "bet": "0.01", "payout": "0", "ts": "2026-01-01 00:00:00"})
    append_record("live", {"id": "iid-1", "bet": "0.0001", "payout": "0.00011", "ts": "2026-01-01 00:00:01"})
    paper = scoped_records("paper", "lifetime")
    live = scoped_records("live", "lifetime")
    both = scoped_records("all", "lifetime")
    assert len(paper) == 1 and paper[0]["book"] == "paper"
    assert len(live) == 1 and live[0]["book"] == "live"
    assert len(both) == 2


def test_loss_streak_and_viability_reject_positive_ev():
    losses = [{"bet": "0.01", "payout": "0"} for _ in range(3)]
    summary = summarize(losses)
    assert summary["current_loss_streak"] == 3
    assert summary["wins"] == 0
    verdict = viability(losses, [])
    assert verdict["live_ev_positive"] is False
    assert verdict["recommendation"] in {"probe-only", "pause"}
    assert 0.18 < loss_p_pick10() < 0.23


def test_eight_losses_recommend_pause():
    losses = [{"bet": "0.0001", "payout": "0"} for _ in range(8)]
    verdict = viability(losses)
    assert verdict["recommendation"] == "pause"
    assert verdict["streak_unusual"] is True
