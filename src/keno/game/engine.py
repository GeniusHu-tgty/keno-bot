from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from .hits import count_hits
from .paytable import Paytable

@dataclass(frozen=True)
class Settlement:
    hits: int
    multiplier: Decimal
    payout: Decimal
    profit: Decimal

def settle(selected: list[int], drawn: list[int], bet_amount: Decimal, paytable: Paytable) -> Settlement:
    if bet_amount < 0:
        raise ValueError("bet_amount must be non-negative")
    hits = count_hits(selected, drawn)
    multiplier = paytable.multiplier(len(selected), hits)
    payout = bet_amount * multiplier
    return Settlement(hits, multiplier, payout, payout - bet_amount)
