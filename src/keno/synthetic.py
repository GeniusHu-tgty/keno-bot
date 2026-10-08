# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from .provably_fair.hmac_rng import HmacSha256Rng
from .provably_fair.float_generator import FloatGenerator
from .game.keno_draw import draw_keno
from .data.schema import RoundRecord

def generate_rounds(count: int, seed: str = "keno-synthetic-v1", client_seed: str = "synthetic-client") -> list[RoundRecord]:
    if count < 0:
        raise ValueError("count must be non-negative")
    rounds = []
    for index in range(count):
        server_seed = hashlib.sha256(f"{seed}:{index}".encode()).hexdigest()
        rng = FloatGenerator(HmacSha256Rng(server_seed, client_seed, nonce=index, cursor=0))
        numbers = draw_keno(rng)
        rounds.append(RoundRecord(round_id=str(index), timestamp=datetime.now(timezone.utc), numbers=numbers, server_seed=server_seed, client_seed=client_seed, nonce=index, cursor=0))
    return rounds
