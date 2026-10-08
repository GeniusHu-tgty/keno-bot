from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from .regime import Regime, RegimeDetector


class MoneyManager(ABC):
    """Staking logic. Selects numbers and timing live in strategies; money lives here."""

    name = "base"

    @abstractmethod
    def next_bet(self, bankroll: Decimal) -> Decimal:
        """Return the intended stake for the next round.

        Do not cap by bankroll here: the bot stops when the bankroll cannot
        cover the intended stake, instead of silently shrinking it.
        """
        raise NotImplementedError

    @abstractmethod
    def observe(self, profit: Decimal) -> None:
        """Feed the settled profit of the last round back into the staking state."""
        raise NotImplementedError

    def should_pause(self) -> bool:
        """Return whether risk control wants the caller to pause before betting.

        The default is deliberately conservative: existing managers preserve
        their historical behavior unless they explicitly opt into a pause
        policy.
        """
        return False

    @property
    def risk_action(self) -> str:
        """Human-readable risk-control action for dashboards and reports."""
        return "continue"

    @property
    @abstractmethod
    def phase(self) -> str:
        raise NotImplementedError


class FlatMoneyManager(MoneyManager):
    name = "flat"

    def __init__(self, base_bet: Decimal) -> None:
        self.base_bet = base_bet

    def next_bet(self, bankroll: Decimal) -> Decimal:
        return self.base_bet

    def observe(self, profit: Decimal) -> None:
        return None

    @property
    def phase(self) -> str:
        return "flat"


class FractionalMoneyManager(MoneyManager):
    """Stake a bounded fraction of the current bankroll.

    This is a risk-control policy, not a predictive strategy.  The floor keeps
    the paper bot compatible with the platform minimum while the cap prevents a
    large balance or a short winning streak from silently creating oversized
    exposure.
    """

    name = "fractional"

    def __init__(
        self,
        fraction: Decimal = Decimal("0.0005"),
        min_bet: Decimal = Decimal("0.0001"),
        max_fraction: Decimal = Decimal("0.002"),
    ) -> None:
        if fraction <= 0:
            raise ValueError("fraction must be positive")
        if min_bet <= 0:
            raise ValueError("min_bet must be positive")
        if max_fraction < fraction:
            raise ValueError("max_fraction must be >= fraction")
        self.fraction = fraction
        self.min_bet = min_bet
        self.max_fraction = max_fraction

    def next_bet(self, bankroll: Decimal) -> Decimal:
        if bankroll <= 0:
            return self.min_bet
        amount = bankroll * min(self.fraction, self.max_fraction)
        return max(self.min_bet, amount)

    def observe(self, profit: Decimal) -> None:
        return None

    @property
    def phase(self) -> str:
        return f"fractional({self.fraction})"


class ProbeWindowManager(MoneyManager):
    """Experimental probe -> exposure -> cooldown schedule.

    The probe result is deliberately *not* treated as evidence that the next
    draw is predictable.  This manager exists to reproduce and measure the
    phase-like operating texture while keeping exposure bounded.
    """

    name = "probe-window"

    def __init__(
        self,
        probe_bet: Decimal = Decimal("0.0001"),
        active_bet: Decimal = Decimal("0.001"),
        probe_rounds: int = 30,
        active_rounds: int = 60,
        cooldown_rounds: int = 30,
    ) -> None:
        if min(probe_bet, active_bet) <= 0:
            raise ValueError("bet amounts must be positive")
        if min(probe_rounds, active_rounds, cooldown_rounds) < 1:
            raise ValueError("round counts must be positive")
        self.probe_bet = probe_bet
        self.active_bet = active_bet
        self.probe_rounds = probe_rounds
        self.active_rounds = active_rounds
        self.cooldown_rounds = cooldown_rounds
        self._round = 0

    def next_bet(self, bankroll: Decimal) -> Decimal:
        cycle = self.probe_rounds + self.active_rounds + self.cooldown_rounds
        position = self._round % cycle
        if position < self.probe_rounds:
            return self.probe_bet
        if position < self.probe_rounds + self.active_rounds:
            return self.active_bet
        return self.probe_bet

    def observe(self, profit: Decimal) -> None:
        self._round += 1

    @property
    def phase(self) -> str:
        cycle = self.probe_rounds + self.active_rounds + self.cooldown_rounds
        position = self._round % cycle
        if position < self.probe_rounds:
            return "probe"
        if position < self.probe_rounds + self.active_rounds:
            return "active-window"
        return "cooldown"


class CappedRecoveryManager(MoneyManager):
    """Small, capped recovery step for comparison against full Martingale."""

    name = "capped-recovery"

    def __init__(
        self,
        base_bet: Decimal = Decimal("0.0001"),
        multiplier: Decimal = Decimal("1.25"),
        max_steps: int = 4,
    ) -> None:
        if base_bet <= 0:
            raise ValueError("base_bet must be positive")
        if multiplier < 1:
            raise ValueError("multiplier must be >= 1")
        if max_steps < 0:
            raise ValueError("max_steps must be non-negative")
        self.base_bet = base_bet
        self.multiplier = multiplier
        self.max_steps = max_steps
        self.step = 0

    def next_bet(self, bankroll: Decimal) -> Decimal:
        return self.base_bet * (self.multiplier ** min(self.step, self.max_steps))

    def observe(self, profit: Decimal) -> None:
        if profit > 0:
            self.step = 0
        elif profit < 0:
            self.step += 1

    @property
    def phase(self) -> str:
        return f"capped({self.step})"


class AdaptiveFractionalManager(MoneyManager):
    """Bounded fractional staking with regime-based risk reduction.

    Regime labels are descriptive only.  A loss/high-variance regime reduces
    exposure; it never increases the stake or claims to predict the next draw.
    """

    name = "adaptive-fractional"

    def __init__(
        self,
        fraction: Decimal = Decimal("0.0005"),
        cautious_fraction: Decimal = Decimal("0.0001"),
        min_bet: Decimal = Decimal("0.0001"),
        max_fraction: Decimal = Decimal("0.002"),
        detector: RegimeDetector | None = None,
        pause_on_loss_cluster: bool = True,
    ) -> None:
        if min(fraction, cautious_fraction, min_bet) <= 0:
            raise ValueError("fractions and min_bet must be positive")
        if cautious_fraction > fraction:
            raise ValueError("cautious_fraction must be <= fraction")
        if max_fraction < fraction:
            raise ValueError("max_fraction must be >= fraction")
        self.fraction = fraction
        self.cautious_fraction = cautious_fraction
        self.min_bet = min_bet
        self.max_fraction = max_fraction
        self.detector = detector or RegimeDetector()
        self.pause_on_loss_cluster = pause_on_loss_cluster

    def next_bet(self, bankroll: Decimal) -> Decimal:
        if bankroll <= 0:
            return self.min_bet
        cautious = self.detector.state in {
            Regime.LOSS_CLUSTER,
            Regime.HIGH_VARIANCE,
        }
        fraction = self.cautious_fraction if cautious else min(self.fraction, self.max_fraction)
        return max(self.min_bet, bankroll * fraction)

    def observe(self, profit: Decimal) -> None:
        self.detector.observe(profit)

    def should_pause(self) -> bool:
        return self.pause_on_loss_cluster and self.detector.should_pause

    @property
    def risk_action(self) -> str:
        return self.detector.recommended_action

    @property
    def phase(self) -> str:
        return f"adaptive-{self.detector.state.value.lower()}"


class PhaseRecoveryManager(MoneyManager):
    """Experimental loss-recovery staking: raise after losses, reset after any win.

    This mirrors the phase-recovery idea visible in the external bot's UI. It is
    NOT a reconstruction of that bot's unknown algorithm and does not change EV;
    it only reshapes variance and drawdown.
    """

    name = "recovery"

    def __init__(
        self,
        base_bet: Decimal,
        recovery_multiplier: Decimal = Decimal("2"),
        max_recovery_steps: int = 8,
    ) -> None:
        if recovery_multiplier < 1:
            raise ValueError("recovery_multiplier must be >= 1")
        if max_recovery_steps < 0:
            raise ValueError("max_recovery_steps must be non-negative")
        self.base_bet = base_bet
        self.recovery_multiplier = recovery_multiplier
        self.max_recovery_steps = max_recovery_steps
        self.recovery_step = 0

    def next_bet(self, bankroll: Decimal) -> Decimal:
        step = min(self.recovery_step, self.max_recovery_steps)
        return self.base_bet * (self.recovery_multiplier**step)

    def observe(self, profit: Decimal) -> None:
        if profit > 0:
            self.recovery_step = 0
        elif profit < 0:
            self.recovery_step += 1

    @property
    def phase(self) -> str:
        return "base" if self.recovery_step == 0 else f"recovery({self.recovery_step})"
