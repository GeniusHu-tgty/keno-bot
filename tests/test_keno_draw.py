# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from keno.game.keno_draw import draw_keno

class ZeroSource:
    def next_float(self): return 0.0

class OneSource:
    def next_float(self): return 0.999999999999

def test_draw_has_ten_unique_numbers_in_range():
    result = draw_keno(ZeroSource())
    assert len(result) == 10
    assert len(set(result)) == 10
    assert all(1 <= x <= 40 for x in result)
    assert result == list(range(1, 11))

def test_high_float_picks_last_remaining():
    result = draw_keno(OneSource(), board_size=5, draw_count=5)
    assert sorted(result) == [1, 2, 3, 4, 5]
