from __future__ import annotations

from collections import deque
from enum import Enum
from statistics import pstdev
from decimal import Decimal


class Regime(str, Enum):
    NORMAL = "NORMAL"
    HIGH_VARIANCE = "HIGH_VARIANCE"
    LOW_VARIANCE = "LOW_VARIANCE"
    LOSS_CLUSTER = "LOSS_CLUSTER"
    WIN_CLUSTER = "WIN_CLUSTER"


class RegimeDetector:
    """Descriptive, causal regime detector for risk control.

    It never predicts the next draw.  It only classifies the already observed
    profit stream so a caller can pause or reduce exposure.
    """

    def __init__(
        self,
        window: int = 30,
        loss_cluster: int = 5,
        win_cluster: int = 5,
        high_variance_factor: float = 2.0,
        low_variance_factor: float = 0.35,
    ) -> None:
        if window < 2:
            raise ValueError("window must be >= 2")
        if min(loss_cluster, win_cluster) < 2:
            raise ValueError("cluster lengths must be >= 2")
        self.window = window
        self.loss_cluster = loss_cluster
        self.win_cluster = win_cluster
        self.high_variance_factor = high_variance_factor
        self.low_variance_factor = low_variance_factor
        self._profits: deque[Decimal] = deque(maxlen=window)
        self._state = Regime.NORMAL

    @property
    def state(self) -> Regime:
        return self._state

    @property
    def profits(self) -> tuple[Decimal, ...]:
        return tuple(self._profits)

    def observe(self, profit: Decimal) -> Regime:
        self._profits.append(Decimal(profit))
        self._state = self._classify()
        return self._state

    @property
    def recommended_action(self) -> str:
        """Map an observed state to a non-predictive risk-control action."""
        if self._state == Regime.LOSS_CLUSTER:
            return "pause"
        if self._state == Regime.HIGH_VARIANCE:
            return "reduce"
        return "continue"

    @property
    def should_pause(self) -> bool:
        return self.recommended_action == "pause"

    def _classify(self) -> Regime:
        values = list(self._profits)
        if len(values) < 2:
            return Regime.NORMAL
        tail = values[-max(self.loss_cluster, self.win_cluster):]
        if len(tail) >= self.loss_cluster and all(value < 0 for value in tail[-self.loss_cluster:]):
            return Regime.LOSS_CLUSTER
        if len(tail) >= self.win_cluster and all(value > 0 for value in tail[-self.win_cluster:]):
            return Regime.WIN_CLUSTER
        split = len(values) // 2
        baseline_sd = pstdev(float(value) for value in values[:split])
        current_sd = pstdev(float(value) for value in values[split:])
        if baseline_sd <= 1e-12:
            return Regime.NORMAL
        if current_sd > baseline_sd * self.high_variance_factor:
            return Regime.HIGH_VARIANCE
        if current_sd < baseline_sd * self.low_variance_factor:
            return Regime.LOW_VARIANCE
        return Regime.NORMAL
