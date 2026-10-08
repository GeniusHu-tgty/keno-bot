from random import Random
from typing import Sequence
from .base import Strategy
from ..data.schema import RoundRecord

class RandomStrategy(Strategy):
    name = "random"
    version = "1"

    def predict(self, history: Sequence[RoundRecord], pick_count: int, rng: Random) -> list[int]:
        return sorted(rng.sample(range(1, 41), pick_count))
