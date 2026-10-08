# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from keno.provably_fair.hmac_rng import HmacSha256Rng
from keno.provably_fair.float_generator import FloatGenerator, bytes_to_float

def test_bytes_to_float_range_and_known_value():
    assert bytes_to_float(bytes([0, 0, 0, 0])) == 0.0
    assert bytes_to_float(bytes([255, 255, 255, 255])) < 1.0

def test_rng_is_deterministic():
    a = HmacSha256Rng("server", "client", 1).bytes(80)
    b = HmacSha256Rng("server", "client", 1).bytes(80)
    assert a == b
    assert a != HmacSha256Rng("server2", "client", 1).bytes(80)

def test_float_generator_consumes_four_bytes():
    rng = HmacSha256Rng("server", "client", 1)
    values = FloatGenerator(rng).take(20)
    assert len(values) == 20
    assert all(0 <= x < 1 for x in values)


def test_bytes_calls_share_one_continuous_stream():
    # Regression: each digest yields 32 bytes; sequential bytes() calls must
    # continue the same stream instead of restarting a fresh digest per call.
    split = HmacSha256Rng("server", "client", 1)
    whole = HmacSha256Rng("server", "client", 1)
    assert split.bytes(4) + split.bytes(4) + split.bytes(8) == whole.bytes(16)
