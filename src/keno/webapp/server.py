# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

"""Keno BOT — local simulated training workbench (no real money, no external I/O).

Reuses the project's verified core:
  * HMAC-SHA256 stream RNG + draw_keno (matches the real platform, 4/4 verified)
  * official payout tables (data/reference/stake_keno_payouts_official.json)
  * the phase-style phase machine (keno.bot.phases.PhaseMachine)

Stdlib-only HTTP server + single-page frontend. Every bet is appended to
data/webapp/records.jsonl; state persists in data/webapp/state.json.
"""

import hashlib
import json
import re
import secrets
import socket
import threading
import time
import uuid
from math import comb
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import paths
from ..bot.phases import PhaseMachine
from ..bot.money import (
    AdaptiveFractionalManager,
    CappedRecoveryManager,
    FractionalMoneyManager,
    ProbeWindowManager,
)
from ..bot.regime import RegimeDetector
from ..strategies import SelectionStrategy
from ..strategies.pattern import PatternStrategy
from ..game.keno_draw import draw_keno
from ..provably_fair.float_generator import FloatGenerator
from ..provably_fair.hmac_rng import HmacSha256Rng

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = paths.bundle_root()
DATA_DIR = paths.data_dir()
STATIC_DIR = paths.static_dir()
PAYOUTS_PATH = paths.official_payouts()
PHASE_CONFIG = paths.config_file("bot_phase.yaml")

MIN_BET = Decimal("0.0001")
QUANT = Decimal("0.00000001")

RISKS = ("low", "classic", "medium", "high")


def _q(value: Decimal) -> Decimal:
    return value.quantize(QUANT)


def _dec_str(value: Decimal) -> str:
    return str(_q(value))


def load_payouts() -> dict:
    if not PAYOUTS_PATH.exists():
        raise SystemExit(f"missing official payouts: {PAYOUTS_PATH}")
    raw = json.loads(PAYOUTS_PATH.read_text(encoding="utf-8"))
    tables: dict[str, dict[int, list[float]]] = {}
    for risk, picks in raw["risks"].items():
        tables[risk] = {int(p): [float(x) for x in table] for p, table in picks.items()}
    return tables


PAYOUTS = load_payouts()


class LabState:
    """Single-operator lab state: virtual balance, seed pair, records."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.balance = Decimal("100.00")
        self.client_seed = secrets.token_hex(5)
        self.server_seed = secrets.token_hex(32)
        self.nonce = 0
        self.next_id = 1
        self.records: list[dict] = []
        self.revealed: list[dict] = []
        self.session = {"batch": 1, "run": 1, "start_index": 0, "started_at": time.time()}
        self.auto_rotate = {"rounds": 0, "minutes": 0}
        self.rounds_since_rotate = 0
        self.last_rotate_at = time.time()
        self._load()

    # ---------- persistence ----------

    def _state_path(self) -> Path:
        return DATA_DIR / "state.json"

    def _records_path(self) -> Path:
        return DATA_DIR / "records.jsonl"

    def _load(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        rp = self._records_path()
        if rp.exists():
            for line in rp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self.records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        sp = self._state_path()
        if sp.exists():
            try:
                data = json.loads(sp.read_text(encoding="utf-8"))
                self.balance = Decimal(str(data.get("balance", "100.00")))
                self.client_seed = str(data.get("client_seed", self.client_seed))
                self.server_seed = str(data.get("server_seed", self.server_seed))
                self.nonce = int(data.get("nonce", 0))
                self.next_id = int(data.get("next_id", len(self.records) + 1))
                self.revealed = list(data.get("revealed", []))
                self.session = dict(data.get("session", self.session))
                self.auto_rotate = dict(data.get("auto_rotate", self.auto_rotate))
                self.rounds_since_rotate = int(data.get("rounds_since_rotate", 0))
                self.last_rotate_at = float(data.get("last_rotate_at", time.time()))
            except (json.JSONDecodeError, ValueError):
                pass

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "balance": _dec_str(self.balance),
            "client_seed": self.client_seed,
            "server_seed": self.server_seed,
            "nonce": self.nonce,
            "next_id": self.next_id,
            "revealed": self.revealed,
            "session": self.session,
            "auto_rotate": self.auto_rotate,
            "rounds_since_rotate": self.rounds_since_rotate,
            "last_rotate_at": self.last_rotate_at,
        }
        self._state_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_record(self, record: dict) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with self._records_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ---------- domain ----------

    def level(self) -> str:
        return f"B{self.session['batch']}R{self.session['run']}"

    def server_seed_hash(self) -> str:
        return hashlib.sha256(self.server_seed.encode()).hexdigest()

    def settle(self, picks: list[int], risk: str, amount: Decimal, stage: str) -> dict:
        """Resolve one round with the provably-fair stream RNG; update balance."""
        if risk not in PAYOUTS:
            raise ValueError(f"未知难度：{risk}")
        if len(picks) not in PAYOUTS[risk]:
            raise ValueError(f"该难度不支持 {len(picks)} 选")
        if amount < MIN_BET:
            raise ValueError(f"低于最低投注 {MIN_BET}")
        if amount > self.balance:
            raise ValueError("余额不足（本地虚拟余额）")

        nonce = self.nonce
        rng = FloatGenerator(HmacSha256Rng(self.server_seed, self.client_seed, nonce=nonce, cursor=0))
        drawn = draw_keno(rng)
        hits = len(set(picks) & set(drawn))
        multiplier = Decimal(str(PAYOUTS[risk][len(picks)][hits]))
        payout = _q(amount * multiplier)
        profit = _q(payout - amount)

        self.balance = _q(self.balance - amount + payout)
        self.nonce = nonce + 1

        record = {
            "id": self.next_id,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "session": self.level(),
            "stage": stage,
            "probe": "探针" in str(stage) or str(stage).lower() == "probe",
            "picks": picks,
            "drawn": drawn,
            "hits": hits,
            "risk": risk,
            "pick_count": len(picks),
            "bet": _dec_str(amount),
            "multiplier": str(multiplier),
            "payout": _dec_str(payout),
            "profit": _dec_str(profit),
            "nonce": nonce,
            "client_seed": self.client_seed,
            "server_seed_hash": self.server_seed_hash(),
            "balance_after": _dec_str(self.balance),
            "book": "paper",
        }
        self.next_id += 1
        self.records.append(record)
        self.append_record(record)
        self.rounds_since_rotate += 1
        self._maybe_auto_rotate()
        return record

    def rotate(self, new_client_seed: str | None = None) -> dict:
        """Reveal the current server seed and start a new pair (like the real flow)."""
        revealed = {
            "server_seed": self.server_seed,
            "server_seed_hash": self.server_seed_hash(),
            "client_seed": self.client_seed,
            "nonce_start": 0,
            "nonce_end": max(0, self.nonce - 1),
            "rotated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.revealed.append(revealed)
        self.client_seed = (new_client_seed or "").strip() or secrets.token_hex(5)
        self.server_seed = secrets.token_hex(32)
        self.nonce = 0
        self.rounds_since_rotate = 0
        self.last_rotate_at = time.time()
        self.save()
        return revealed

    def _maybe_auto_rotate(self) -> None:
        rounds = int(self.auto_rotate.get("rounds") or 0)
        minutes = int(self.auto_rotate.get("minutes") or 0)
        if rounds and self.rounds_since_rotate >= rounds:
            self.rotate()
        elif minutes and (time.time() - self.last_rotate_at) >= minutes * 60:
            self.rotate()

    def new_session(self, new_batch: bool = False) -> None:
        if new_batch:
            self.session["batch"] += 1
            self.session["run"] = 1
        else:
            self.session["run"] += 1
        self.session["start_index"] = len(self.records)
        self.session["started_at"] = time.time()
        self.save()


STATE = LabState()
LAB_JOBS: dict[str, dict] = {}
LAB_JOBS_LOCK = threading.RLock()


def _aggregate(records: list[dict]) -> dict:
    staked = Decimal(0)
    returned = Decimal(0)
    wins = 0
    for r in records:
        staked += Decimal(r["bet"])
        returned += Decimal(r["payout"])
        if Decimal(r["payout"]) > Decimal(r["bet"]):
            wins += 1
    profit = _q(returned - staked)
    return {
        "rounds": len(records),
        "staked": _dec_str(staked),
        "returned": _dec_str(returned),
        "profit": _dec_str(profit),
        "roi_pct": float(profit / staked * 100) if staked > 0 else 0.0,
        "success_rate": (wins / len(records)) if records else 0.0,
    }


def _theory(risk: str, pick_count: int) -> dict:
    """Exact one-round probabilities from the official hypergeometric model."""
    table = PAYOUTS[risk][pick_count]
    denominator = comb(40, pick_count)
    expected_profit = Decimal("0")
    profitable = Decimal("0")
    returned = Decimal("0")
    for hits, multiplier in enumerate(table):
        if hits > 10 or pick_count - hits < 0 or pick_count - hits > 30:
            continue
        probability = Decimal(comb(10, hits) * comb(30, pick_count - hits)) / Decimal(denominator)
        mult = Decimal(str(multiplier))
        expected_profit += probability * (mult - Decimal("1"))
        if mult > Decimal("1"):
            profitable += probability
        if mult > Decimal("0"):
            returned += probability
    return {
        "risk": risk,
        "pick_count": pick_count,
        "rtp_pct": float((Decimal("1") + expected_profit) * 100),
        "expected_roi_pct": float(expected_profit * 100),
        "profit_probability_pct": float(profitable * 100),
        "return_probability_pct": float(returned * 100),
        "loss_probability_pct": float((Decimal("1") - profitable) * 100),
    }


def _block_table(records: list[dict], pace_seconds: float = 3.5) -> list[dict]:
    block_size = max(1, round(15 * 60 / max(0.1, pace_seconds)))
    rows = []
    for offset in range(0, len(records), block_size):
        subset = records[offset : offset + block_size]
        agg = _aggregate(subset)
        rows.append({
            "block": offset // block_size + 1,
            "round_start": offset + 1,
            "round_end": offset + len(subset),
            **agg,
        })
    return rows


def _regime(records: list[dict]) -> dict:
    detector = RegimeDetector(window=30)
    for record in records[-30:]:
        detector.observe(Decimal(record["profit"]))
    return {
        "state": detector.state.value,
        "window": len(detector.profits),
        "loss_streak": sum(1 for value in reversed(detector.profits) if value < 0),
        "win_streak": sum(1 for value in reversed(detector.profits) if value > 0),
        "recommended_action": detector.recommended_action,
        "should_pause": detector.should_pause,
        "note": "仅用于描述已发生的收益波动，不预测下一局。",
    }


def _hit_table(records: list[dict]) -> list[dict]:
    rows = []
    for hits in range(0, 11):
        subset = [r for r in records if r["hits"] == hits]
        if not subset:
            continue
        agg = _aggregate(subset)
        rows.append(
            {
                "hits": hits,
                "rounds": agg["rounds"],
                "share": agg["rounds"] / len(records) if records else 0.0,
                "staked": agg["staked"],
                "returned": agg["returned"],
                "profit": agg["profit"],
            }
        )
    return rows


_STAGE_KIND_RE = re.compile(
    r"^(?:B)?(\d+)\s*(?:阶段)?\s*(恢复|取利|收尾|收益1|收益2|探针)$"
)
_STAGE_CN_RE = re.compile(r"^(\d+)阶段\s*(恢复|收益1|收益2)$")
_KIND_ALIAS = {"取利": "收益1", "收尾": "收益2"}
_KIND_RANK = {"探针": 0, "恢复": 1, "收益1": 2, "收益2": 3}


def _stage_parts(stage: str) -> tuple[int | None, str]:
    """Split a stored stage label into (block, kind) for phase-style tables."""
    text = str(stage or "?").strip()
    if "探针" in text:
        return (None, "探针")
    matched = _STAGE_KIND_RE.match(text) or _STAGE_CN_RE.match(text)
    if matched:
        return (int(matched.group(1)), _KIND_ALIAS.get(matched.group(2), matched.group(2)))
    return (None, text)


def _stage_label(block: int | None, kind: str) -> str:
    if block is None or kind == "探针":
        return kind
    return f"{block}阶段 {kind}"


def _stage_row(stage: str, subset: list[dict], role: str) -> dict:
    agg = _aggregate(subset)
    wins = sum(1 for r in subset if Decimal(r["payout"]) > Decimal(r["bet"]))
    return {
        "stage": stage,
        "role": role,
        "rounds": agg["rounds"],
        "wins": wins,
        "fails": agg["rounds"] - wins,
        "success_rate": (wins / agg["rounds"]) if agg["rounds"] else 0.0,
        "staked": agg["staked"],
        "returned": agg["returned"],
        "profit": agg["profit"],
    }


def _stage_table(records: list[dict]) -> list[dict]:
    if not records:
        return []
    buckets: dict[tuple[int | None, str], list[dict]] = {}
    order: list[tuple[int | None, str]] = []
    for record in records:
        key = _stage_parts(str(record.get("stage", "?")))
        if key not in buckets:
            order.append(key)
            buckets[key] = []
        buckets[key].append(record)

    def sort_key(item: tuple[int | None, str]) -> tuple[int, int, int]:
        block, kind = item
        if kind == "探针":
            return (0, 0, 0)
        if block is not None and kind in _KIND_RANK:
            return (1, block, _KIND_RANK[kind])
        return (2, 0, order.index(item))

    rows: list[dict] = []
    current_block: int | None = None
    block_records: list[dict] = []

    def flush_subtotal() -> None:
        nonlocal block_records
        if current_block is not None and block_records:
            rows.append(_stage_row(f"{current_block}阶段 小计", block_records, "subtotal"))
        block_records = []

    for key in sorted(order, key=sort_key):
        block, kind = key
        subset = buckets[key]
        if block != current_block:
            flush_subtotal()
            current_block = block
        if block is not None:
            block_records.extend(subset)
        rows.append(_stage_row(_stage_label(block, kind), subset, "stage"))
    flush_subtotal()
    rows.append(_stage_row("合计", records, "total"))
    return rows


def _session_records() -> list[dict]:
    return STATE.records[STATE.session["start_index"] :]


def state_snapshot() -> dict:
    session_records = _session_records()
    risk = "low"
    pick_count = 10
    theory_matrix = {
        current_risk: {
            str(current_pick): _theory(current_risk, current_pick)
            for current_pick in range(1, 11)
        }
        for current_risk in RISKS
    }
    return {
        "balance": _dec_str(STATE.balance),
        "level": STATE.level(),
        "nonce": STATE.nonce,
        "client_seed": STATE.client_seed,
        "server_seed_hash": STATE.server_seed_hash(),
        "min_bet": str(MIN_BET),
        "auto_rotate": dict(STATE.auto_rotate),
        "paytable": {risk: {str(pick): table for pick, table in picks.items()} for risk, picks in PAYOUTS.items()},
        "session": {
            **_aggregate(session_records),
            "duration_sec": int(time.time() - STATE.session["started_at"]),
        },
        "lifetime": _aggregate(STATE.records),
        "stage_table": _stage_table(session_records),
        "hit_table": _hit_table(session_records),
        "theory": _theory(risk, pick_count),
        "theory_matrix": theory_matrix,
        "regime": _regime(session_records),
        "block_table": _block_table(session_records),
        "revealed": [
            {
                "server_seed_hash": r["server_seed_hash"],
                "server_seed": r["server_seed"],
                "client_seed": r["client_seed"],
                "nonce_start": r["nonce_start"],
                "nonce_end": r["nonce_end"],
                "rotated_at": r["rotated_at"],
            }
            for r in STATE.revealed[-5:]
        ],
    }


def history(limit: int = 80, book: str = "paper", scope: str = "session") -> list[dict]:
    from ..bot.ledger import scoped_records

    if book in ("live", "all"):
        rows = scoped_records(book, scope)
        return list(reversed(rows[-limit:]))
    if scope == "lifetime":
        rows = list(STATE.records)
    else:
        rows = _session_records()
    tagged = [{**r, "book": r.get("book") or "paper"} for r in rows]
    return list(reversed(tagged[-limit:]))


# ---------------- automated runner ----------------

def _pick_set(mode: str, pick_count: int, rng_seed: int) -> list[int]:
    if mode == "pattern":
        reference = [3, 6, 14, 16, 22, 25, 29, 36, 37, 38]
        return sorted(reference[:pick_count]) if pick_count <= 10 else reference
    import random as _random

    rnd = _random.Random(rng_seed)
    return sorted(rnd.sample(range(1, 41), pick_count))


def _optional_decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    return abs(Decimal(str(value)))


def _build_auto_managers(kind: str, base_bet: Decimal):
    pm = PhaseMachine.from_yaml(PHASE_CONFIG) if kind == "phase" else None
    fractional = (
        FractionalMoneyManager(
            fraction=Decimal("0.0005"),
            min_bet=MIN_BET,
            max_fraction=Decimal("0.002"),
        )
        if kind == "fractional"
        else None
    )
    adaptive = (
        AdaptiveFractionalManager(
            fraction=Decimal("0.0005"),
            cautious_fraction=Decimal("0.0001"),
            min_bet=MIN_BET,
            max_fraction=Decimal("0.002"),
        )
        if kind == "adaptive"
        else None
    )
    probe = (
        ProbeWindowManager(
            probe_bet=MIN_BET,
            active_bet=base_bet,
            probe_rounds=30,
            active_rounds=60,
            cooldown_rounds=30,
        )
        if kind == "probe"
        else None
    )
    capped = (
        CappedRecoveryManager(
            base_bet=base_bet,
            multiplier=Decimal("1.25"),
            max_steps=4,
        )
        if kind == "capped"
        else None
    )
    return pm, fractional, adaptive, probe, capped


def _next_auto_stake(kind, pm, fractional, adaptive, probe, capped, mart_step, base_bet, balance):
    if pm is not None:
        return pm.display_stage, pm.next_bet(balance), pm.is_probe
    if fractional is not None:
        return fractional.phase, fractional.next_bet(balance), False
    if adaptive is not None:
        return adaptive.phase, adaptive.next_bet(balance), False
    if probe is not None:
        stage = probe.phase
        return stage, probe.next_bet(balance), stage == "probe"
    if capped is not None:
        return capped.phase, capped.next_bet(balance), False
    if kind == "martingale":
        return "马丁", base_bet * (2 ** mart_step), False
    return "平注", base_bet, False


def _observe_auto_managers(kind, pm, fractional, adaptive, probe, capped, profit: Decimal) -> None:
    if pm is not None:
        pm.observe(profit)
    elif fractional is not None:
        fractional.observe(profit)
    elif adaptive is not None:
        adaptive.observe(profit)
    elif probe is not None:
        probe.observe(profit)
    elif capped is not None:
        capped.observe(profit)


def _risk_pause(pm, fractional, adaptive, probe, capped) -> str | None:
    if pm is not None and pm.should_pause():
        return "risk-control pause"
    for manager in (fractional, adaptive, probe, capped):
        if manager is not None and manager.should_pause():
            return f"risk-control pause ({manager.risk_action})"
    return None


def _sleep_pace(pace_seconds: float, cancel_event: threading.Event | None) -> bool:
    deadline = time.monotonic() + pace_seconds
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            return True
        time.sleep(min(0.1, max(0.01, deadline - time.monotonic())))
    return False


def _run_one_auto_session(
    *,
    kind: str,
    rounds: int,
    risk: str,
    pick_count: int,
    base_bet: Decimal,
    session_bankroll: Decimal,
    stop_win: Decimal | None,
    stop_loss: Decimal | None,
    max_drawdown_limit: Decimal | None,
    picks_mode: str,
    pace_seconds: float,
    realtime: bool,
    block_size: int,
    progress_callback,
    cancel_event: threading.Event | None,
    completed_before: int,
    total_estimate: int,
    selection_rng,
) -> dict:
    pm, fractional, adaptive, probe, capped = _build_auto_managers(kind, base_bet)
    selection_strategy = (
        SelectionStrategy(picks_mode, block_rounds=block_size)
        if picks_mode in {
            "random",
            "block-random",
            "fixed-pattern",
            "hot",
            "cold",
            "avoid-cold-zone",
            "balanced-random",
        }
        else None
    )
    pattern_strategy = PatternStrategy(reroll_every=4) if picks_mode == "pattern" else None
    selection_history = []
    mart_step = 0
    session_remaining = session_bankroll
    peak = Decimal(0)
    max_dd = Decimal(0)
    stop_reason = "rounds completed"
    profit = Decimal(0)
    risk_action = "continue"
    block_picks: list[int] | None = None

    with STATE.lock:
        STATE.new_session()
        session_id = STATE.level()
        start_index = len(STATE.records)

    played = 0
    for i in range(rounds):
        if cancel_event is not None and cancel_event.is_set():
            stop_reason = "cancelled"
            break
        pause = _risk_pause(pm, fractional, adaptive, probe, capped)
        if pause:
            stop_reason = pause
            risk_action = "pause"
            break
        with STATE.lock:
            balance = STATE.balance
        stage, bet, is_probe = _next_auto_stake(
            kind, pm, fractional, adaptive, probe, capped, mart_step, base_bet, balance
        )
        bet = min(bet, balance, session_remaining)
        if bet < MIN_BET:
            stop_reason = "session budget depleted" if balance >= MIN_BET else "bankroll exhausted"
            break
        if selection_strategy is not None:
            picks = selection_strategy.predict(selection_history, pick_count, selection_rng)
        elif pattern_strategy is not None:
            picks = pattern_strategy.predict([], pick_count, selection_rng)
        elif picks_mode == "block-random":
            if block_picks is None or i % block_size == 0:
                block_picks = _pick_set("random", pick_count, rng_seed=int(time.time() * 1000) + i)
            picks = block_picks
        else:
            picks = _pick_set(picks_mode, pick_count, rng_seed=i + 17)
        with STATE.lock:
            record = STATE.settle(picks, risk, bet, stage)
            record["probe"] = bool(is_probe or "探针" in stage)
        if selection_strategy is not None:
            from types import SimpleNamespace

            selection_history.append(SimpleNamespace(numbers=list(record["drawn"])))
        round_profit = Decimal(record["profit"])
        profit += round_profit
        session_remaining = _q(session_remaining - bet)
        _observe_auto_managers(kind, pm, fractional, adaptive, probe, capped, round_profit)
        if kind == "martingale":
            mart_step = mart_step + 1 if Decimal(record["payout"]) == 0 else 0
        peak = max(peak, profit)
        max_dd = max(max_dd, peak - profit)
        played = i + 1
        if profit <= -session_bankroll:
            stop_reason = "session bankroll depleted"
            break
        if stop_win is not None and profit >= stop_win:
            stop_reason = "stop-win hit"
            break
        if stop_loss is not None and profit <= -stop_loss:
            stop_reason = "stop-loss hit"
            break
        if max_drawdown_limit is not None and max_dd >= max_drawdown_limit:
            stop_reason = "max-drawdown hit"
            break
        if progress_callback is not None:
            progress_callback(completed_before + played, total_estimate, record)
        if realtime and i + 1 < rounds:
            if _sleep_pace(pace_seconds, cancel_event):
                stop_reason = "cancelled"
                break

    with STATE.lock:
        session_records = list(STATE.records[start_index:])
        STATE.save()
    agg = _aggregate(session_records)
    agg["stop_reason"] = stop_reason
    agg["max_drawdown"] = _dec_str(max_dd)
    agg["stage_table"] = _stage_table(session_records)
    agg["hit_table"] = _hit_table(session_records)
    agg["level"] = session_id
    agg["cancelled"] = stop_reason == "cancelled"
    agg["risk_action"] = risk_action
    agg["realtime"] = realtime
    agg["session_budget_remaining"] = _dec_str(session_remaining)
    agg["pace_seconds"] = pace_seconds
    agg["block_rounds"] = block_size
    agg["block_table"] = _block_table(session_records, pace_seconds)
    agg["played"] = played
    agg["fatal"] = stop_reason in ("bankroll exhausted", "session bankroll depleted")
    return agg


def run_auto(payload: dict, progress_callback=None, cancel_event: threading.Event | None = None) -> dict:
    kind = str(payload.get("kind", "phase"))
    unattended = bool(payload.get("unattended", False))
    hours = max(0.0, float(payload.get("hours", 0) or 0))
    max_sessions = int(payload.get("max_sessions", 0) or 0)
    if unattended and max_sessions <= 0 and hours <= 0:
        hours = 24.0
    if not unattended:
        max_sessions = 1
        hours = 0.0
    rounds = min(max(int(payload.get("rounds", 176) or 176), 1), 10000 if unattended else 2000)
    risk = str(payload.get("risk", "low"))
    if risk not in RISKS:
        raise ValueError(f"未知难度：{risk}")
    pick_count = min(max(int(payload.get("pick_count", 10)), 1), 10)
    base_bet = Decimal(str(payload.get("base_bet", "0.01")))
    session_bankroll = Decimal(str(payload.get("session_bankroll", "10")))
    if session_bankroll <= 0:
        raise ValueError("会话资金必须为正数")
    stop_win = _optional_decimal(payload.get("stop_win"))
    stop_loss = _optional_decimal(payload.get("stop_loss"))
    max_drawdown_limit = _optional_decimal(payload.get("max_drawdown"))
    daily_loss_limit = _optional_decimal(payload.get("daily_loss_limit")) or session_bankroll
    picks_mode = str(payload.get("picks", "pattern"))
    pace_seconds = max(0.1, float(payload.get("pace_seconds", 3.5) or 3.5))
    realtime = bool(payload.get("realtime", False))
    default_block = max(1, round(15 * 60 / pace_seconds))
    block_size = max(1, int(payload.get("block_rounds", default_block) or default_block))
    wall_start = time.monotonic()
    import random as _random

    with STATE.lock:
        selection_rng = _random.Random(STATE.next_id + 100003)

    if hours > 0:
        total_estimate = max(1, int(hours * 3600 / pace_seconds)) if realtime else max(rounds, max_sessions * rounds or rounds)
    elif max_sessions > 1:
        total_estimate = max_sessions * rounds
    else:
        total_estimate = rounds

    sessions: list[dict] = []
    completed = 0
    cumulative_profit = Decimal(0)
    stop_all = "sessions completed"
    global_start = None
    with STATE.lock:
        global_start = len(STATE.records)

    while True:
        if cancel_event is not None and cancel_event.is_set():
            stop_all = "cancelled"
            break
        if hours and (time.monotonic() - wall_start) >= hours * 3600:
            stop_all = "hours completed"
            break
        if max_sessions and len(sessions) >= max_sessions:
            stop_all = "sessions completed"
            break
        if cumulative_profit <= -daily_loss_limit:
            stop_all = "daily-loss hit"
            break
        session = _run_one_auto_session(
            kind=kind,
            rounds=rounds,
            risk=risk,
            pick_count=pick_count,
            base_bet=base_bet,
            session_bankroll=session_bankroll,
            stop_win=stop_win,
            stop_loss=stop_loss,
            max_drawdown_limit=max_drawdown_limit,
            picks_mode=picks_mode,
            pace_seconds=pace_seconds,
            realtime=realtime,
            block_size=block_size,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            completed_before=completed,
            total_estimate=total_estimate,
            selection_rng=selection_rng,
        )
        sessions.append({
            "level": session["level"],
            "rounds": session["rounds"],
            "profit": session["profit"],
            "staked": session["staked"],
            "returned": session["returned"],
            "success_rate": session["success_rate"],
            "stop_reason": session["stop_reason"],
            "max_drawdown": session["max_drawdown"],
            "session_budget_remaining": session.get("session_budget_remaining", "0"),
        })
        completed += int(session.get("played") or session["rounds"])
        cumulative_profit += Decimal(session["profit"])
        if session["cancelled"]:
            stop_all = "cancelled"
            break
        if session.get("fatal"):
            stop_all = session["stop_reason"]
            break
        if not unattended:
            stop_all = session["stop_reason"]
            break

    with STATE.lock:
        all_records = list(STATE.records[global_start:])
        STATE.save()
    agg = _aggregate(all_records)
    last = sessions[-1] if sessions else {}
    agg["stop_reason"] = stop_all
    agg["max_drawdown"] = last.get("max_drawdown", "0")
    agg["stage_table"] = _stage_table(all_records)
    agg["hit_table"] = _hit_table(all_records)
    agg["level"] = last.get("level", STATE.level())
    agg["cancelled"] = stop_all == "cancelled"
    agg["risk_action"] = "continue"
    agg["realtime"] = realtime
    agg["session_budget_remaining"] = last.get("session_budget_remaining", "0")
    agg["pace_seconds"] = pace_seconds
    agg["block_rounds"] = block_size
    agg["block_table"] = _block_table(all_records, pace_seconds)
    agg["unattended"] = unattended
    agg["session_count"] = len(sessions)
    agg["sessions"] = sessions
    agg["green_sessions"] = sum(1 for row in sessions if Decimal(row["profit"]) > 0)
    agg["cumulative_profit"] = _dec_str(cumulative_profit)
    agg["hours"] = hours
    return agg


# ---------------- strategy lab ----------------

def _lab_draws(sessions: int, rounds: int) -> list[list[list[int]]]:
    base = secrets.token_hex(8)
    draws: list[list[list[int]]] = []
    for s in range(sessions):
        seed = hashlib.sha256(f"{base}:{s}".encode()).hexdigest()
        rows = []
        for r in range(rounds):
            rng = FloatGenerator(HmacSha256Rng(seed, "lab-client", nonce=r, cursor=0))
            rows.append(draw_keno(rng))
        draws.append(rows)
    return draws


def _simulate_kind(kind: str, draws: list[list[list[int]]], risk: str, pick_count: int) -> dict:
    import random as _random

    profits: list[Decimal] = []
    rois: list[float] = []
    dds: list[Decimal] = []
    ruins = 0
    base_bet = Decimal("0.01")
    table = PAYOUTS[risk][pick_count]

    for s, session_draws in enumerate(draws):
        # 10u bankroll so the ladder rungs (0.0001/0.01/0.1/0.6) keep their
        # real ratios (final shot = 6% of bankroll), matching the screenshots.
        bankroll = Decimal("10.0")
        profit = Decimal(0)
        peak = Decimal(0)
        max_dd = Decimal(0)
        staked = Decimal(0)
        pm = PhaseMachine.from_yaml(PHASE_CONFIG) if kind == "phase" else None
        mart_step = 0
        rnd = _random.Random(1000 + s)
        for r, drawn in enumerate(session_draws):
            if pm is not None:
                bet = pm.next_bet(bankroll)
            elif kind == "martingale":
                bet = base_bet * (2 ** mart_step)
            else:
                bet = base_bet
            bet = min(bet, bankroll)
            if bet < MIN_BET:
                break
            picks = sorted(rnd.sample(range(1, 41), pick_count))
            hits = len(set(picks) & set(drawn))
            payout = _q(bet * Decimal(str(table[hits])))
            profit += payout - bet
            staked += bet
            bankroll = _q(bankroll - bet + payout)
            if pm is not None:
                pm.observe(payout - bet)
            if kind == "martingale":
                mart_step = mart_step + 1 if payout == 0 else 0
            peak = max(peak, profit)
            max_dd = max(max_dd, peak - profit)
            if bankroll < MIN_BET:
                ruins += 1
                break
        profits.append(profit)
        rois.append(float(profit / staked) if staked > 0 else 0.0)
        dds.append(max_dd)

    count = len(profits)
    green = sum(1 for p in profits if p > 0) / count if count else 0.0
    return {
        "kind": kind,
        "sessions": count,
        "mean_roi_pct": (sum(rois) / count * 100) if count else 0.0,
        "green_pct": green,
        "ruin_pct": ruins / count if count else 0.0,
        "mean_profit": str(sum(profits, Decimal(0)) / count) if count else "0",
        "median_profit": str(sorted(profits)[count // 2]) if count else "0",
        "worst_profit": str(min(profits)) if profits else "0",
        "best_profit": str(max(profits)) if profits else "0",
        "mean_max_drawdown": str(sum(dds, Decimal(0)) / count) if count else "0",
    }


def run_lab(payload: dict) -> dict:
    from ..research.strategy_grid import run_strategy_grid

    sessions = min(max(int(payload.get("sessions", 5000)), 10), 20000)
    rounds = min(max(int(payload.get("rounds", 176)), 20), 2000)
    kinds = tuple(
        k for k in payload.get(
            "kinds",
            ["flat-min", "flat-001", "fractional", "adaptive", "probe-window", "capped-recovery", "phase", "martingale"],
        )
        if k in {
            "flat-min",
            "flat-001",
            "fractional",
            "adaptive",
            "probe-window",
            "capped-recovery",
            "phase",
            "martingale",
        }
    )
    if not kinds:
        kinds = ("flat-min",)
    risk = str(payload.get("risk", "medium"))
    pick_count = min(max(int(payload.get("pick_count", 10)), 1), 10)
    pace_seconds = float(payload.get("pace_seconds", 3.5) or 3.5)
    selection_modes = tuple(
        x for x in payload.get("selection_modes", ["random"]) if x in {
            "random",
            "block-random",
            "fixed-pattern",
            "hot",
            "cold",
            "avoid-cold-zone",
            "balanced-random",
        }
    ) or ("random",)
    report = run_strategy_grid(
        sessions=sessions,
        rounds_per_session=rounds,
        risk=risk,
        pick_count=pick_count,
        bankroll=str(payload.get("bankroll", "10") or "10"),
        seed=str(payload.get("seed", "keno-grid-2026-09-11")),
        selection_seed=int(payload.get("selection_seed", 9911) or 9911),
        pace_seconds=pace_seconds,
        candidates=kinds,
        selection_modes=selection_modes,
        stop_win=payload.get("stop_win"),
        stop_loss=payload.get("stop_loss"),
        max_drawdown=payload.get("max_drawdown"),
        out_prefix=paths.report_prefix("strategy_grid_web"),
    )
    return {
        "sessions": sessions,
        "rounds": rounds,
        "risk": risk,
        "pick_count": pick_count,
        "pace_seconds": pace_seconds,
        "selection_modes": list(selection_modes),
        "rows": report["rows"],
        "note": report["note"],
    }


def start_lab_job(payload: dict) -> str:
    """Start a large lab run without blocking the HTTP request."""
    job_id = uuid.uuid4().hex[:12]
    cancel_event = threading.Event()
    with LAB_JOBS_LOCK:
        LAB_JOBS[job_id] = {
            "status": "running",
            "completed": 0,
            "total": int(payload.get("sessions", 5000) or 5000),
            "result": None,
            "error": None,
            "cancel_event": cancel_event,
        }

    def progress(completed: int, total: int) -> None:
        with LAB_JOBS_LOCK:
            job = LAB_JOBS.get(job_id)
            if job:
                job["completed"] = completed
                job["total"] = total

    def worker() -> None:
        try:
            from ..research.strategy_grid import run_strategy_grid

            sessions = min(max(int(payload.get("sessions", 5000)), 10), 20000)
            rounds = min(max(int(payload.get("rounds", 176)), 20), 2000)
            candidates = tuple(
                k for k in payload.get("candidates", payload.get("kinds", []))
                if isinstance(k, str)
            ) or None
            selection_modes = tuple(
                k for k in payload.get("selection_modes", ["random"])
                if isinstance(k, str)
            ) or ("random",)
            result = run_strategy_grid(
                sessions=sessions,
                rounds_per_session=rounds,
                risk=str(payload.get("risk", "medium")),
                pick_count=min(max(int(payload.get("pick_count", 10)), 1), 10),
                bankroll=str(payload.get("bankroll", "10") or "10"),
                seed=str(payload.get("seed", "keno-grid-2026-09-11")),
                selection_seed=int(payload.get("selection_seed", 9911) or 9911),
                pace_seconds=float(payload.get("pace_seconds", 3.5) or 3.5),
                candidates=candidates,
                selection_modes=selection_modes,
                stop_win=payload.get("stop_win"),
                stop_loss=payload.get("stop_loss"),
                max_drawdown=payload.get("max_drawdown"),
                progress_callback=progress,
                cancel_event=cancel_event,
                out_prefix=paths.report_prefix(f"strategy_grid_job_{job_id}"),
            )
            with LAB_JOBS_LOCK:
                LAB_JOBS[job_id]["status"] = "cancelled" if result["cancelled"] else "completed"
                LAB_JOBS[job_id]["result"] = result
        except Exception as exc:  # noqa: BLE001
            with LAB_JOBS_LOCK:
                LAB_JOBS[job_id]["status"] = "failed"
                LAB_JOBS[job_id]["error"] = f"{type(exc).__name__}: {exc}"

    threading.Thread(target=worker, name=f"keno-bot-{job_id}", daemon=True).start()
    return job_id


def lab_job_snapshot(job_id: str) -> dict:
    with LAB_JOBS_LOCK:
        job = LAB_JOBS.get(job_id)
        if job is None:
            raise ValueError("unknown lab job")
        return {
            "ok": True,
            "job_id": job_id,
            "status": job["status"],
            "completed": job["completed"],
            "total": job["total"],
            "error": job["error"],
            "result": job["result"],
        }


LIVE_CONNECTING = False
LIVE_CONNECT_LOCK = threading.Lock()


def start_live_connect(wait_login: float = 180.0) -> dict:
    global LIVE_CONNECTING
    with LIVE_CONNECT_LOCK:
        if LIVE_CONNECTING:
            from ..bot.stake_session import public_status

            status = public_status()
            status["connecting"] = True
            return status
        LIVE_CONNECTING = True

    def worker() -> None:
        global LIVE_CONNECTING
        try:
            from ..bot.stake_session import connect_stake

            connect_stake(wait_login=wait_login)
        except Exception as exc:  # noqa: BLE001
            from ..bot.stake_session import mark_error

            mark_error(f"{type(exc).__name__}: {exc}")
        finally:
            with LIVE_CONNECT_LOCK:
                LIVE_CONNECTING = False

    threading.Thread(target=worker, name="stake-live-connect", daemon=True).start()
    from ..bot.stake_session import public_status

    status = public_status()
    status["connecting"] = True
    if status.get("status") == "disconnected":
        status["status"] = "opening"
    return status


def start_auto_job(payload: dict) -> str:
    job_id = "auto-" + uuid.uuid4().hex[:12]
    cancel_event = threading.Event()
    unattended = bool(payload.get("unattended", False))
    hours = max(0.0, float(payload.get("hours", 0) or 0))
    max_sessions = int(payload.get("max_sessions", 0) or 0)
    if unattended and max_sessions <= 0 and hours <= 0:
        hours = 24.0
    rounds = min(max(int(payload.get("rounds", 176) or 176), 1), 10000 if unattended else 2000)
    pace_seconds = max(0.1, float(payload.get("pace_seconds", 3.5) or 3.5))
    realtime = bool(payload.get("realtime", False))
    if hours > 0 and realtime:
        total = max(1, int(hours * 3600 / pace_seconds))
    elif unattended and max_sessions > 1:
        total = max_sessions * rounds
    else:
        total = rounds
    with LAB_JOBS_LOCK:
        LAB_JOBS[job_id] = {
            "status": "running",
            "completed": 0,
            "total": total,
            "result": None,
            "error": None,
            "cancel_event": cancel_event,
            "kind": "auto",
            "last_record": None,
            "unattended": unattended,
        }

    def progress(completed: int, total: int, record: dict) -> None:
        with LAB_JOBS_LOCK:
            job = LAB_JOBS.get(job_id)
            if job:
                job["completed"] = completed
                job["total"] = total
                job["last_record"] = record

    def worker() -> None:
        try:
            result = run_auto(payload, progress_callback=progress, cancel_event=cancel_event)
            with LAB_JOBS_LOCK:
                LAB_JOBS[job_id]["status"] = "cancelled" if result["cancelled"] else "completed"
                LAB_JOBS[job_id]["result"] = result
        except Exception as exc:  # noqa: BLE001
            with LAB_JOBS_LOCK:
                LAB_JOBS[job_id]["status"] = "failed"
                LAB_JOBS[job_id]["error"] = f"{type(exc).__name__}: {exc}"

    threading.Thread(target=worker, name=f"keno-auto-{job_id}", daemon=True).start()
    return job_id


def auto_job_snapshot(job_id: str) -> dict:
    snapshot = lab_job_snapshot(job_id)
    with LAB_JOBS_LOCK:
        job = LAB_JOBS.get(job_id)
        snapshot["last_record"] = job.get("last_record") if job else None
    return snapshot


# ---------------- verification ----------------

def verify_all() -> dict:
    by_hash = {r["server_seed_hash"]: r for r in STATE.revealed}
    checked = passed = 0
    failures = []
    for record in STATE.records:
        entry = by_hash.get(record["server_seed_hash"])
        if entry is None:
            continue
        checked += 1
        rng = FloatGenerator(
            HmacSha256Rng(entry["server_seed"], record["client_seed"], nonce=int(record["nonce"]), cursor=0)
        )
        expected = draw_keno(rng)
        if expected == [int(x) for x in record["drawn"]]:
            passed += 1
        else:
            failures.append(record["id"])
    return {"checked": checked, "passed": passed, "failures": failures[:20]}


# ---------------- randomness self-test ----------------

def run_selftest(draws_n: int = 20000) -> dict:
    draws_n = min(max(int(draws_n), 2000), 100000)

    # A. recheck the sample rounds shipped with the tool, same engine
    real = {"checked": 0, "passed": 0, "source": "data/samples/rounds_sample.jsonl"}
    real_path = paths.sample_rounds()
    if real_path.exists():
        for line in real_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not rec.get("server_seed") or rec.get("client_seed") is None or rec.get("nonce") is None:
                continue
            rng = FloatGenerator(
                HmacSha256Rng(
                    str(rec["server_seed"]),
                    str(rec["client_seed"]),
                    nonce=int(rec["nonce"]),
                    cursor=int(rec.get("cursor") or 0),
                )
            )
            got = draw_keno(rng)
            real["checked"] += 1
            if got == [int(x) for x in rec["numbers"]]:
                real["passed"] += 1

    # B. fresh synthetic draws: uniformity over 40 numbers + hit distribution
    base = secrets.token_hex(8)
    counts = [0] * 41
    hit_counts = [0] * 11
    reference_picks = {3, 6, 14, 16, 22, 25, 29, 36, 37, 38}
    for i in range(draws_n):
        seed = hashlib.sha256(f"{base}:{i}".encode()).hexdigest()
        rng = FloatGenerator(HmacSha256Rng(seed, "selftest", nonce=0, cursor=0))
        drawn = draw_keno(rng)
        for n in drawn:
            counts[n] += 1
        hit_counts[len(reference_picks & set(drawn))] += 1

    p = 0.25  # a fixed number appears in a 10-of-40 draw with prob 1/4
    expected = draws_n * p
    chi2 = sum(((counts[n] - expected) ** 2) / expected for n in range(1, 41))

    total_comb = comb(40, 10)
    probs = [(comb(10, k) * comb(30, 10 - k)) / total_comb for k in range(0, 7)]
    probs[6] = 1.0 - sum(probs[0:6])  # fold the 6+ tail
    buckets = [hit_counts[k] for k in range(0, 6)]
    buckets.append(sum(hit_counts[6:]))
    hit_chi2 = sum(
        ((buckets[i] - draws_n * probs[i]) ** 2) / (draws_n * probs[i])
        for i in range(len(buckets))
    )

    return {
        "draws": draws_n,
        "real_rounds": real,
        "uniformity": {
            "chi2": round(chi2, 2),
            "df": 39,
            "crit_0p05": 54.6,
            "crit_0p01": 66.8,
            "pass": chi2 <= 66.8,
            "verdict": "PASS" if chi2 <= 54.6 else ("NORMAL_RANGE" if chi2 <= 66.8 else "WARN"),
            "freq_min_pct": round(min(counts[1:]) / draws_n * 100, 3),
            "freq_max_pct": round(max(counts[1:]) / draws_n * 100, 3),
            "expected_pct": 25.0,
        },
        "hits": {
            "buckets": [
                {
                    "label": str(i) if i < 6 else "6+",
                    "observed": buckets[i],
                    "expected": round(draws_n * probs[i], 1),
                }
                for i in range(len(buckets))
            ],
            "chi2": round(hit_chi2, 2),
            "df": len(buckets) - 1,
            "crit_0p05": 12.6,
            "crit_0p01": 16.81,
            "pass": hit_chi2 <= 16.81,
            "verdict": "PASS" if hit_chi2 <= 12.6 else ("NORMAL_RANGE" if hit_chi2 <= 16.81 else "WARN"),
        },
        "note": "uniformity: 40 numbers, 25% expected each; hits: reference pick-10 vs hypergeometric; real_rounds: bundled sample rounds recheck.",
    }


# ---------------- HTTP layer ----------------

APP_ID = "keno-bot"


class Handler(BaseHTTPRequestHandler):
    server_version = "KenoBOT/1.0"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._send_json({"error": "not found"}, 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._route_get()
        except Exception as exc:  # noqa: BLE001 — never drop a response
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

    def _route_get(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        if route in ("/", "/index.html"):
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif route in ("/live", "/live.html"):
            self._send_file(STATIC_DIR / "live.html", "text/html; charset=utf-8")
        elif route == "/static/style.css":
            self._send_file(STATIC_DIR / "style.css", "text/css; charset=utf-8")
        elif route == "/static/live.css":
            self._send_file(STATIC_DIR / "live.css", "text/css; charset=utf-8")
        elif route == "/static/app.js":
            self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
        elif route == "/static/live.js":
            self._send_file(STATIC_DIR / "live.js", "application/javascript; charset=utf-8")
        elif route == "/api/app":
            # Handshake used by keno_bot_app: an instance identifies itself, so a
            # different local server on the same port is never mistaken for this one.
            self._send_json({"app": APP_ID, "brand": "Keno BOT", "frozen": paths.is_frozen()})
        elif route == "/api/state":
            with STATE.lock:
                self._send_json(state_snapshot())
        elif route == "/api/history":
            query = parse_qs(parsed.query)
            book = str((query.get("book") or ["paper"])[0])
            scope = str((query.get("scope") or ["session"])[0])
            limit = min(max(int((query.get("limit") or ["80"])[0]), 1), 20000)
            with STATE.lock:
                rows = history(limit, book=book, scope=scope)
            self._send_json({"ok": True, "book": book, "scope": scope, "records": rows})
        elif route == "/api/live/status":
            from ..bot.ledger import current_run, live_session_info, scoped_records, summarize
            from ..bot.stake_live import is_running, live_preview, live_progress
            from ..bot.stake_session import public_status

            status = public_status()
            info = live_session_info()
            session_rows = scoped_records("live", "session")
            session_stats = summarize(session_rows)
            session_stats["duration_sec"] = info["duration_sec"]

            status["connecting"] = LIVE_CONNECTING
            status["running"] = is_running()
            status["session"] = info["level"]
            status["level"] = info["level"]
            status["session_stats"] = session_stats
            status["lifetime_stats"] = summarize(scoped_records("live", "lifetime"))
            status["progress"] = live_progress()
            status["current_run"] = current_run()
            status["stage_table"] = _stage_table(session_rows)
            try:
                from ..bot.stake_live import desk_stats

                status["desk"] = desk_stats(session_rows)
            except Exception as exc:  # noqa: BLE001
                status["desk"] = {"error": f"{type(exc).__name__}: {exc}"}
            status["paytables"] = {risk: picks.get(10, []) for risk, picks in PAYOUTS.items()}
            try:
                bankroll = Decimal(str(status.get("balance") or "0") or "0")
                status["preview"] = live_preview(bankroll=bankroll)
            except Exception as exc:  # noqa: BLE001
                status["preview"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            self._send_json({"ok": True, **status})
        elif route == "/api/live/preview":
            from ..bot.stake_live import live_preview

            self._send_json({"ok": True, **live_preview()})
        elif route == "/api/live/runs":
            from ..bot.ledger import get_live_run, list_live_runs

            query = parse_qs(parsed.query)
            run_id = str((query.get("id") or [""])[0])
            if run_id:
                run = get_live_run(run_id)
                if not run:
                    self._send_json({"ok": False, "error": "找不到这次记录"}, 404)
                    return
                if str((query.get("export") or [""])[0]):
                    payload = {"exported_at": time.strftime("%Y-%m-%d %H:%M:%S"), **run}
                    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
                    fname = f"keno-run-{run_id}.json"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                self._send_json({"ok": True, "run": run})
            else:
                self._send_json({"ok": True, "runs": list_live_runs()})
        elif route == "/api/live/pnl":
            from ..bot.ledger import live_pnl_board

            self._send_json({"ok": True, **live_pnl_board()})
        elif route == "/api/run/status":
            job_id = parse_qs(parsed.query).get("job_id", [""])[0]
            self._send_json(auto_job_snapshot(job_id) if job_id.startswith("auto-") else lab_job_snapshot(job_id))
        elif route == "/api/export":
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            body = (DATA_DIR / "records.jsonl").read_bytes() if (DATA_DIR / "records.jsonl").exists() else b""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=keno_lab_records.jsonl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path.rstrip("/") or "/"
        payload = self._read_json()
        try:
            if route == "/api/bet":
                picks = [int(x) for x in payload.get("picks", [])]
                picks = sorted({p for p in picks if 1 <= p <= 40})
                if not picks:
                    self._send_json({"ok": False, "error": "picks required (1-40)"}, 400)
                    return
                risk = str(payload.get("risk", "low"))
                try:
                    amount = Decimal(str(payload.get("amount", "0.0001")))
                except Exception as exc:
                    raise ValueError("投注额格式错误") from exc
                with STATE.lock:
                    record = STATE.settle(picks, risk, amount, stage=str(payload.get("stage", "手动")))
                    STATE.save()
                self._send_json({"ok": True, "record": record, "state": state_snapshot()})
            elif route == "/api/auto":
                if payload.get("async"):
                    job_id = start_auto_job(payload)
                    self._send_json({"ok": True, "job_id": job_id})
                else:
                    result = run_auto(payload)
                    self._send_json({"ok": True, "summary": result, "state": state_snapshot()})
            elif route == "/api/live/connect":
                wait_login = float(payload.get("wait_login") or 180)
                status = start_live_connect(wait_login=wait_login)
                self._send_json({"ok": True, **status})
            elif route == "/api/live/refresh":
                from ..bot.stake_session import refresh_stake

                status = refresh_stake()
                self._send_json({"ok": True, **status})
            elif route == "/api/live/preview":
                from ..bot.stake_live import live_preview

                bankroll = None
                if payload.get("balance") not in (None, ""):
                    bankroll = Decimal(str(payload.get("balance")))
                self._send_json({"ok": True, **live_preview(payload, bankroll=bankroll)})
            elif route == "/api/live/run":
                from ..bot.stake_live import run_stake_live

                if not payload.get("live_bets"):
                    self._send_json({"ok": False, "error": "实盘下注需要 live_bets=true"}, 400)
                    return
                if payload.get("async"):
                    from ..bot.stake_live import plan_live_run, run_stake_live

                    job_id = "live-" + uuid.uuid4().hex[:12]
                    cancel_event = threading.Event()
                    planned = plan_live_run(payload)

                    def worker() -> None:
                        try:
                            result = run_stake_live(payload)
                            with LAB_JOBS_LOCK:
                                LAB_JOBS[job_id]["status"] = "cancelled" if result.get("stop_reason") == "cancelled" else "completed"
                                LAB_JOBS[job_id]["result"] = result
                        except Exception as exc:  # noqa: BLE001
                            with LAB_JOBS_LOCK:
                                LAB_JOBS[job_id]["status"] = "failed"
                                LAB_JOBS[job_id]["error"] = f"{type(exc).__name__}: {exc}"

                    with LAB_JOBS_LOCK:
                        LAB_JOBS[job_id] = {
                            "status": "running",
                            "completed": 0,
                            "total": planned["target"],
                            "result": None,
                            "error": None,
                            "cancel_event": cancel_event,
                            "kind": "live",
                        }
                    threading.Thread(target=worker, name=f"keno-live-{job_id}", daemon=True).start()
                    self._send_json({"ok": True, "job_id": job_id})
                else:
                    result = run_stake_live(payload)
                    self._send_json(result)
            elif route == "/api/live/stop":
                from ..bot.stake_live import request_stop

                request_stop()
                self._send_json({"ok": True})
            elif route == "/api/live/session/new":
                from ..bot.ledger import live_level, new_live_session

                level = new_live_session(
                    new_batch=bool(payload.get("new_batch")),
                    new_conversation=bool(payload.get("new_conversation")),
                )
                self._send_json({"ok": True, "session": level or live_level()})
            elif route == "/api/live/reset":
                from ..bot.stake_live import reset_combo_run

                level = reset_combo_run(name=payload.get("name"), settings=payload.get("settings"))
                self._send_json({"ok": True, "session": level})
            elif route == "/api/live/runs/rename":
                from ..bot.ledger import rename_live_run, update_current_run_settings

                run_id = str(payload.get("id") or "")
                name = str(payload.get("name") or "")
                if run_id:
                    run = rename_live_run(run_id, name)
                else:
                    run = update_current_run_settings(name=name)
                if not run:
                    self._send_json({"ok": False, "error": "找不到这次记录"}, 404)
                    return
                self._send_json({"ok": True, "run": run})
            elif route == "/api/live/runs/delete":
                from ..bot.ledger import delete_live_run

                run_id = str(payload.get("id") or "")
                if not run_id:
                    self._send_json({"ok": False, "error": "缺少 id"}, 400)
                    return
                ok = delete_live_run(run_id)
                self._send_json({"ok": bool(ok)})
            elif route == "/api/auto/start":
                job_id = start_auto_job(payload)
                self._send_json({"ok": True, "job_id": job_id})
            elif route == "/api/lab":
                if payload.get("async"):
                    job_id = start_lab_job(payload)
                    self._send_json({"ok": True, "job_id": job_id})
                else:
                    result = run_lab(payload)
                    self._send_json({"ok": True, **result})
            elif route == "/api/run/cancel":
                job_id = str(payload.get("job_id", ""))
                with LAB_JOBS_LOCK:
                    job = LAB_JOBS.get(job_id)
                    if job is None:
                        raise ValueError("unknown lab job")
                    job["cancel_event"].set()
                self._send_json({"ok": True, "job_id": job_id})
            elif route == "/api/rotate":
                with STATE.lock:
                    revealed = STATE.rotate(payload.get("client_seed"))
                self._send_json({"ok": True, "revealed": revealed, "state": state_snapshot()})
            elif route == "/api/autorotate":
                with STATE.lock:
                    STATE.auto_rotate = {
                        "rounds": max(0, int(payload.get("rounds", 0) or 0)),
                        "minutes": max(0, int(payload.get("minutes", 0) or 0)),
                    }
                    STATE.save()
                self._send_json({"ok": True, "state": state_snapshot()})
            elif route == "/api/selftest":
                result = run_selftest(int(payload.get("draws", 20000) or 20000))
                self._send_json({"ok": True, **result})
            elif route == "/api/session/new":
                with STATE.lock:
                    STATE.new_session(bool(payload.get("new_batch", False)))
                self._send_json({"ok": True, "state": state_snapshot()})
            elif route == "/api/verify":
                with STATE.lock:
                    result = verify_all()
                self._send_json({"ok": True, **result})
            elif route == "/api/calc":
                server_seed = str(payload.get("server_seed", "")).strip()
                client_seed = str(payload.get("client_seed", "")).strip()
                try:
                    nonce = int(payload.get("nonce", 1))
                except Exception as exc:
                    raise ValueError("nonce 必须是整数") from exc
                if not server_seed or not client_seed:
                    raise ValueError("server seed 与 client seed 必填")
                rng = FloatGenerator(HmacSha256Rng(server_seed, client_seed, nonce=nonce, cursor=0))
                numbers1 = draw_keno(rng)
                self._send_json({
                    "ok": True,
                    "nonce": nonce,
                    "numbers0": [n - 1 for n in numbers1],
                    "numbers1": numbers1,
                })
            elif route == "/api/reset":
                with STATE.lock:
                    STATE.balance = Decimal(str(payload.get("balance", "100.00")))
                    STATE.save()
                self._send_json({"ok": True, "state": state_snapshot()})
            else:
                self._send_json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001 — surface any input error as JSON
            message = str(exc) if isinstance(exc, (ValueError, KeyError)) else f"{type(exc).__name__}: {exc}"
            self._send_json({"ok": False, "error": message}, 400)


class LabServer(ThreadingHTTPServer):
    allow_reuse_address = True


FALLBACK_PORTS = (8000, 8001, 8002, 8765, 8787, 18765)


def port_has_listener(host: str, port: int, timeout: float = 0.4) -> bool:
    """True when something already accepts TCP connections on host:port.

    Windows lets SO_REUSEADDR bind an address another process is already serving,
    which would silently take over (or split) that port — so a candidate is only
    used when nothing answers there.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)
        try:
            return probe.connect_ex((host, port)) == 0
        except OSError:
            return True


def bind_http_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    """Bind Keno BOT. If the requested port is taken, try FALLBACK_PORTS."""
    if port == 0:
        return LabServer((host, 0), Handler)
    candidates: list[int] = [port]
    for extra in FALLBACK_PORTS:
        if extra not in candidates:
            candidates.append(extra)
    seen: list[int] = []
    last_err: OSError | None = None
    for candidate in candidates:
        if port_has_listener(host, candidate):
            seen.append(candidate)
            last_err = OSError(f"{host}:{candidate} 已被别的进程监听")
            continue
        try:
            server = LabServer((host, candidate), Handler)
        except OSError as exc:
            seen.append(candidate)
            last_err = exc
            continue
        if candidate != port:
            print(f"端口 {port} 被占用，改用 {candidate}。")
        return server
    raise OSError(f"端口都被占了（试过 {seen}）：{last_err}") from last_err


def main(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = bind_http_server(host, port)
    bound = server.server_address[1]
    url = f"http://{host}:{bound}"
    print(f"Keno BOT 已启动（本地模拟，无真钱）：{url}")
    print(f"实盘台：{url}/live")
    print("按 Ctrl+C 停止。不要关这个窗口。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="keno-bot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    main(args.host, args.port)
