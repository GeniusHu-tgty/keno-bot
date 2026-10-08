# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

from abc import ABC, abstractmethod
from random import Random
from typing import Sequence
from ..data.schema import RoundRecord

class Strategy(ABC):
    name = "base"
    version = "1"

    @abstractmethod
    def predict(self, history: Sequence[RoundRecord], pick_count: int, rng: Random) -> list[int]:
        """Return a selection using history only; current/future round is unavailable."""
        raise NotImplementedError

    def observe(self, record: RoundRecord) -> None:
        """Optional post-round hook. The default strategy is stateless."""
