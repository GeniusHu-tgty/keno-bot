# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

from .hmac_rng import HmacSha256Rng

def bytes_to_float(chunk: bytes) -> float:
    if len(chunk) != 4:
        raise ValueError("exactly 4 bytes are required")
    return sum(byte / (256 ** (i + 1)) for i, byte in enumerate(chunk))

class FloatGenerator:
    def __init__(self, byte_source: HmacSha256Rng) -> None:
        self.byte_source = byte_source

    def next_float(self) -> float:
        return bytes_to_float(self.byte_source.bytes(4))

    def take(self, count: int) -> list[float]:
        return [self.next_float() for _ in range(count)]
