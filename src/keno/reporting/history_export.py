from __future__ import annotations

"""Normalize collected Keno history into the seven-column reference format."""

import csv
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


def _decimal(value: object, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, "") else Decimal(default)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _money(value: Decimal) -> str:
    return f"{value:.8f}"


def normalize_record(record: dict, index: int) -> dict:
    bet = record.get("bet") or {}
    selected = [
        int(x)
        for x in (bet.get("selected_numbers") or record.get("selected_numbers") or [])
    ]
    drawn = [int(x) for x in (record.get("numbers") or record.get("drawn_numbers") or [])]
    amount = _decimal(bet.get("bet_amount", record.get("bet_amount", "0")))
    multiplier = _decimal(
        bet.get("payout_multiplier", record.get("payout_multiplier", "0"))
    )
    gross_payout = _decimal(bet.get("payout", record.get("payout", "0")))
    hits = len(set(selected) & set(drawn))

    # Stake's history row uses net result in the final column: a losing round
    # is -stake, while a winning round is gross payout minus stake.
    if gross_payout > 0:
        profit = gross_payout - amount
    else:
        profit = -amount

    raw_id = record.get("id") or record.get("round_id") or index
    # Keep the human-facing first column numeric when the platform identifier
    # is formatted as ``house:<numeric-id>``; retain the full value in JSON.
    display_id = str(raw_id).split(":")[-1]
    return {
        "id": display_id,
        "bet_amount": _money(amount),
        "selected_numbers": selected,
        "drawn_numbers": drawn,
        "hits": hits,
        "multiplier": f"{multiplier:.2f}",
        "return": _money(profit),
        "timestamp": record.get("timestamp"),
        "round_id": record.get("round_id"),
        "risk": bet.get("risk", record.get("risk")),
        "nonce": record.get("nonce"),
        "currency": bet.get("currency", record.get("currency")),
    }


def read_jsonl(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type", "round") == "round":
            rows.append(record)
    return rows


def normalize_history(records: Iterable[dict]) -> list[dict]:
    return [normalize_record(record, index + 1) for index, record in enumerate(records)]


def write_history_exports(
    input_path: str | Path,
    *,
    out_prefix: str | Path | None = None,
    newest_first: bool = True,
) -> dict:
    source = Path(input_path)
    prefix = Path(out_prefix) if out_prefix else source.with_name(source.stem + "_formatted")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    rows = normalize_history(read_jsonl(source))
    if newest_first:
        rows.reverse()

    csv_path = prefix.with_suffix(".csv")
    jsonl_path = prefix.with_suffix(".jsonl")
    csv_fields = (
        "id",
        "bet_amount",
        "selected_numbers",
        "drawn_numbers",
        "hits",
        "multiplier",
        "return",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(("编号", "投入金额", "选择的数字", "实际的数字", "命中数", "倍率", "回报"))
        for row in rows:
            writer.writerow(
                [
                    row["id"],
                    row["bet_amount"],
                    "[" + ",".join(map(str, row["selected_numbers"])) + "]",
                    "[" + ",".join(map(str, row["drawn_numbers"])) + "]",
                    row["hits"],
                    "x" + row["multiplier"],
                    row["return"],
                ]
            )

    jsonl_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return {
        "source": str(source),
        "rows": len(rows),
        "csv": str(csv_path),
        "jsonl": str(jsonl_path),
        "columns": list(csv_fields),
    }
