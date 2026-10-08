# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from keno.provably_fair.verifier import verify_round


def test_verifier_passes_for_matching_observed_result():
    result = verify_round(
        server_seed="server-seed-demo",
        client_seed="player-007",
        nonce=7,
        cursor=0,
        observed=[11, 21, 9, 13, 31, 28, 24, 10, 6, 19],
    )
    assert result.passed
    assert result.status() == "PASS"


def test_verifier_fails_for_modified_observed_result():
    result = verify_round(
        server_seed="server-seed-demo",
        client_seed="player-007",
        nonce=7,
        cursor=0,
        observed=[11, 21, 9, 13, 31, 28, 24, 10, 6, 18],
    )
    assert not result.passed
    assert result.status() == "FAIL"
