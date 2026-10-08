# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
"""Generate the provably-fair sample that ships with Keno BOT.

Every row is produced by this repo from seeds that exist nowhere else, so the
shipped sample contains no third-party account data.  The web workbench uses it
for its randomness self-test, and the CLI can verify it end to end:

    python -m keno.cli verify-rounds --replay-file data/samples/rounds_sample.jsonl \
        --seeds-file data/samples/seeds_sample.json

Run:  python tools/make_sample.py  [rounds]
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from keno.game.keno_draw import draw_keno
from keno.provably_fair.float_generator import FloatGenerator
from keno.provably_fair.hmac_rng import HmacSha256Rng

ROUNDS = 240
CLIENT_SEED = "keno-bot-sample-client"
SEED_NAMESPACE = "keno-bot/sample/server"
RISK = "low"
PICK_COUNT = 10
BET = Decimal("0.00010000")
PICKS = [1, 2, 7, 11, 18, 19, 24, 31, 36, 40]
QUANT = Decimal("0.00000001")


def server_seed(index: int) -> str:
    return hashlib.sha256(f"{SEED_NAMESPACE}/{index}".encode()).hexdigest()


def main() -> None:
    rounds = ROUNDS if len(sys.argv) < 2 else int(sys.argv[1])
    out_dir = ROOT / "data" / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)

    official = json.loads(
        (ROOT / "data" / "reference" / "stake_keno_payouts_official.json").read_text(
            encoding="utf-8"
        )
    )
    table = {int(hits): Decimal(str(m)) for hits, m in enumerate(official["risks"][RISK]["10"])}

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    replay_lines: list[str] = []
    seed_rows: list[dict] = []
    for index in range(rounds):
        seed = server_seed(index)
        numbers = draw_keno(FloatGenerator(HmacSha256Rng(seed, CLIENT_SEED, index, 0)))
        hits = len(set(numbers) & set(PICKS))
        payout = (BET * table[hits]).quantize(QUANT)
        replay_lines.append(
            json.dumps(
                {
                    "type": "round",
                    "round_id": f"sample-{index:04d}",
                    "timestamp": (start + timedelta(seconds=3 * index)).isoformat(),
                    "numbers": numbers,
                    "server_seed": seed,
                    "server_seed_hash": hashlib.sha256(seed.encode()).hexdigest(),
                    "client_seed": CLIENT_SEED,
                    "nonce": index,
                    "cursor": 0,
                    "source": "sample",
                    "risk": RISK,
                    "pick_count": PICK_COUNT,
                    "selected_numbers": PICKS,
                    "hits": hits,
                    "bet_amount": str(BET),
                    "payout": str(payout),
                },
                ensure_ascii=False,
            )
        )
        seed_rows.append(
            {
                "round_id": f"sample-{index:04d}",
                "server_seed": seed,
                "server_seed_hash": hashlib.sha256(seed.encode()).hexdigest(),
                "client_seed": CLIENT_SEED,
                "nonce": index,
            }
        )

    replay_path = out_dir / "rounds_sample.jsonl"
    seeds_path = out_dir / "seeds_sample.json"
    replay_path.write_text("\n".join(replay_lines) + "\n", encoding="utf-8")
    seeds_path.write_text(
        json.dumps(
            {
                "note": "self-generated sample: seeds here exist only in this repo",
                "client_seed": CLIENT_SEED,
                "rounds": seed_rows,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"wrote {replay_path.relative_to(ROOT)} ({len(replay_lines)} rounds)")
    print(f"wrote {seeds_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
