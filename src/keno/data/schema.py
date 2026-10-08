from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

@dataclass(frozen=True)
class RoundRecord:
    round_id: str
    timestamp: datetime
    numbers: list[int]
    server_seed_hash: str | None = None
    server_seed: str | None = None
    client_seed: str | None = None
    nonce: int | None = None
    cursor: int | None = None
    source: str = "synthetic"

@dataclass(frozen=True)
class BetRecord:
    round_id: str
    selected_numbers: list[int]
    pick_count: int
    difficulty: str
    bet_amount: Decimal
    hits: int
    multiplier: Decimal
    payout: Decimal
    profit: Decimal
    strategy_name: str
    strategy_version: str
    decision_reason: str | None = None

def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {k: jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value
