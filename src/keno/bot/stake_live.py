# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

"""Place real Stake keno bets through the logged-in Chrome tab.

Default is connect-only. Real wagers require live_bets=True.
The live desk shares money + selection state with the preview so the
board the operator sees is the next real ticket.
"""

import copy
import threading
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from random import Random

from .. import paths
from ..bot.combo_v2 import ComboV2, analyze_numbers, current_real_loss_streak, dashboard, recommend, soul_snapshot, zone_rows
from ..bot.money import (
    AdaptiveFractionalManager,
    CappedRecoveryManager,
    FlatMoneyManager,
    FractionalMoneyManager,
    PhaseRecoveryManager,
    ProbeWindowManager,
)
from ..bot.phases import PhaseMachine
from ..data.schema import RoundRecord
from ..strategies.pattern import PatternStrategy
from ..strategies.selection import SelectionStrategy
from ..research.live_lab import shadow_for_draw
from .ledger import (
    append_record,
    current_run,
    live_level,
    mark_play_end,
    mark_play_start,
    new_live_session,
    read_records,
    scoped_records,
    update_current_run_settings,
    viability,
)
from .stake_session import connect_stake, live_status, money_str, place_keno_bet, refresh_stake

WHY_PICK = {
    "pattern": "同组复用：连续几局用同一组号，对齐实盘「探针和实注共用一组」。不改变期望。",
    "random": "每局重新随机，作为无记忆对照。不改变期望。",
    "block-random": "按时间块固定一组，块内不换号。不改变期望。",
    "fixed-pattern": "固定号码 3, 6, 14, 16, 22, 25, 29, 36, 37, 38。不改变期望。",
    "hot": "最近开奖里出现最多的号（实验，不改变期望）。",
    "cold": "最近开奖里出现最少的号（实验，不改变期望）。",
    "avoid-cold-zone": "避开最近最冷的区域（实验，不改变期望）。",
    "balanced-random": "四个十号区各抽一些，尽量铺开。不改变期望。",
}
WHY_MONEY = {
    "combo": "Combo V2：自定义金额档，输了升档、赢了回 1 档。赢了留号。侦察开着时先打 0.0001。",
    "phase": "阶段机：探针 0.0001 → 恢复 0.01 → 取利 0.10 → 收尾 0.60。",
    "flat": "每局固定基础注。",
    "probe": "先用最低注观察一段时间，再抬到基础注，然后冷却。",
    "fractional": "按余额很小比例下注，亏了自动变小。",
    "adaptive": "连亏或波动大时把比例再压低。",
    "capped": "有限恢复：输了按 1.25 倍抬，最多 4 步就回到基础注。",
    "martingale": "输了加倍。",
}
STOP_ZH = {
    "rounds completed": "本轮局数已跑完",
    "cancelled": "已手动停止",
    "stop-loss hit": "触及止损",
    "stop-win hit": "触及止盈",
    "daily-take-profit": "全天止盈已到，今晚停，把绿留下",
    "hours completed": "无人值守时长已到",
    "Stake 未确认入账": "Stake 未确认入账",
    "reconnect failed": "分段后重连失败，已停",
    "max-streak": "触及最大连败",
    "session-rounds": "本轮局数已跑完",
    "next-bet-exceeds-stop": "下一注大于库存，已收口",
    "max-level-win": "第4档赢了，已收口",
    "max-level-loss": "第4档输了，当天不再打",
    "session-fat-hit": "肥尾倍率到了，已收口",
    "session-take-profit": "本轮止盈，绿已锁",
    "session-round-cap": "本轮局数到了，已收口",
    "session-stop-loss": "本轮止损，整段停",
    "daily-stop-loss": "当天止损已到，歇到明天",
}

# 无限跑只在「收了绿」之后新开一轮。止损 / 四连败 / 第4档输 = 整段停，避免 10u 被一轮轮止损削完。
SESSION_ROTATE_REASONS = {
    "stop-win hit",
    "session-rounds",
    "session-take-profit",
    "session-round-cap",
    "session-fat-hit",
    "max-level-win",
}

MIN_BET = Decimal("0.0001")
MAX_SLICE_ROUNDS = 200
MAX_TOTAL_ROUNDS = 40000
DEFAULT_SLICE_ROUNDS = 100
DEFAULT_SLICE_COOLDOWN = 8.0
DEFAULT_MAX_BET = Decimal("0.01")
QUANT = Decimal("0.00000001")
MAX_LIVE_ROUNDS = MAX_TOTAL_ROUNDS
_CANCEL = threading.Event()
_RUN_LOCK = threading.Lock()
_RUNNING = False
_PROGRESS: dict = {
    "completed": 0,
    "total": 0,
    "last": None,
    "stop_reason": None,
}


def _q(value: Decimal) -> Decimal:
    return value.quantize(QUANT)


def next_bet_blows_stop(
    session_profit: Decimal,
    amount: Decimal,
    stop_loss: Decimal | None,
    level: int | None = None,
    max_level: int | None = None,
    bankroll: Decimal | None = None,
) -> bool:
    """回本枪必须打。只在下一注大于库存、根本下不出去时才拦。"""
    if bankroll is not None and amount > bankroll:
        return True
    return False


def _engine_key(kind, pick_mode, base_bet, max_bet, pick_count, force_min, block_rounds, extra="") -> tuple:
    return (
        str(kind),
        str(pick_mode),
        format(_q(Decimal(str(base_bet))), "f"),
        format(_q(Decimal(str(max_bet))), "f"),
        int(pick_count),
        bool(force_min),
        int(block_rounds),
        str(extra or ""),
    )


def request_stop() -> None:
    _CANCEL.set()


def is_running() -> bool:
    return _RUNNING


def live_progress() -> dict:
    return dict(_PROGRESS)


def plan_live_run(payload: dict) -> dict:
    """Split a long run into slices so 1000–3000 rounds can idle 24h without one fragile job."""
    hours = max(0.0, float(payload.get("hours") or 0))
    pace = max(3.0, float(payload.get("pace_seconds") or 3.0))
    slice_rounds = min(MAX_SLICE_ROUNDS, max(1, int(payload.get("slice_rounds") or DEFAULT_SLICE_ROUNDS)))
    cooldown = max(3.0, float(payload.get("slice_cooldown") or DEFAULT_SLICE_COOLDOWN))
    requested = int(payload.get("rounds") or 0)
    loop_sessions = bool(payload.get("loop_sessions"))
    session_cap = int(payload.get("session_rounds") or 0)
    if loop_sessions:
        if session_cap <= 0:
            session_cap = requested if requested > 0 else 200
        if hours > 0:
            target = max(1, int(hours * 3600 / pace))
        else:
            target = MAX_TOTAL_ROUNDS
        unattended = True
    elif hours > 0:
        from_hours = max(1, int(hours * 3600 / pace))
        target = from_hours if requested <= 0 else min(requested, from_hours)
        session_cap = session_cap or target
        unattended = True
    else:
        target = requested if requested > 0 else 1
        session_cap = session_cap or target
        unattended = bool(payload.get("unattended") or target > slice_rounds)
    target = min(max(target, 1), MAX_TOTAL_ROUNDS)
    if unattended:
        slices = (target + slice_rounds - 1) // slice_rounds
    else:
        slice_rounds = min(target, MAX_SLICE_ROUNDS)
        slices = 1
        cooldown = 0.0
    return {
        "target": target,
        "slice_rounds": slice_rounds,
        "slices": slices,
        "cooldown": cooldown,
        "hours": hours,
        "pace": pace,
        "unattended": unattended,
        "loop_sessions": loop_sessions,
        "session_cap": max(1, session_cap),
    }


def _opt_dec(value, default=None):
    if value in (None, ""):
        return default
    return Decimal(str(value))


def playbook_from_payload(payload: dict) -> dict:
    """Hunt → bank session → maybe grind → hunt. Daily take-profit stops the night."""
    enabled = bool(payload.get("playbook") or payload.get("bank_sessions"))
    return {
        "enabled": enabled,
        "session_stop_win": _opt_dec(payload.get("session_stop_win"), Decimal("0.005") if enabled else None),
        "session_stop_loss": _opt_dec(
            payload.get("session_stop_loss") if payload.get("session_stop_loss") not in (None, "") else payload.get("stop_loss")
        ),
        "session_max_rounds": max(20, int(payload.get("session_max_rounds") or (400 if enabled else 10**9))),
        "stop_on_mult": _opt_dec(payload.get("stop_on_mult"), Decimal("8") if enabled else None),
        "daily_stop_win": _opt_dec(
            payload.get("daily_stop_win") if payload.get("daily_stop_win") not in (None, "") else (
                None if str(payload.get("after_bank") or "") == "stop" else (
                    payload.get("stop_win") if enabled else None
                )
            )
        ),
        "daily_stop_loss": _opt_dec(payload.get("daily_stop_loss")),
        "after_bank": str(payload.get("after_bank") or "grind"),
        "grind_rounds": max(10, int(payload.get("grind_rounds") or 80)),
        "rest_seconds": max(30, int(payload.get("rest_seconds") or 180)),
        "hard_rest_seconds": max(60, int(payload.get("hard_rest_seconds") or 900)),
    }


def session_should_end(
    session_profit: Decimal,
    session_rounds: int,
    last_mult: Decimal,
    book: dict,
) -> str | None:
    if not book.get("enabled"):
        return None
    if book.get("stop_on_mult") is not None and last_mult >= book["stop_on_mult"]:
        return "session-fat-hit"
    if book.get("session_stop_win") is not None and session_profit >= book["session_stop_win"]:
        return "session-take-profit"
    if book.get("session_stop_loss") is not None and session_profit <= -abs(book["session_stop_loss"]):
        return "session-stop-loss"
    if session_rounds >= int(book["session_max_rounds"]):
        return "session-round-cap"
    return None


HARD_SESSION_STOPS = {"session-stop-loss"}
SOUL_BANK_STOPS = {"session-fat-hit", "session-take-profit", "session-round-cap"}


def playbook_hard_stop(end: str | None, book: dict) -> bool:
    """Soul mode: a banked green or session stop-loss ends the whole run."""
    if not end:
        return False
    if end in HARD_SESSION_STOPS:
        return True
    mode = str(book.get("after_bank") or "")
    return mode in {"stop", "rest"} and end in SOUL_BANK_STOPS


GREEN_REST_REASONS = SOUL_BANK_STOPS | {"max-level-win", "stop-win hit", "session-rounds"}
HARD_REST_REASONS = {"stop-loss hit", "max-streak", "session-stop-loss"}
DAY_REST_REASONS = {"daily-take-profit", "daily-stop-loss", "max-level-loss"}
HOST_RESUME_REASONS = GREEN_REST_REASONS | HARD_REST_REASONS | DAY_REST_REASONS


def seconds_until_next_local_day() -> float:
    now = datetime.now()
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return max(60.0, (nxt - now).total_seconds())


def rest_seconds_for(reason: str, book: dict) -> float:
    if reason in DAY_REST_REASONS:
        return seconds_until_next_local_day()
    if reason in HARD_REST_REASONS:
        return float(book.get("hard_rest_seconds") or 900)
    return float(book.get("rest_seconds") or 180)


def _interruptible_sleep(seconds: float) -> bool:
    deadline = time.time() + max(0.0, seconds)
    while time.time() < deadline:
        if _CANCEL.is_set():
            return False
        time.sleep(min(0.5, deadline - time.time()))
    return True


def _host_rest(seconds: float, reason: str) -> bool:
    """Sleep while remaining interruptible; UI reads rest_left / rest_why."""
    total = max(0.0, float(seconds))
    deadline = time.time() + total
    why = _zh_stop(reason)
    _PROGRESS["resting"] = True
    _PROGRESS["rest_why"] = why
    _PROGRESS["rest_left"] = int(total)
    try:
        while time.time() < deadline:
            if _CANCEL.is_set():
                return False
            left = deadline - time.time()
            _PROGRESS["rest_left"] = max(0, int(left))
            time.sleep(min(1.0, left))
        return True
    finally:
        _PROGRESS["resting"] = False
        _PROGRESS["rest_left"] = 0


def _build_money(kind: str, base_bet: Decimal):
    if kind == "phase":
        return PhaseMachine.from_yaml(paths.config_file("bot_phase.yaml"))
    if kind == "probe":
        return ProbeWindowManager(
            probe_bet=MIN_BET,
            active_bet=max(base_bet, MIN_BET),
            probe_rounds=30,
            active_rounds=60,
            cooldown_rounds=30,
        )
    if kind == "fractional":
        return FractionalMoneyManager(
            fraction=Decimal("0.0005"),
            min_bet=MIN_BET,
            max_fraction=Decimal("0.002"),
        )
    if kind == "adaptive":
        return AdaptiveFractionalManager(
            fraction=Decimal("0.0005"),
            cautious_fraction=Decimal("0.0001"),
            min_bet=MIN_BET,
            max_fraction=Decimal("0.002"),
        )
    if kind == "capped":
        return CappedRecoveryManager(base_bet=base_bet, multiplier=Decimal("1.25"), max_steps=4)
    if kind == "martingale":
        return PhaseRecoveryManager(
            base_bet=base_bet,
            recovery_multiplier=Decimal("2"),
            max_recovery_steps=8,
        )
    return FlatMoneyManager(base_bet)


def _build_picks(mode: str, block_rounds: int = 257):
    if mode == "pattern":
        return PatternStrategy(reroll_every=4)
    if mode in ("random", "block-random", "fixed-pattern", "hot", "cold", "avoid-cold-zone", "balanced-random"):
        return SelectionStrategy(mode, block_rounds=block_rounds)
    return PatternStrategy(reroll_every=4)


def _money_label(kind: str, money) -> str:
    if kind == "combo" and hasattr(money, "display_stage"):
        return money.display_stage
    if kind == "phase" and hasattr(money, "display_stage"):
        return money.display_stage
    if kind == "flat":
        return "平注"
    if kind == "fractional":
        return "余额分数"
    if kind == "adaptive":
        return "自适应"
    if kind == "capped":
        return f"有限恢复 第{getattr(money, 'step', 0)}步"
    if kind == "martingale":
        step = getattr(money, "recovery_step", 0)
        return "马丁" if not step else f"马丁 第{step}步"
    if kind == "probe":
        phase = str(getattr(money, "phase", "probe"))
        return {"probe": "探针窗口", "active-window": "小额窗口", "cooldown": "冷却"}.get(phase, phase)
    return str(getattr(money, "phase", kind))


def _combo_extra(payload: dict) -> str:
    def nv(key, default):
        value = payload.get(key)
        return default if value in (None, "") else value

    return "|".join(
        [
            str(payload.get("custom_amounts") or ""),
            str(payload.get("start_level") or "1"),
            str(payload.get("max_level") or ""),
            str(bool(payload.get("reset_on_max_loss"))),
            str(bool(payload.get("recon_on"))),
            str(payload.get("keep_on_win", True)),
            str(nv("recon_n_loss", "2")),
            str(nv("recon_n_win", "0")),
            str(nv("recon_real_n", "4")),
            str(bool(payload.get("recon_return_on_real_win"))),
            str(bool(payload.get("recon_abort_on_real_loss"))),
            str(payload.get("recon_numbers") or "fixed"),
        ]
    )


def _zh_stop(reason: str) -> str:
    if reason in STOP_ZH:
        return STOP_ZH[reason]
    if reason.startswith("bet failed"):
        return "下单失败：" + reason.split(":", 1)[-1].strip()
    return reason


class LiveEngine:
    """Shared money + selection state so the preview matches the next real bet."""

    def __init__(self, payload: dict) -> None:
        self.payload = dict(payload)
        self.kind = str(payload.get("money") or payload.get("kind") or "combo")
        self.pick_mode = str(payload.get("picks") or "combo")
        self.base_bet = max(MIN_BET, Decimal(str(payload.get("base_bet") or "0.0001")))
        self.max_bet = max(MIN_BET, Decimal(str(payload.get("max_bet") or DEFAULT_MAX_BET)))
        self.pick_count = min(max(int(payload.get("pick_count") or 10), 1), 10)
        self.force_min = bool(payload.get("probe_only") or payload.get("force_min"))
        self.block_rounds = max(1, int(payload.get("block_rounds") or 257))
        self.combo = ComboV2.from_payload(payload) if self.kind == "combo" else None
        if self.combo:
            top = max(self.combo.amounts)
            if self.max_bet < top and payload.get("max_bet") in (None, ""):
                self.max_bet = top
            self.money = self.combo
            self.selection = None
        else:
            self.money = _build_money(self.kind, self.base_bet)
            self.selection = _build_picks(self.pick_mode, self.block_rounds)
        self.rng = Random(int(payload.get("rng_seed") or 7))
        self.history: list[RoundRecord] = []
        self.draws: list[list[int]] = []
        self.last_win: bool | None = None
        self.manual_picks = [int(x) for x in (payload.get("manual_picks") or []) if str(x).isdigit()]
        self.key = _engine_key(
            self.kind,
            self.pick_mode,
            self.base_bet,
            self.max_bet,
            self.pick_count,
            self.force_min,
            self.block_rounds,
            _combo_extra(payload) if self.combo else "",
        )

    def reset_run(self) -> None:
        if self.combo:
            self.combo.reset_run()
            self.combo.picks = None
        self.last_win = None

    def analysis(self) -> dict:
        return analyze_numbers(self.draws)

    def _apply_caps(self, raw: Decimal) -> tuple[Decimal, str | None]:
        note = None
        amount = max(MIN_BET, _q(raw))
        if self.force_min:
            if amount != MIN_BET:
                note = f"已打开强制最低探针，策略想下 {money_str(amount)}，实际下一注是 {money_str(MIN_BET)}"
            else:
                note = "已打开强制最低探针，下一注固定 0.0001"
            amount = MIN_BET
        elif self.kind != "combo" and amount > self.max_bet:
            note = f"策略想下 {money_str(amount)}，被单注上限压成 {money_str(self.max_bet)}"
            amount = self.max_bet
        return max(MIN_BET, _q(amount)), note

    def preview(self, bankroll: Decimal) -> dict:
        raw = self.money.next_bet(bankroll if bankroll > 0 else Decimal("10"))
        amount, cap_note = self._apply_caps(raw)
        rng = Random()
        rng.setstate(self.rng.getstate())
        if self.combo:
            picks = self.combo.choose_picks(
                self.draws,
                self.pick_count,
                rng,
                self.last_win,
                self.manual_picks if len(self.manual_picks) == self.pick_count else None,
            )
            money_label = self.combo.display_stage
            picks_why = "赢了留号，输了按 100 局热力/空窗/热号重选。" if self.combo.keep_on_win else "每局按热力重选。"
            level = self.combo.level
            recon = self.combo.in_recon
        else:
            clone = copy.deepcopy(self.selection)
            picks = list(clone.predict(self.history, self.pick_count, rng))
            money_label = _money_label(self.kind, self.money)
            picks_why = WHY_PICK.get(self.pick_mode, "")
            level = 1
            recon = False
        why_money = WHY_MONEY.get(self.kind, "")
        if cap_note:
            why_money = why_money + " " + cap_note
        heat = self.analysis()
        recs = []
        if heat:
            for n in recommend(heat, min(10, self.pick_count), Random(1)):
                cell = heat.get(n) or {}
                recs.append({"n": n, "freq": cell.get("freq"), "tags": cell.get("tags") or []})
        return {
            "amount": money_str(amount),
            "raw_amount": money_str(_q(raw)),
            "picks": picks,
            "pick_count": self.pick_count,
            "money": self.kind,
            "money_label": money_label,
            "money_why": why_money,
            "picks_mode": self.pick_mode,
            "picks_why": picks_why,
            "force_min": self.force_min,
            "base_bet": money_str(self.base_bet),
            "max_bet": money_str(self.max_bet),
            "cap_note": cap_note,
            "level": level,
            "recon": recon,
            "recon_min": format(self.combo.recon_min, "f") if self.combo else "0.0001",
            "ladder": [format(a, "f") for a in self.combo.amounts] if self.combo else [],
            "max_level": self.combo.max_level if self.combo else 1,
            "heatmap": {str(k): v for k, v in heat.items()},
            "recommended": recs,
            "zones": zone_rows(heat) if heat else [],
        }

    def commit(self, profit: Decimal, drawn: list[int], selected: list[int] | None = None) -> None:
        """Advance selection + money only after Stake confirms the ticket."""
        win = profit >= 0
        if self.combo:
            if selected:
                self.combo.picks = sorted(int(x) for x in selected)
            hits = None
            if selected and drawn:
                hits = len(set(int(x) for x in selected) & set(int(x) for x in drawn))
            self.combo.observe(profit, hits=hits)
            if not (win and self.combo.keep_on_win):
                self.combo.picks = None
            self.manual_picks = []
        else:
            self.selection.predict(self.history, self.pick_count, self.rng)
            self.money.observe(profit)
        self.last_win = win
        drawn_list = list(drawn or [])
        self.draws.append(drawn_list)
        if len(self.draws) > 400:
            self.draws = self.draws[-200:]
        self.history.append(
            RoundRecord(
                round_id=str(uuid.uuid4()),
                timestamp=datetime.now(),
                numbers=drawn_list,
                source="live",
            )
        )
        if len(self.history) > 400:
            self.history = self.history[-200:]


_ENGINE: LiveEngine | None = None


def reset_live_engine() -> None:
    global _ENGINE
    _ENGINE = None


def ensure_engine(payload: dict | None = None) -> LiveEngine:
    global _ENGINE
    payload = payload or {}
    if not payload and _ENGINE is not None:
        return _ENGINE

    def pick(key: str, attr: str, default):
        value = payload.get(key)
        if value not in (None, ""):
            return value
        if key == "money" and payload.get("kind") not in (None, ""):
            return payload.get("kind")
        if _ENGINE is not None:
            return getattr(_ENGINE, attr)
        return default

    merged = {
        "money": pick("money", "kind", "combo"),
        "picks": pick("picks", "pick_mode", "combo"),
        "base_bet": pick("base_bet", "base_bet", "0.0001"),
        "max_bet": pick("max_bet", "max_bet", str(DEFAULT_MAX_BET)),
        "pick_count": pick("pick_count", "pick_count", 10),
        "probe_only": pick("force_min", "force_min", False),
        "force_min": pick("force_min", "force_min", False),
        "block_rounds": pick("block_rounds", "block_rounds", 257),
        "rng_seed": payload.get("rng_seed") or 7,
        "custom_amounts": payload.get("custom_amounts") or getattr(_ENGINE, "payload", {}).get("custom_amounts") if _ENGINE else payload.get("custom_amounts"),
        "start_level": payload.get("start_level"),
        "max_level": payload.get("max_level"),
        "reset_on_max_loss": payload.get("reset_on_max_loss"),
        "recon_on": payload.get("recon_on"),
        "recon_n_loss": payload.get("recon_n_loss"),
        "recon_n_win": payload.get("recon_n_win"),
        "recon_real_n": payload.get("recon_real_n"),
        "recon_min": payload.get("recon_min"),
        "recon_max": payload.get("recon_max"),
        "recon_numbers": payload.get("recon_numbers"),
        "recon_return_on_real_win": payload.get("recon_return_on_real_win"),
        "recon_abort_on_real_loss": payload.get("recon_abort_on_real_loss"),
        "keep_on_win": payload.get("keep_on_win", True),
        "manual_picks": payload.get("manual_picks") or [],
    }
    if payload.get("probe_only"):
        merged["force_min"] = True
        merged["probe_only"] = True
    key = _engine_key(
        merged["money"] or "combo",
        merged["picks"] or "combo",
        max(MIN_BET, Decimal(str(merged["base_bet"]))),
        max(MIN_BET, Decimal(str(merged["max_bet"]))),
        int(merged["pick_count"] or 10),
        bool(merged["force_min"]),
        int(merged["block_rounds"] or 257),
        _combo_extra(merged),
    )
    if _ENGINE is None or _ENGINE.key != key:
        _ENGINE = LiveEngine(merged)
        rows = read_records("live")
        _ENGINE.draws = [list(r.get("drawn") or []) for r in rows if r.get("drawn")][-100:]
        _ENGINE.history = [
            RoundRecord(round_id=str(i), timestamp=datetime.now(), numbers=d, source="live")
            for i, d in enumerate(_ENGINE.draws)
        ]
    elif payload.get("manual_picks"):
        _ENGINE.manual_picks = [int(x) for x in payload.get("manual_picks") or [] if str(x).isdigit()]
    return _ENGINE


def reset_combo_run(name: str | None = None, settings: dict | None = None, keep_picks: bool = False):
    level = new_live_session(name=name, settings=settings)
    if _ENGINE is not None:
        kept = list(_ENGINE.combo.picks) if keep_picks and _ENGINE.combo and _ENGINE.combo.picks else None
        _ENGINE.reset_run()
        all_rows = read_records("live")
        _ENGINE.draws = [list(r.get("drawn") or []) for r in all_rows if r.get("drawn")][-100:]
        _ENGINE.history = [
            RoundRecord(round_id=str(i), timestamp=datetime.now(), numbers=d, source="live")
            for i, d in enumerate(_ENGINE.draws)
        ]
        _ENGINE.last_win = None
        if keep_picks and _ENGINE.combo is not None and kept:
            _ENGINE.combo.picks = kept
    return level


def desk_stats(records: list | None = None) -> dict:
    rows = list(records if records is not None else scoped_records("live", "session"))
    dash = dashboard(rows)
    engine = _ENGINE
    draws = engine.draws if engine else [list(r.get("drawn") or []) for r in rows if r.get("drawn")]
    heat = analyze_numbers(draws)
    rng = Random(1)
    recs = []
    if heat:
        for n in recommend(heat, 10, rng):
            cell = heat[n]
            recs.append({"n": n, "freq": cell["freq"], "tags": cell["tags"]})
    return {
        "dashboard": dash,
        "heatmap": {str(k): v for k, v in heat.items()},
        "recommended": recs,
        "zones": zone_rows(heat) if heat else [],
        "level": engine.combo.level if engine and engine.combo else 1,
        "recon": bool(engine.combo.in_recon) if engine and engine.combo else False,
        "level_label": (
            "侦察"
            if engine and engine.combo and engine.combo.recon_on and engine.combo.in_recon
            else str(engine.combo.level if engine and engine.combo else 1)
        ),
    }


def live_preview(payload: dict | None = None, bankroll: Decimal | None = None) -> dict:
    engine = ensure_engine(payload)
    status = live_status()
    if bankroll is None:
        bankroll = Decimal(str(status.get("balance") or "0") or "0")
    plan = engine.preview(bankroll)
    plan["connected"] = status.get("status") == "connected"
    plan["balance"] = status.get("balance")
    plan["ok"] = True
    return plan


def run_stake_live(payload: dict) -> dict:
    if not bool(payload.get("live_bets")):
        raise ValueError("实盘下注需要显式打开 live_bets")
    plan = plan_live_run(payload)
    cdp = str(payload.get("cdp") or "http://127.0.0.1:9222")
    status = live_status()
    if status.get("status") != "connected":
        from .stake_cdp import ensure_cdp

        ensure_cdp(cdp)
        status = connect_stake(cdp=cdp, wait_login=float(payload.get("wait_login") or 180))
    if status.get("status") != "connected":
        return {"ok": False, "status": status, "bets": []}
    verdict = status.get("viability") or viability([])
    if (
        payload.get("pause_on_cluster")
        and verdict.get("recommendation") == "pause"
        and not payload.get("force")
    ):
        return {
            "ok": False,
            "status": status,
            "bets": [],
            "error": verdict.get("reason") or "连败簇，先停实盘",
            "viability": verdict,
        }
    risk = str(payload.get("risk") or "low").lower()
    currency = str(payload.get("currency") or status.get("currency") or "usdt").lower()
    stop_loss = abs(Decimal(str(payload.get("stop_loss") or "5000")))
    stop_win = payload.get("stop_win")
    stop_win = abs(Decimal(str(stop_win))) if stop_win not in (None, "") else None
    max_streak = max(1, int(payload.get("max_streak") or 10000))
    stop_on_max_win = payload.get("stop_on_max_win") not in (False, "false", "0", 0, "OFF", "off")
    loop_sessions = bool(plan.get("loop_sessions") or payload.get("loop_sessions"))
    session_cap = int(plan.get("session_cap") or payload.get("session_rounds") or plan["target"])
    book = playbook_from_payload(payload)
    engine = ensure_engine(payload)
    update_current_run_settings(
        settings={
            "risk": str(payload.get("risk") or "low"),
            "pick_count": int(payload.get("pick_count") or 10),
            "custom_amounts": str(payload.get("custom_amounts") or "0.0001"),
            "keep_on_win": payload.get("keep_on_win", True),
            "recon_on": bool(payload.get("recon_on")),
            "max_level": payload.get("max_level"),
            "start_level": payload.get("start_level"),
        },
        name=payload.get("run_name"),
    )
    profit = Decimal("0")
    day_profit = Decimal("0")
    bets: list[dict] = []
    recent_rows: list[dict] = []
    stop_reason = "rounds completed"
    session_id = new_live_session() if payload.get("new_session", True) else live_level()
    session_profit = Decimal("0")
    session_rounds = 0
    session_index = 1
    run_settings = {
        "risk": str(payload.get("risk") or "low"),
        "pick_count": int(payload.get("pick_count") or 10),
        "custom_amounts": str(payload.get("custom_amounts") or "0.0001"),
        "keep_on_win": payload.get("keep_on_win", True),
        "recon_on": bool(payload.get("recon_on")),
        "max_level": payload.get("max_level"),
        "start_level": payload.get("start_level"),
    }
    chapter = "hunt"
    grind_left = 0
    risk = str(payload.get("risk") or "low").lower()
    deadline = time.time() + plan["hours"] * 3600 if plan["hours"] > 0 else None
    global _RUNNING
    _CANCEL.clear()
    with _RUN_LOCK:
        if _RUNNING:
            return {"ok": False, "error": "实盘已在跑", "bets": []}
        _RUNNING = True
    mark_play_start()
    _PROGRESS.update(
        {
            "completed": 0,
            "total": plan["target"],
            "slice": 0,
            "slices": plan["slices"],
            "chapter": "hunt",
            "session_profit": "0",
            "session_index": 1,
            "session_rounds": 0,
            "session_cap": session_cap,
            "loop_sessions": loop_sessions,
            "rotate_reason": None,
            "last": None,
            "stop_reason": None,
        }
    )

    def switch_chapter(name: str) -> None:
        nonlocal engine, risk, chapter, grind_left
        chapter = name
        if name == "grind":
            grind_left = book["grind_rounds"]
            engine = ensure_engine(
                {
                    "money": "flat",
                    "picks": "pattern",
                    "pick_count": 10,
                    "base_bet": "0.0001",
                    "max_bet": "0.0001",
                    "force_min": True,
                }
            )
            risk = "low"
        else:
            grind_left = 0
            engine = ensure_engine(payload)
            risk = str(payload.get("risk") or "low").lower()

    def rotate_now(reason: str) -> None:
        nonlocal session_id, session_profit, session_rounds, session_index, day_profit
        mark_play_end()
        session_index += 1
        session_id = reset_combo_run(
            name=payload.get("run_name"),
            settings=run_settings,
            keep_picks=False,
        )
        session_profit = Decimal("0")
        session_rounds = 0
        if reason in DAY_REST_REASONS:
            day_profit = Decimal("0")
        mark_play_start()
        _PROGRESS.update(
            {
                "session_index": session_index,
                "session_profit": "0",
                "session_rounds": 0,
                "rotate_reason": _zh_stop(reason),
                "stop_reason": None,
            }
        )

    def place_one() -> str | None:
        nonlocal profit, day_profit, status, session_id, session_profit, session_rounds, grind_left, engine, risk, chapter
        bankroll = Decimal(str(status.get("balance") or "1") or "1")
        next_plan = engine.preview(bankroll)
        amount = Decimal(str(next_plan["amount"]))
        picks = list(next_plan["picks"])
        recon = bool(next_plan.get("recon"))
        stage = "侦察" if recon else next_plan["money_label"]
        level = 0 if recon else int(next_plan.get("level") or (engine.combo.level if engine.combo else 1))
        max_lv = engine.combo.max_level if engine.combo else None
        if next_bet_blows_stop(session_profit, amount, stop_loss, level, max_lv, bankroll):
            return "next-bet-exceeds-stop"
        try:
            result = place_keno_bet(
                picks_1_based=picks,
                amount=amount,
                currency=currency,
                risk=risk,
                identifier=str(uuid.uuid4()),
            )
        except Exception as exc:  # noqa: BLE001
            return f"bet failed: {type(exc).__name__}: {exc}"
        if not result.get("confirmed"):
            return "Stake 未确认入账"
        payout = Decimal(str(result.get("payout") or "0"))
        round_profit = _q(payout - amount)
        profit += round_profit
        day_profit += round_profit
        drawn = list(result.get("drawn") or [])
        shadow = shadow_for_draw(drawn, engine.history, engine.pick_count)
        selected = result.get("selected") or picks
        engine.commit(round_profit, drawn, selected)
        row = {
            "n": len(scoped_records("live", "session")) + 1,
            "id": result.get("iid"),
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "session": session_id,
            "stage": stage,
            "level": level,
            "recon": recon,
            "probe": amount == MIN_BET or bool(next_plan.get("force_min")),
            "picks": selected,
            "drawn": drawn,
            "hits": len(set(selected) & set(drawn)),
            "risk": risk,
            "pick_count": engine.pick_count,
            "bet": money_str(amount),
            "multiplier": str(result.get("payout_multiplier") or "0"),
            "payout": money_str(payout),
            "profit": money_str(round_profit),
            "nonce": result.get("nonce"),
            "nonce_before": result.get("nonce_before"),
            "balance_before": result.get("balance_before"),
            "balance_after": result.get("balance_after"),
            "confirmed": True,
            "on_book": result.get("on_book"),
            "currency": currency,
            "iid": result.get("iid"),
            "book": "live",
            "money": engine.kind,
            "picks_mode": engine.pick_mode,
            "money_why": next_plan.get("money_why"),
            "picks_why": next_plan.get("picks_why"),
            "shadow": shadow,
            "chapter": chapter,
            "run_id": (current_run() or {}).get("id"),
        }
        append_record("live", row)
        bets.append(row)
        recent_rows.append(row)
        if len(recent_rows) > 400:
            del recent_rows[:150]
        _PROGRESS["soul"] = soul_snapshot(recent_rows)
        if engine.combo:
            _PROGRESS["phase"] = engine.combo.phase
            _PROGRESS["probe_work"] = engine.combo.probe_work
        session_profit += round_profit
        session_rounds += 1
        last_mult = Decimal(str(result.get("payout_multiplier") or "0"))
        _PROGRESS.update(
            {
                "completed": len(bets),
                "total": plan["target"],
                "last": row,
                "chapter": chapter,
                "session_profit": money_str(session_profit),
                "session_index": session_index,
                "session_rounds": session_rounds,
                "stop_reason": None,
            }
        )
        status["balance"] = result.get("balance_after") or status.get("balance")
        if stop_on_max_win and not recon and max_lv and level >= int(max_lv) and round_profit >= 0:
            return "max-level-win"
        if session_profit <= -stop_loss:
            return "stop-loss hit"
        if book.get("daily_stop_win") is not None and day_profit >= book["daily_stop_win"]:
            return "daily-take-profit"
        if book.get("daily_stop_loss") is not None and day_profit <= -abs(book["daily_stop_loss"]):
            return "daily-stop-loss"
        if not book["enabled"] and stop_win is not None and session_profit >= stop_win:
            return "stop-win hit"
        if session_rounds >= session_cap:
            return "session-rounds"
        if max_streak < 10000:
            from .ledger import summarize as _sum

            session_rows = scoped_records("live", "session")
            if engine.combo and engine.combo.recon_on:
                streak_now = current_real_loss_streak(session_rows)
            else:
                streak_now = int(_sum(session_rows).get("current_loss_streak") or 0)
            if streak_now >= max_streak:
                return "max-streak"
        end = session_should_end(session_profit, session_rounds, last_mult, book)
        if chapter == "grind":
            grind_left = max(0, grind_left - 1)
            if grind_left == 0:
                end = end or "grind-done"
        if end:
            if playbook_hard_stop(end, book):
                return end
            session_id = new_live_session()
            session_profit = Decimal("0")
            session_rounds = 0
            banked = end in {"session-fat-hit", "session-take-profit"}
            if end == "grind-done":
                switch_chapter("hunt")
            elif banked and book["after_bank"] == "grind":
                switch_chapter("grind")
            else:
                switch_chapter("hunt")
            _PROGRESS["chapter"] = chapter
        return None

    try:
        slice_index = 0
        while len(bets) < plan["target"]:
            if _CANCEL.is_set():
                stop_reason = "cancelled"
                break
            if deadline is not None and time.time() >= deadline:
                stop_reason = "hours completed"
                break
            remaining = plan["target"] - len(bets)
            this_slice = min(plan["slice_rounds"], remaining)
            slice_index += 1
            _PROGRESS["slice"] = slice_index
            _PROGRESS["slices"] = plan["slices"]
            slice_fail = None
            for i in range(this_slice):
                if _CANCEL.is_set():
                    slice_fail = "cancelled"
                    break
                if deadline is not None and time.time() >= deadline:
                    slice_fail = "hours completed"
                    break
                slice_fail = place_one()
                if slice_fail:
                    break
                if i + 1 < this_slice and not _interruptible_sleep(plan["pace"]):
                    slice_fail = "cancelled"
                    break
            if slice_fail:
                stop_reason = slice_fail
                host_rest = book.get("after_bank") == "rest" and loop_sessions
                soul_lock = book.get("after_bank") == "stop" and slice_fail in (
                    SOUL_BANK_STOPS | {"max-level-win", "stop-win hit", "session-rounds"}
                )
                if host_rest and slice_fail in HOST_RESUME_REASONS and not _CANCEL.is_set():
                    _PROGRESS["rotate_reason"] = _zh_stop(slice_fail)
                    rotate_now(slice_fail)
                    if engine.combo:
                        engine.combo.in_recon = True
                        if slice_fail in DAY_REST_REASONS:
                            engine.combo.lock_real_until = time.time() + rest_seconds_for(slice_fail, book)
                            engine.combo.probe_work = 0
                        elif slice_fail in HARD_REST_REASONS:
                            engine.combo.probe_work = 50
                        else:
                            engine.combo.probe_work = 30
                    continue
                if loop_sessions and slice_fail in SESSION_ROTATE_REASONS and not soul_lock and not host_rest and not _CANCEL.is_set():
                    rotate_now(slice_fail)
                    continue
                recoverable = stop_reason in {"Stake 未确认入账"} or str(stop_reason).startswith("bet failed")
                if recoverable and len(bets) < plan["target"] and not _CANCEL.is_set():
                    if not _interruptible_sleep(max(plan["cooldown"], 8)):
                        stop_reason = "cancelled"
                        break
                    try:
                        from .stake_cdp import ensure_cdp

                        ensure_cdp(cdp)
                        status = connect_stake(cdp=cdp, wait_login=60)
                    except Exception:
                        status = live_status()
                    if status.get("status") != "connected":
                        stop_reason = "reconnect failed"
                        break
                    continue
                break
            if len(bets) >= plan["target"]:
                stop_reason = "rounds completed"
                break
            if plan["unattended"] and plan["cooldown"] > 0:
                try:
                    status = refresh_stake()
                except Exception:
                    status = live_status()
                if not _interruptible_sleep(plan["cooldown"]):
                    stop_reason = "cancelled"
                    break
    finally:
        _RUNNING = False
        mark_play_end()
        _PROGRESS["stop_reason"] = _zh_stop(stop_reason)
    try:
        status = refresh_stake()
    except Exception:
        status = live_status()
    return {
        "ok": True,
        "live_bets": True,
        "book": "live",
        "session": session_id,
        "rounds": len(bets),
        "profit": str(profit),
        "stop_reason": _zh_stop(stop_reason),
        "currency": currency,
        "bets": bets[-80:],
        "plan": plan,
        "viability": verdict,
        "preview": engine.preview(Decimal(str(status.get("balance") or "0") or "0")),
        "account": {
            "user_name": status.get("user_name"),
            "balance": status.get("balance"),
            "currency": status.get("currency"),
            "synced_at": status.get("synced_at"),
        },
    }
