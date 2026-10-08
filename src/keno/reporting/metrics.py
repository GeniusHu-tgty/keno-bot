from __future__ import annotations

import math
from collections import Counter
from decimal import Decimal

def hypergeom_pmf(board_size: int, draw_count: int, pick_count: int, hits: int) -> float:
    if hits < 0 or hits > pick_count or hits > draw_count or draw_count - hits > board_size - pick_count:
        return 0.0
    return math.comb(pick_count, hits) * math.comb(board_size - pick_count, draw_count - hits) / math.comb(board_size, draw_count)

def hits_distribution(hits: list[int]) -> dict[int, int]:
    return dict(sorted(Counter(hits).items()))

def chi_square(observed: dict[int, int], expected_probs: dict[int, float], total: int) -> float:
    return sum((observed.get(k, 0) - total * p) ** 2 / (total * p) for k, p in expected_probs.items() if p > 0)

def max_drawdown(profits: list[Decimal]) -> Decimal:
    balance = Decimal("0")
    peak = Decimal("0")
    maximum = Decimal("0")
    for profit in profits:
        balance += profit
        peak = max(peak, balance)
        maximum = max(maximum, peak - balance)
    return maximum

def longest_loss_streak(profits: list[Decimal]) -> int:
    current = longest = 0
    for profit in profits:
        if profit < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest
