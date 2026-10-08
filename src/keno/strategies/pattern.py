from __future__ import annotations

from random import Random
from typing import Sequence

from .base import Strategy
from ..data.schema import RoundRecord


class PatternStrategy(Strategy):
    """Keep one selection fixed across rounds, re-rolling on a fixed cadence.

    This mirrors the reference bot's visible behaviour of reusing the same 10-number
    pattern across probe and real bets (screenshot 2026-09-11). Because rounds are
    independent, persistence changes nothing statistically; it only reproduces the
    observed betting texture.
    """

    name = "pattern"
    version = "1"

    def __init__(self, board_size: int = 40, reroll_every: int = 3) -> None:
        if reroll_every < 1:
            raise ValueError("reroll_every must be >= 1")
        self.board_size = board_size
        self.reroll_every = reroll_every
        self._calls = 0
        self._current: list[int] | None = None

    def predict(self, history: Sequence[RoundRecord], pick_count: int, rng: Random) -> list[int]:
        if self._current is None or self._calls % self.reroll_every == 0:
            self._current = sorted(rng.sample(range(1, self.board_size + 1), pick_count))
        self._calls += 1
        return list(self._current)
