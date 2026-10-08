# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from decimal import Decimal

from keno.bot.ledger import pnl_from_records


def test_pnl_from_records_today_week_and_curve():
    rows = [
        {"ts": "2026-08-01 10:00:00", "bet": "1", "payout": "0", "profit": "-1"},
        {"ts": "2026-09-13 12:00:00", "bet": "1", "payout": "1.1", "profit": "0.1"},
        {"ts": "2026-09-14 09:00:00", "bet": "0.001", "payout": "0", "profit": "-0.001"},
        {"ts": "2026-09-14 09:01:00", "bet": "0.011", "payout": "0.0121", "profit": "0.0011"},
    ]
    board = pnl_from_records(rows, today="2026-09-14")
    assert board["today"] == "2026-09-14"
    assert board["buckets"]["today"]["rounds"] == 2
    assert Decimal(board["buckets"]["today"]["profit"]) == Decimal("0.0001")
    assert board["buckets"]["d7"]["rounds"] == 3
    assert board["buckets"]["d30"]["rounds"] == 3
    assert board["buckets"]["all"]["rounds"] == 4
    assert len(board["today_curve"]) == 2
    assert board["today_curve"][0]["ts"] < board["today_curve"][-1]["ts"]
    assert Decimal(board["today_curve"][-1]["cum"]) == Decimal(board["buckets"]["today"]["profit"])
    assert Decimal(board["d7_curve"][-1]["cum"]) == Decimal(board["buckets"]["d7"]["profit"])
    assert board["days"][-1]["day"] == "2026-09-14"
    assert Decimal(board["days"][-1]["cum"]) == Decimal(board["buckets"]["all"]["profit"])


def test_pnl_today_curve_is_full_day_not_last_window():
    rows = [
        {"ts": f"2026-09-14 01:{i:02d}:00", "bet": "1", "payout": "0", "profit": "-1"}
        for i in range(50)
    ] + [
        {"ts": f"2026-09-14 23:{i:02d}:00", "bet": "1", "payout": "2", "profit": "1"}
        for i in range(10)
    ]
    board = pnl_from_records(rows, today="2026-09-14")
    assert board["buckets"]["today"]["rounds"] == 60
    assert Decimal(board["today_curve"][0]["cum"]) == Decimal("-1")
    assert Decimal(board["today_curve"][-1]["cum"]) == Decimal(board["buckets"]["today"]["profit"])
    assert board["today_curve"][0]["ts"].startswith("2026-09-14 01:")
    assert board["today_curve"][-1]["ts"].startswith("2026-09-14 23:")


def test_pnl_skips_rows_without_day():
    board = pnl_from_records([{"bet": "1", "payout": "0", "profit": "-1"}], today="2026-09-14")
    assert board["buckets"]["all"]["rounds"] == 0
    assert board["days"] == []
