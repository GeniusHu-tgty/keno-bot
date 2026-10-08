# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from random import Random

from keno.data.schema import RoundRecord
from keno.strategies.selection import SELECTION_MODES, SelectionStrategy, select_numbers


def test_all_selection_modes_return_valid_unique_numbers():
    history = [
        RoundRecord(
            round_id=str(i),
            timestamp=None,
            numbers=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            source="test",
        )
        for i in range(20)
    ]
    for mode in SELECTION_MODES:
        picked = select_numbers(mode, history, 10, Random(1))
        assert len(picked) == 10
        assert len(set(picked)) == 10
        assert all(1 <= number <= 40 for number in picked)


def test_block_selection_reuses_set_until_block_boundary():
    strategy = SelectionStrategy("block-random", block_rounds=3)
    rng = Random(7)
    first = strategy.predict([], 10, rng)
    assert strategy.predict([], 10, rng) == first
    assert strategy.predict([], 10, rng) == first
    assert strategy.predict([], 10, rng) != first
