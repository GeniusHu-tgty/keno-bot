from collections import Counter
from random import Random
from typing import Sequence
from .base import Strategy
from ..data.schema import RoundRecord

class ColdStrategy(Strategy):
    name = "cold"
    version = "1"

    def __init__(self, window: int = 1000) -> None:
        self.window = window
        self._recent: list[RoundRecord] = []
        self._counts = Counter()

    def predict(self, history: Sequence[RoundRecord], pick_count: int, rng: Random) -> list[int]:
        if not self._recent and history:
            self._recent = list(history[-self.window:])
            self._counts = Counter(number for record in self._recent for number in record.numbers)
        ranked = sorted(range(1, 41), key=lambda number: (self._counts[number], number))
        return sorted(ranked[:pick_count])

    def observe(self, record: RoundRecord) -> None:
        self._recent.append(record)
        self._counts.update(record.numbers)
        if len(self._recent) > self.window:
            expired = self._recent.pop(0)
            self._counts.subtract(expired.numbers)
