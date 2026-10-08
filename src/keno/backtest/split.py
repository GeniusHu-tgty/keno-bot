# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, TypeVar

T = TypeVar("T")

@dataclass(frozen=True)
class ChronologicalSplit:
    train: list[T]
    validation: list[T]
    test: list[T]

def chronological_split(records: Sequence[T], train_ratio: float = 0.5, validation_ratio: float = 0.25) -> ChronologicalSplit[T]:
    if not 0 < train_ratio < 1 or not 0 < validation_ratio < 1 or train_ratio + validation_ratio >= 1:
        raise ValueError("train_ratio + validation_ratio must be less than 1")
    n = len(records)
    train_end = int(n * train_ratio)
    validation_end = train_end + int(n * validation_ratio)
    return ChronologicalSplit(list(records[:train_end]), list(records[train_end:validation_end]), list(records[validation_end:]))
