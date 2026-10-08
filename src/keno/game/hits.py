# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
def count_hits(selected: list[int], drawn: list[int]) -> int:
    return len(set(selected).intersection(drawn))
