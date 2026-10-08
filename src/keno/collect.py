# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .data.schema import RoundRecord, jsonable

# Integer tokens, excluding digits inside decimals (0.0001) and longer ids (40712).
NUMBER_TOKEN = re.compile(r"(?<![\d.])\d+(?![\d.])")


def parse_round_line(line: str) -> list[int] | None:
    """Extract the drawn round from a pasted line, tolerating surrounding noise
    (timestamps, bet ids, amounts). Finds the unique contiguous run of exactly
    10 distinct numbers in 1..40; raises ValueError when absent or ambiguous."""
    stripped = line.strip()
    if not stripped:
        return None
    tokens = [int(t) for t in NUMBER_TOKEN.findall(stripped)]
    candidates: list[list[int]] = []
    for start in range(max(0, len(tokens) - 9)):
        window = tokens[start : start + 10]
        if all(1 <= n <= 40 for n in window) and len(set(window)) == 10:
            candidates.append(window)
    if not candidates:
        raise ValueError(f"no run of 10 distinct numbers in 1..40 found: {stripped!r}")
    if len(candidates) > 1:
        raise ValueError(
            f"ambiguous line, {len(candidates)} candidate runs found (copy only the drawn-number columns): {stripped!r}"
        )
    return candidates[0]


def collect_rounds(out_path: str | Path, lines, start_index: int = 0) -> int:
    """Append manually observed rounds to a JSONL log. `lines` is any iterable of str.

    Blank lines are skipped; a line 'done' stops collection cleanly. Bad or
    ambiguous lines are reported and skipped so one noisy row never loses the
    rest of the batch. Returns the number of rounds accepted.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    accepted = 0
    skipped: list[tuple[int, str]] = []
    with out.open("a", encoding="utf-8") as f:
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.lower() == "done":
                break
            if not stripped:
                continue
            try:
                numbers = parse_round_line(line)
            except ValueError as exc:
                skipped.append((lineno, str(exc)))
                continue
            if numbers is None:
                continue
            index = start_index + accepted
            record = RoundRecord(
                round_id=str(index),
                timestamp=datetime.now(timezone.utc),
                numbers=numbers,
                source="manual",
            )
            f.write(json.dumps({"type": "round", **jsonable(record)}, ensure_ascii=False) + "\n")
            accepted += 1
            print(f"logged round {index}: {numbers}")
    for lineno, reason in skipped:
        print(f"skipped line {lineno}: {reason}")
    if skipped:
        print(f"{len(skipped)} line(s) skipped, {accepted} rounds accepted")
    return accepted


def main_collect(out_path: str | Path) -> int:
    print("每行粘贴一局开奖的 10 个号码（逗号或空格分隔），输入 done 结束。")
    return collect_rounds(out_path, sys.stdin)


def read_clipboard() -> str:
    import platform
    import subprocess

    if platform.system() != "Windows":
        raise RuntimeError("--clipboard currently supports Windows only; paste manually instead")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to read clipboard: {result.stderr.strip()}")
    return result.stdout


def collect_from_clipboard(out_path: str | Path) -> int:
    """Collect rounds from the clipboard text: select the history rows on the
    site, copy, then run `keno collect --clipboard`. One paste can cover many rounds."""
    text = read_clipboard()
    lines = text.splitlines()
    accepted = collect_rounds(out_path, lines)
    print(f"clipboard: {accepted} rounds logged")
    return accepted
