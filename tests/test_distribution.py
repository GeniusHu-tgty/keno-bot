# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from keno.reporting.metrics import hypergeom_pmf
from keno.synthetic import generate_rounds

def test_five_pick_distribution_is_close_for_20000_rounds():
    rounds = generate_rounds(20_000)
    selected = set(range(1, 6))
    counts = [len(set(r.numbers).intersection(selected)) for r in rounds]
    for k in range(6):
        observed = counts.count(k) / len(counts)
        assert abs(observed - hypergeom_pmf(40, 10, 5, k)) < 0.02
