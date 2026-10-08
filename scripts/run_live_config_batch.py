# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
"""Run a small live probe batch with an explicit risk/pick config."""

from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=15) as response:
        return json.loads(response.read().decode())


def post(path: str, payload: dict, timeout: int = 30) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def wait_connected(seconds: float = 120) -> dict:
    status = get("/api/live/status")
    if status.get("status") == "connected":
        return status
    post("/api/live/connect", {"wait_login": 180})
    deadline = time.time() + seconds
    while time.time() < deadline:
        status = get("/api/live/status")
        if status.get("status") in {"connected", "error"}:
            return status
        time.sleep(2)
    return status


def run_batch(risk: str, pick_count: int, rounds: int, tag: str) -> dict:
    status = wait_connected()
    print("status", status.get("status"), status.get("balance"), status.get("nonce"), tag)
    if status.get("status") != "connected":
        raise SystemExit(status.get("error") or "not connected")
    start = post(
        "/api/live/run",
        {
            "async": True,
            "live_bets": True,
            "new_session": True,
            "rounds": rounds,
            "risk": risk,
            "pick_count": pick_count,
            "money": "flat",
            "picks": "pattern",
            "base_bet": "0.0001",
            "max_bet": "0.0001",
            "force_min": True,
            "stop_loss": "0.002",
            "pace_seconds": 3.5,
        },
    )
    job_id = start.get("job_id")
    print("start", tag, start)
    if not job_id:
        raise SystemExit(start.get("error") or "no job")
    deadline = time.time() + 30 + rounds * 6
    while time.time() < deadline:
        job = get("/api/run/status?job_id=" + job_id)
        if job.get("status") in {"completed", "cancelled", "failed"}:
            result = job.get("result") or {}
            print(
                "done",
                tag,
                job.get("status"),
                result.get("stop_reason"),
                "rounds",
                result.get("rounds"),
                "profit",
                result.get("profit"),
                "err",
                job.get("error"),
            )
            return result
        time.sleep(3)
    raise SystemExit("timeout " + tag)


def main() -> None:
    configs = [
        ("classic", 10, 12, "classic10"),
        ("low", 9, 8, "low9"),
    ]
    if len(sys.argv) > 1:
        configs = [(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4])]
    for item in configs:
        run_batch(*item)


if __name__ == "__main__":
    main()
