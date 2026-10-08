# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from decimal import Decimal
from keno.game.paytable import Paytable

def test_configured_paytable_and_settlement():
    table = Paytable.from_yaml("configs/payout.yaml")
    assert table.multiplier(1, 0) == Decimal("0.70")
    assert table.multiplier(1, 1) == Decimal("1.85")
