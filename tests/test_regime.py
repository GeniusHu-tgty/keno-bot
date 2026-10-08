# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from decimal import Decimal

from keno.bot.regime import Regime, RegimeDetector


def test_regime_detector_is_causal_and_detects_loss_cluster():
    detector = RegimeDetector(window=10, loss_cluster=3, win_cluster=3)
    for _ in range(7):
        detector.observe(Decimal("0.01"))
    assert detector.observe(Decimal("-0.01")) == Regime.NORMAL
    assert detector.observe(Decimal("-0.01")) == Regime.NORMAL
    assert detector.observe(Decimal("-0.01")) == Regime.LOSS_CLUSTER


def test_regime_detector_does_not_classify_short_history_as_variance():
    detector = RegimeDetector(window=10)
    assert detector.observe(Decimal("1")) == Regime.NORMAL
    assert detector.observe(Decimal("-1")) == Regime.NORMAL
