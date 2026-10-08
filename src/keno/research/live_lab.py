# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

"""Turn paid live draws into extra learning without extra stake.

Every real draw is scored against several causal selection modes. Money
management is compared on paper. Nothing here claims a positive edge.
"""

import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from math import comb
from pathlib import Path
from random import Random

from .. import paths
from ..data.schema import RoundRecord
from ..strategies.selection import FIXED_PATTERN, select_numbers

LIVE_PATH = paths.data_dir() / "live_records.jsonl"
PAYOUTS_PATH = paths.official_payouts()
QUANT = Decimal("0.00000001")

SHADOW_MODES = ("fixed-pattern", "hot", "cold", "avoid-cold-zone", "balanced-random")


def _q(value: Decimal) -> Decimal:
    return value.quantize(QUANT)


def hypergeometric_p(hits: int, pick_count: int = 10, draw_count: int = 10, board: int = 40) -> float:
    if hits < 0 or hits > min(pick_count, draw_count):
        return 0.0
    remain = draw_count - hits
    pool = board - pick_count
    if remain < 0 or remain > pool:
        return 0.0
    return comb(pick_count, hits) * comb(pool, remain) / comb(board, draw_count)


def low10_multipliers() -> list[Decimal]:
    raw = json.loads(PAYOUTS_PATH.read_text(encoding="utf-8"))
    return [Decimal(str(x)) for x in raw["risks"]["low"]["10"]]


def theoretical_rtp(pick_count: int = 10) -> Decimal:
    table = low10_multipliers()
    expected = Decimal("0")
    for hits, multiplier in enumerate(table):
        expected += Decimal(str(hypergeometric_p(hits, pick_count))) * multiplier
    return expected


def shadow_for_draw(drawn: list[int], history: list[RoundRecord], pick_count: int = 10) -> dict[str, int]:
    drawn_set = set(int(n) for n in drawn)
    out: dict[str, int] = {}
    out["fixed-pattern"] = len(drawn_set & set(FIXED_PATTERN[:pick_count]))
    for mode in ("hot", "cold", "avoid-cold-zone", "balanced-random"):
        rng = Random(7 + len(history))
        picks = select_numbers(mode, history, pick_count, rng, recent_window=100)
        out[mode] = len(drawn_set & set(picks))
    return out


def _as_history(drawn_rows: list[list[int]]) -> list[RoundRecord]:
    rows = []
    for i, numbers in enumerate(drawn_rows):
        rows.append(
            RoundRecord(
                round_id=str(i),
                timestamp=datetime.now(),
                numbers=list(numbers),
                source="live",
            )
        )
    return rows


def load_live_records(path: Path | None = None) -> list[dict]:
    target = path or LIVE_PATH
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def analyze_live_records(records: list[dict] | None = None) -> dict:
    records = records if records is not None else load_live_records()
    rtp = theoretical_rtp()
    table = low10_multipliers()
    expected_hits = sum(k * hypergeometric_p(k) for k in range(11))
    hits = Counter(int(r.get("hits") or 0) for r in records)
    staked = Decimal("0")
    returned = Decimal("0")
    prior: list[list[int]] = []
    shadow_hits: dict[str, list[int]] = {mode: [] for mode in SHADOW_MODES}
    shadow_pnl: dict[str, Decimal] = {mode: Decimal("0") for mode in SHADOW_MODES}
    actual_hits_list = []
    for row in records:
        bet = Decimal(str(row.get("bet") or "0"))
        payout = Decimal(str(row.get("payout") or "0"))
        staked += bet
        returned += payout
        drawn = [int(n) for n in (row.get("drawn") or [])]
        actual = int(row.get("hits") or 0)
        actual_hits_list.append(actual)
        history = _as_history(prior)
        shadow = shadow_for_draw(drawn, history, int(row.get("pick_count") or 10))
        for mode, count in shadow.items():
            shadow_hits[mode].append(count)
            multiplier = table[count] if count < len(table) else Decimal("0")
            shadow_pnl[mode] += _q(bet * multiplier - bet)
        if drawn:
            prior.append(drawn)
    n = len(records)
    observed_rtp = (returned / staked) if staked else Decimal("0")
    hit_table = []
    for k in range(11):
        observed = hits.get(k, 0)
        expected = hypergeometric_p(k) * n
        hit_table.append(
            {
                "hits": k,
                "observed": observed,
                "expected": round(expected, 3),
                "p": round(hypergeometric_p(k), 6),
            }
        )
    shadow_summary = []
    actual_pnl = _q(returned - staked)
    for mode in SHADOW_MODES:
        values = shadow_hits[mode]
        mean_hits = (sum(values) / len(values)) if values else 0.0
        shadow_summary.append(
            {
                "mode": mode,
                "mean_hits": round(mean_hits, 4),
                "profit": str(_q(shadow_pnl[mode])),
                "vs_actual_profit": str(_q(shadow_pnl[mode] - actual_pnl)),
            }
        )
    return {
        "rounds": n,
        "staked": str(_q(staked)),
        "returned": str(_q(returned)),
        "profit": str(actual_pnl),
        "observed_rtp": str(observed_rtp),
        "theoretical_rtp": str(rtp),
        "expected_hits": round(expected_hits, 4),
        "mean_hits": round((sum(actual_hits_list) / n) if n else 0.0, 4),
        "hit_table": hit_table,
        "shadow": shadow_summary,
        "wins": sum(1 for r in records if Decimal(str(r.get("payout") or "0")) > Decimal(str(r.get("bet") or "0"))),
    }


def write_markdown(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 实盘能力实验（探针，不追求正期望）",
        "",
        f"- 局数：{report['rounds']}",
        f"- 投入：{report['staked']}　回收：{report['returned']}　盈亏：{report['profit']}",
        f"- 实盘 RTP：{report['observed_rtp']}　理论 RTP：{report['theoretical_rtp']}",
        f"- 平均命中：{report['mean_hits']}　理论平均命中：{report['expected_hits']}",
        "",
        "## 命中分布（已付费开奖，对照超几何）",
        "",
        "| 命中 | 实盘 | 理论期望 | 理论概率 |",
        "|---:|---:|---:|---:|",
    ]
    for row in report["hit_table"]:
        lines.append(f"| {row['hits']} | {row['observed']} | {row['expected']} | {row['p']} |")
    lines += [
        "",
        "## 阴影选号（同一开奖、不另花钱）",
        "",
        "把已经开出来的号套到别的选号法上。平均命中接近 2.5 就是随机，谁高谁低都是噪音。",
        "",
        "| 选号 | 平均命中 | 若用该方法的盈亏 | 相对实盘 |",
        "|---|---:|---:|---:|",
    ]
    for row in report["shadow"]:
        lines.append(
            f"| {row['mode']} | {row['mean_hits']} | {row['profit']} | {row['vs_actual_profit']} |"
        )
    lines += [
        "",
        "## 结论闸",
        "",
        "- 选号阴影如果没有稳定高出理论 2.5 命中，就不要为换选号法加注。",
        "- 实盘 RTP 围绕 98.76% 波动，样本不够大时正负都正常。",
        "- 操作规则只改形状：探针 0.0001、硬止损、不把阶段机抬到 0.10/0.60。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
