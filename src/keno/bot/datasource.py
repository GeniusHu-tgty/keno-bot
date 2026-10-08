from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ..data.schema import RoundRecord

# Streaming twin of synthetic.generate_rounds: the bot can run 100k+ rounds
# without materialising every record up front.


def iter_synthetic_rounds(count: int, seed: str = "keno-synthetic-v1", client_seed: str = "synthetic-client") -> Iterator[RoundRecord]:
    from ..provably_fair.hmac_rng import HmacSha256Rng
    from ..provably_fair.float_generator import FloatGenerator
    from ..game.keno_draw import draw_keno

    for index in range(count):
        server_seed = hashlib.sha256(f"{seed}:{index}".encode()).hexdigest()
        rng = FloatGenerator(HmacSha256Rng(server_seed, client_seed, nonce=index, cursor=0))
        yield RoundRecord(
            round_id=str(index),
            timestamp=datetime.now(timezone.utc),
            numbers=draw_keno(rng),
            server_seed=server_seed,
            client_seed=client_seed,
            nonce=index,
            cursor=0,
            source="synthetic",
        )


def iter_replay_rounds(path: str | Path, limit: int | None = None) -> Iterator[RoundRecord]:
    """Read a rounds JSONL file written by write_rounds_jsonl (or hand-collected logs)."""
    yielded = 0
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            if event.get("type", "round") == "round":
                yield RoundRecord(
                    round_id=str(event["round_id"]),
                    timestamp=datetime.fromisoformat(event["timestamp"]),
                    numbers=[int(n) for n in event["numbers"]],
                    server_seed=event.get("server_seed"),
                    server_seed_hash=event.get("server_seed_hash"),
                    client_seed=event.get("client_seed"),
                    nonce=event.get("nonce"),
                    cursor=event.get("cursor"),
                    source=event.get("source", "replay"),
                )
                yielded += 1
                if limit is not None and yielded >= limit:
                    return


def write_rounds_jsonl(path: str | Path, records: Iterator[RoundRecord], limit: int | None = None) -> int:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    from ..data.schema import jsonable

    written = 0
    with out.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps({"type": "round", **jsonable(record)}, ensure_ascii=False) + "\n")
            written += 1
            if limit is not None and written >= limit:
                break
    return written
