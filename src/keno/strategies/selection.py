from __future__ import annotations

from collections import Counter
from random import Random
from typing import Sequence

from ..data.schema import RoundRecord
from .base import Strategy

SELECTION_MODES = (
    "random",
    "block-random",
    "fixed-pattern",
    "hot",
    "cold",
    "avoid-cold-zone",
    "balanced-random",
)

FIXED_PATTERN = (3, 6, 14, 16, 22, 25, 29, 36, 37, 38)


def _ranked(history: Sequence[RoundRecord], pick_count: int, reverse: bool, window: int) -> list[int]:
    counts = Counter(number for record in history[-window:] for number in record.numbers)
    numbers = list(range(1, 41))
    numbers.sort(key=lambda number: ((-counts[number] if reverse else counts[number]), number))
    return numbers[:pick_count]


def select_numbers(
    mode: str,
    history: Sequence[RoundRecord],
    pick_count: int,
    rng: Random,
    *,
    block_index: int = 0,
    recent_window: int = 100,
) -> list[int]:
    """Return a causal selection; history never contains the current draw."""
    if mode not in SELECTION_MODES:
        raise ValueError(f"unknown selection mode: {mode}")
    if not 1 <= pick_count <= 10:
        raise ValueError("pick_count must be in 1..10")
    if mode == "fixed-pattern":
        return sorted(FIXED_PATTERN[:pick_count])
    if mode == "block-random":
        return sorted(rng.sample(range(1, 41), pick_count))
    if mode == "random" or not history:
        return sorted(rng.sample(range(1, 41), pick_count))
    if mode == "hot":
        return sorted(_ranked(history, pick_count, True, recent_window))
    if mode == "cold":
        return sorted(_ranked(history, pick_count, False, recent_window))
    if mode == "avoid-cold-zone":
        counts = Counter(number for record in history[-recent_window:] for number in record.numbers)
        ranked = sorted(range(1, 41), key=lambda number: (-counts[number], number))
        eligible = ranked[: max(pick_count, 30)]
        return sorted(rng.sample(eligible, pick_count))
    # Balanced random: one draw from each ten-number band before filling.
    buckets = [list(range(start, start + 10)) for start in range(1, 41, 10)]
    chosen = [rng.choice(bucket) for bucket in buckets[: min(pick_count, len(buckets))]]
    remaining = [n for n in range(1, 41) if n not in chosen]
    if len(chosen) < pick_count:
        chosen.extend(rng.sample(remaining, pick_count - len(chosen)))
    return sorted(chosen)


class SelectionStrategy(Strategy):
    """Adapter exposing all causal selection modes to the paper bot."""

    version = "1"

    def __init__(self, mode: str = "random", block_rounds: int = 257, recent_window: int = 100) -> None:
        if mode not in SELECTION_MODES:
            raise ValueError(f"unknown selection mode: {mode}")
        if block_rounds < 1 or recent_window < 1:
            raise ValueError("block_rounds and recent_window must be positive")
        self.mode = mode
        self.block_rounds = block_rounds
        self.recent_window = recent_window
        self._calls = 0
        self._block_selection: list[int] | None = None
        self.name = mode

    def predict(self, history: Sequence[RoundRecord], pick_count: int, rng: Random) -> list[int]:
        block = self._calls // self.block_rounds
        if self.mode == "block-random":
            if self._block_selection is None or self._calls % self.block_rounds == 0:
                self._block_selection = select_numbers(
                    self.mode,
                    history,
                    pick_count,
                    rng,
                    block_index=block,
                    recent_window=self.recent_window,
                )
            selected = list(self._block_selection)
        else:
            selected = select_numbers(
                self.mode,
                history,
                pick_count,
                rng,
                block_index=block,
                recent_window=self.recent_window,
            )
        self._calls += 1
        return selected
