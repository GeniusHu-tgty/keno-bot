"""Connect if needed, then place a bounded 0.0001 live probe batch."""

from __future__ import annotations

import json
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


def main() -> None:
    status = wait_connected()
    print("status", status.get("status"), status.get("user_name"), status.get("balance"), status.get("nonce"))
    if status.get("status") != "connected":
        raise SystemExit(status.get("error") or "not connected")
    start = post(
        "/api/live/run",
        {
            "async": True,
            "live_bets": True,
            "new_session": True,
            "rounds": 20,
            "risk": "low",
            "pick_count": 10,
            "money": "flat",
            "picks": "pattern",
            "base_bet": "0.0001",
            "max_bet": "0.0001",
            "force_min": True,
            "stop_loss": "0.002",
            "pace_seconds": 3.5,
        },
    )
    print("start", start)
    job_id = start.get("job_id")
    if not job_id:
        raise SystemExit(start.get("error") or "no job")
    deadline = time.time() + 200
    while time.time() < deadline:
        job = get("/api/run/status?job_id=" + job_id)
        progress = (get("/api/live/status").get("progress") or {})
        print("job", job.get("status"), progress.get("completed"), "/", progress.get("total"), job.get("error"))
        if job.get("status") in {"completed", "cancelled", "failed"}:
            result = job.get("result") or {}
            print("stop", result.get("stop_reason"), "rounds", result.get("rounds"), "profit", result.get("profit"))
            bets = result.get("bets") or []
            if bets:
                print("shadow", bets[-1].get("shadow"))
                print("nonce", bets[-1].get("nonce_before"), "->", bets[-1].get("nonce"))
            return
        time.sleep(4)
    raise SystemExit("timeout")


if __name__ == "__main__":
    main()
