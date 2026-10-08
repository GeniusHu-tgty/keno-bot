import json

from keno.reporting.history_export import normalize_record, write_history_exports


def test_normalize_record_matches_screenshot_columns():
    row = normalize_record(
        {
            "round_id": "house:1",
            "numbers": [1, 2, 3, 4],
            "bet": {
                "selected_numbers": [1, 5, 6],
                "bet_amount": 0.1,
                "payout": 0.13,
                "payout_multiplier": 1.3,
            },
        },
        1,
    )
    assert row["id"] == "1"
    assert row["hits"] == 1
    assert row["multiplier"] == "1.30"
    assert row["return"] == "0.03000000"


def test_write_history_exports(tmp_path):
    source = tmp_path / "rounds.jsonl"
    source.write_text(
        json.dumps(
            {
                "type": "round",
                "round_id": "1",
                "numbers": [1],
                "bet": {
                    "selected_numbers": [1],
                    "bet_amount": 0.0001,
                    "payout": 0.00012,
                    "payout_multiplier": 1.2,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = write_history_exports(source)
    assert result["rows"] == 1
    assert "编号,投入金额,选择的数字,实际的数字,命中数,倍率,回报" in (
        tmp_path / "rounds_formatted.csv"
    ).read_text(encoding="utf-8-sig")
    assert "1,0.00010000,[1],[1],1,x1.20,0.00002000" in (
        tmp_path / "rounds_formatted.csv"
    ).read_text(encoding="utf-8-sig")
