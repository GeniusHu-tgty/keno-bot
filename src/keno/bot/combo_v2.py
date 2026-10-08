from __future__ import annotations

"""Combo V2 (侦察) — 对齐四档阶梯 bot 的资金档 + 赢了留号 + 热力选号。"""

import time
from collections import Counter
from decimal import Decimal
from random import Random
from typing import Iterable, Sequence

MIN_BET = Decimal("0.0001")
QUANT = Decimal("0.00000001")
EXPECT_PCT = 25.0  # 10/40
WINDOW = 100
ZONES = ((1, 8), (9, 16), (17, 24), (25, 32), (33, 40))


def _q(value: Decimal) -> Decimal:
    return value.quantize(QUANT)


def parse_amounts(text: str) -> list[Decimal]:
    parts = [p.strip() for p in str(text or "").replace("，", ",").split(",") if p.strip()]
    amounts = [max(MIN_BET, Decimal(p)) for p in parts]
    if not amounts:
        raise ValueError("自定义金额至少要有一档")
    return amounts


def is_win(payout: Decimal, bet: Decimal) -> bool:
    """参考成功率：收回 >= 投下。低等 2 命中 1.1x 算赢，中等 2 命中 0 算输。"""
    return payout >= bet


def _truthy(value, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    return value not in (False, "false", "0", 0, "OFF", "off")


def _int_or(value, default: int) -> int:
    if value in (None, ""):
        return default
    return int(value)


def analyze_numbers(draws: Sequence[Sequence[int]], window: int = WINDOW) -> dict[int, dict]:
    recent = [list(d) for d in draws[-window:] if d]
    n = len(recent)
    out: dict[int, dict] = {}
    for number in range(1, 41):
        appeared = [i for i, draw in enumerate(recent) if number in draw]
        freq = (100.0 * len(appeared) / n) if n else 0.0
        last_idx = appeared[-1] if appeared else -1
        gap = n - 1 - last_idx if n else 0
        if last_idx < 0:
            gap = n
        half = max(1, n // 5) if n else 1
        recent_hits = sum(1 for draw in recent[-half:] if number in draw) if n else 0
        older_hits = sum(1 for draw in recent[-2 * half : -half] if number in draw) if n else 0
        rising = recent_hits > older_hits
        consecutive = 0
        for draw in reversed(recent):
            if number in draw:
                consecutive += 1
            else:
                break
        tags: list[str] = []
        if gap >= 8:
            tags.append(f"空窗{gap}")
        if freq >= 32:
            tags.append("热")
        if rising:
            tags.append("升")
        if consecutive >= 2:
            tags.append(f"{consecutive}连出")
        if 22 <= freq <= 28 and "热" not in tags:
            tags.append("稳定")
        score = (freq - EXPECT_PCT) + gap * 0.8 + (8 if rising else 0) + consecutive * 2
        out[number] = {
            "n": number,
            "freq": round(freq, 1),
            "gap": gap,
            "rising": rising,
            "consecutive": consecutive,
            "tags": tags,
            "score": score,
            "hot": freq >= 32,
        }
    return out


def recommend(analysis: dict[int, dict], pick_count: int, rng: Random) -> list[int]:
    if pick_count < 1:
        return []
    hot_rising = sorted(
        analysis.values(),
        key=lambda x: (not x["hot"], not x["rising"], -x["freq"], -x["consecutive"], x["n"]),
    )
    due = sorted(analysis.values(), key=lambda x: (-x["gap"], -x["score"], x["n"]))
    stable = [x for x in analysis.values() if "稳定" in x["tags"] or x["rising"]]
    stable.sort(key=lambda x: (-x["score"], x["n"]))
    picked: list[int] = []

    def take(rows: Iterable[dict], need: int) -> None:
        for row in rows:
            if len(picked) >= pick_count:
                return
            if row["n"] not in picked:
                picked.append(row["n"])
                need -= 1
                if need <= 0:
                    return

    take(hot_rising, max(3, pick_count // 3 + 1))
    take(due, max(3, pick_count // 3 + 1))
    take(stable, pick_count)
    if len(picked) < pick_count:
        rest = [n for n in range(1, 41) if n not in picked]
        rng.shuffle(rest)
        picked.extend(rest[: pick_count - len(picked)])
    return sorted(picked[:pick_count])


def zone_rows(analysis: dict[int, dict]) -> list[dict]:
    rows = []
    for start, end in ZONES:
        cells = [analysis[n] for n in range(start, end + 1)]
        avg = sum(c["freq"] for c in cells) / len(cells) if cells else 0.0
        hot = sum(1 for c in cells if c["hot"])
        rows.append({"label": f"{start}–{end}", "avg": round(avg, 1), "hot": hot})
    return rows


def soul_snapshot(records: Sequence[dict]) -> dict:
    """Cheap live note: real WR, streaks, L4, hot numbers. Does not change EV."""
    rows = list(records or [])
    def recon(r: dict) -> bool:
        return bool(r.get("recon") or r.get("stage") == "侦察" or str(r.get("level")) in ("0", "None"))
    def won(r: dict) -> bool:
        try:
            return Decimal(str(r.get("payout") or "0")) >= Decimal(str(r.get("bet") or "0"))
        except Exception:
            return False
    real = [r for r in rows if not recon(r)]
    scout = [r for r in rows if recon(r)]
    last_real = real[-80:]
    wr = (sum(1 for r in last_real if won(r)) / len(last_real)) if last_real else 0.0
    l4 = [r for r in real if str(r.get("level")) in ("4", 4)]
    l4_w = sum(1 for r in l4 if won(r))
    streak = current_real_loss_streak(rows)
    freq: Counter[int] = Counter()
    for r in rows[-60:]:
        for n in r.get("drawn") or []:
            try:
                freq[int(n)] += 1
            except Exception:
                pass
    hot = [n for n, _ in freq.most_common(10)]
    return {
        "real_n": len(last_real),
        "real_wr": round(wr, 4),
        "scout_n": len(scout[-80:]),
        "streak": streak,
        "l4_n": len(l4),
        "l4_w": l4_w,
        "l4_l": len(l4) - l4_w,
        "hot": hot,
        "note": (
            f"近{len(last_real)}局实战成功率 {wr:.1%}，实战连败 {streak}。"
            f"第4档 {l4_w}胜{len(l4)-l4_w}负。6小时最多2枪第4档；5命中锁6小时。"
        ),
    }


def dashboard(records: Sequence[dict]) -> dict:
    """等级 / 连败 / 命中表，成功率按收回>=投下。"""
    levels: dict[int, dict] = {}
    hits: dict[int, dict] = {i: {"n": 0, "staked": Decimal("0"), "returned": Decimal("0")} for i in range(11)}
    streak_hist = {k: 0 for k in range(2, 11)}
    current_streak = 0
    max_streak = 0
    run = 0
    real_streak_hist = {k: 0 for k in range(2, 11)}
    real_current = 0
    real_max = 0
    real_run = 0
    recon_rounds = 0
    staked = Decimal("0")
    returned = Decimal("0")
    win_profit = Decimal("0")
    lose_profit = Decimal("0")
    wins = 0
    cum = Decimal("0")
    peak = Decimal("0")
    trough = Decimal("0")
    peak_n = 0
    trough_n = 0
    curve: list[dict] = []
    ordered = list(records)
    for i, row in enumerate(ordered, 1):
        bet = Decimal(str(row.get("bet") or "0"))
        payout = Decimal(str(row.get("payout") or "0"))
        hit = int(row.get("hits") or 0)
        raw_lv = row.get("level")
        level = int(raw_lv) if raw_lv not in (None, "") else 1
        staked += bet
        returned += payout
        pnl = payout - bet
        cum += pnl
        if cum > peak:
            peak = cum
            peak_n = i
        if cum < trough:
            trough = cum
            trough_n = i
        curve.append(
            {
                "n": int(row.get("n") or i),
                "level": level,
                "hits": hit,
                "profit": str(_q(pnl)),
                "cum": str(_q(cum)),
            }
        )
        is_recon = bool(row.get("recon")) or str(row.get("stage") or "") == "侦察"
        if is_recon:
            level = 0
            recon_rounds += 1
        win = is_win(payout, bet)
        if win:
            wins += 1
            win_profit += pnl
            if run >= 2:
                streak_hist[min(run, 10)] += 1
            run = 0
            current_streak = 0
        else:
            lose_profit += pnl
            run += 1
            current_streak = run
            max_streak = max(max_streak, run)
        if not is_recon:
            if win:
                if real_run >= 2:
                    real_streak_hist[min(real_run, 10)] += 1
                real_run = 0
                real_current = 0
            else:
                real_run += 1
                real_current = real_run
                real_max = max(real_max, real_run)
        bucket = levels.setdefault(
            level,
            {"level": level, "n": 0, "wins": 0, "fails": 0, "staked": Decimal("0"), "returned": Decimal("0")},
        )
        bucket["n"] += 1
        bucket["staked"] += bet
        bucket["returned"] += payout
        if win:
            bucket["wins"] += 1
        else:
            bucket["fails"] += 1
        if 0 <= hit <= 10:
            hits[hit]["n"] += 1
            hits[hit]["staked"] += bet
            hits[hit]["returned"] += payout

    def money_row(st: Decimal, ret: Decimal) -> dict:
        return {
            "staked": str(_q(st)),
            "returned": str(_q(ret)),
            "profit": str(_q(ret - st)),
        }

    level_rows = []
    for level in sorted(levels):
        b = levels[level]
        level_rows.append(
            {
                "level": level,
                "label": "侦察" if level == 0 else f"{level}档",
                "n": b["n"],
                "wins": b["wins"],
                "fails": b["fails"],
                "winrate": (b["wins"] / b["n"]) if b["n"] else 0.0,
                **money_row(b["staked"], b["returned"]),
            }
        )
    hit_rows = []
    total = len(ordered) or 1
    for hit in range(0, 11):
        h = hits[hit]
        if h["n"] == 0 and hit > 7:
            continue
        hit_rows.append(
            {
                "hits": hit,
                "n": h["n"],
                "pct": h["n"] / total if ordered else 0.0,
                **money_row(h["staked"], h["returned"]),
            }
        )
    profit = _q(returned - staked)
    return {
        "rounds": len(ordered),
        "wins": wins,
        "fails": len(ordered) - wins,
        "winrate": (wins / len(ordered)) if ordered else 0.0,
        "staked": str(_q(staked)),
        "returned": str(_q(returned)),
        "profit": str(profit),
        "win_profit": str(_q(win_profit)),
        "lose_profit": str(_q(lose_profit)),
        "current_streak": current_streak,
        "max_streak": max_streak,
        "recon_rounds": recon_rounds,
        "real_current_streak": real_current,
        "real_max_streak": real_max,
        "real_streaks": [{"k": k, "n": real_streak_hist[k]} for k in range(2, 11)],
        "peak": str(_q(peak)),
        "trough": str(_q(trough)),
        "peak_n": peak_n,
        "trough_n": trough_n,
        "curve": curve,
        "levels": level_rows,
        "streaks": [{"k": k, "n": streak_hist[k]} for k in range(2, 11)],
        "hits": hit_rows,
    }


def current_real_loss_streak(records: Sequence[dict]) -> int:
    """Consecutive real-money losses, skipping recon rows. Used for 最大连败 stop."""
    run = 0
    for row in records:
        if row.get("recon") or str(row.get("stage") or "") == "侦察":
            continue
        bet = Decimal(str(row.get("bet") or "0"))
        payout = Decimal(str(row.get("payout") or "0"))
        if is_win(payout, bet):
            run = 0
        else:
            run += 1
    return run


class ComboV2:
    """自定义 N 档马丁 + 可选侦察。赢了回 1 档，输了升档。"""

    name = "combo"

    def __init__(
        self,
        amounts: list[Decimal],
        start_level: int = 1,
        max_level: int | None = None,
        reset_on_max_loss: bool = False,
        recon_on: bool = False,
        recon_n_loss: int = 2,
        recon_n_win: int = 0,
        recon_real_n: int = 4,
        recon_min: Decimal = MIN_BET,
        recon_max: Decimal = MIN_BET,
        recon_numbers_fixed: bool = True,
        keep_on_win: bool = True,
        recon_return_on_real_win: bool = False,
        recon_abort_on_real_loss: bool = False,
        recon_abort_after: int = 0,
    ) -> None:
        if not amounts:
            raise ValueError("amounts required")
        self.amounts = [max(MIN_BET, _q(a)) for a in amounts]
        self.start_level = max(1, int(start_level))
        cap = max_level if max_level is not None else len(self.amounts)
        self.max_level = max(self.start_level, min(int(cap), len(self.amounts)))
        self.reset_on_max_loss = bool(reset_on_max_loss)
        self.recon_on = bool(recon_on)
        self.recon_n_loss = max(0, int(recon_n_loss))
        self.recon_n_win = max(0, int(recon_n_win))
        self.recon_real_n = max(1, int(recon_real_n))
        self.recon_min = max(MIN_BET, _q(recon_min))
        self.recon_max = max(self.recon_min, _q(recon_max))
        self.recon_numbers_fixed = bool(recon_numbers_fixed)
        self.keep_on_win = bool(keep_on_win)
        self.recon_return_on_real_win = bool(recon_return_on_real_win)
        self.recon_abort_on_real_loss = bool(recon_abort_on_real_loss)
        abort_after = max(0, int(recon_abort_after))
        if self.recon_abort_on_real_loss:
            abort_after = max(abort_after, 1)
        self.recon_abort_after = abort_after
        self.level = self.start_level
        self.in_recon = bool(self.recon_on)
        self.recon_losses = 0
        self.recon_wins = 0
        self.real_loss_run = 0
        self.l4_times: list[float] = []
        self.freeze_l4_until = 0.0
        self.probe_work = 0
        self.lock_real_until = 0.0
        self.real_left = 0
        self.last_amount = self.amounts[self.start_level - 1]
        self.picks: list[int] | None = None

    @classmethod
    def from_payload(cls, payload: dict) -> "ComboV2":
        amounts = parse_amounts(str(payload.get("custom_amounts") or payload.get("amounts") or "0.0001"))
        return cls(
            amounts=amounts,
            start_level=int(payload.get("start_level") or 1),
            max_level=int(payload.get("max_level") or len(amounts)),
            reset_on_max_loss=bool(payload.get("reset_on_max_loss")),
            recon_on=bool(payload.get("recon_on")),
            recon_n_loss=_int_or(payload.get("recon_n_loss"), 2),
            recon_n_win=_int_or(payload.get("recon_n_win"), 0),
            recon_real_n=_int_or(payload.get("recon_real_n"), 4),
            recon_min=Decimal(str(payload.get("recon_min") or "0.0001")),
            recon_max=Decimal(str(payload.get("recon_max") or "0.0001")),
            recon_numbers_fixed=str(payload.get("recon_numbers") or "fixed") != "reshuffle",
            keep_on_win=_truthy(payload.get("keep_on_win", True), True),
            recon_return_on_real_win=_truthy(payload.get("recon_return_on_real_win"), False),
            recon_abort_on_real_loss=_truthy(payload.get("recon_abort_on_real_loss"), False),
            recon_abort_after=_int_or(payload.get("recon_abort_after"), 0),
        )

    def clone(self) -> "ComboV2":
        other = ComboV2(
            list(self.amounts),
            self.start_level,
            self.max_level,
            self.reset_on_max_loss,
            self.recon_on,
            self.recon_n_loss,
            self.recon_n_win,
            self.recon_real_n,
            self.recon_min,
            self.recon_max,
            self.recon_numbers_fixed,
            self.keep_on_win,
            self.recon_return_on_real_win,
            self.recon_abort_on_real_loss,
            self.recon_abort_after,
        )
        other.level = self.level
        other.in_recon = self.in_recon
        other.recon_losses = self.recon_losses
        other.recon_wins = self.recon_wins
        other.real_loss_run = self.real_loss_run
        other.l4_times = list(self.l4_times)
        other.freeze_l4_until = self.freeze_l4_until
        other.probe_work = self.probe_work
        other.lock_real_until = self.lock_real_until
        other.real_left = self.real_left
        other.last_amount = self.last_amount
        other.picks = list(self.picks) if self.picks else None
        return other

    def reset_run(self) -> None:
        self.level = self.start_level
        self.in_recon = bool(self.recon_on)
        self.recon_losses = 0
        self.recon_wins = 0
        self.real_loss_run = 0
        self.real_left = 0
        self.last_amount = self.next_bet(Decimal("1"))

    def _enter_recon(self) -> None:
        self.in_recon = True
        self.real_left = 0
        self.recon_losses = 0
        self.recon_wins = 0
        self.real_loss_run = 0
        self.level = self.start_level

    def locked_to_probe(self) -> bool:
        if self.probe_work > 0:
            return True
        return bool(self.lock_real_until) and time.time() < float(self.lock_real_until)

    def _note_l4(self) -> None:
        now = time.time()
        cutoff = now - 6 * 3600
        self.l4_times = [t for t in self.l4_times if t >= cutoff]
        self.l4_times.append(now)

    def l4_allowed(self) -> bool:
        now = time.time()
        if now < float(self.freeze_l4_until or 0):
            return False
        cutoff = now - 6 * 3600
        self.l4_times = [t for t in self.l4_times if t >= cutoff]
        return len(self.l4_times) < 2

    def next_bet(self, bankroll: Decimal | None = None) -> Decimal:
        if self.recon_on and (self.in_recon or self.locked_to_probe()):
            self.last_amount = self.recon_min
            return self.last_amount
        level = self.level
        if level >= 3 and not self.l4_allowed():
            self._enter_recon()
            self.last_amount = self.recon_min
            return self.last_amount
        idx = min(max(level, 1), self.max_level, len(self.amounts)) - 1
        self.last_amount = self.amounts[idx]
        return self.last_amount

    def observe(self, profit: Decimal, hits: int | None = None) -> None:
        win = profit >= 0
        if self.recon_on and self.in_recon:
            if self.probe_work > 0:
                self.probe_work -= 1
            if win:
                self.recon_wins += 1
                self.recon_losses = 0
            else:
                self.recon_losses += 1
                self.recon_wins = 0
            if self.locked_to_probe():
                return
            hit_loss = self.recon_n_loss > 0 and self.recon_losses >= self.recon_n_loss
            hit_win = self.recon_n_win > 0 and self.recon_wins >= self.recon_n_win
            if hit_loss or hit_win:
                self.in_recon = False
                self.real_left = self.recon_real_n
                self.level = self.start_level
                self.recon_losses = 0
                self.recon_wins = 0
            return
        if win:
            if self.level >= self.max_level:
                self._note_l4()
                if hits is not None and hits >= 5:
                    self.freeze_l4_until = time.time() + 6 * 3600
                    self.probe_work = max(self.probe_work, 40)
            self.real_loss_run = 0
            self.level = self.start_level
            if self.recon_on and self.recon_return_on_real_win:
                self._enter_recon()
                return
        else:
            self.real_loss_run += 1
            if self.level >= self.max_level:
                self._note_l4()
                self._enter_recon()
                self.probe_work = max(self.probe_work, 40)
                return
            if self.recon_on and self.recon_abort_after and self.real_loss_run >= self.recon_abort_after:
                self._enter_recon()
                return
            nxt = self.level + 1 if self.level < self.max_level else self.level
            if nxt >= 3 and not self.l4_allowed():
                self._enter_recon()
                self.probe_work = max(self.probe_work, 20)
                return
            if self.level < self.max_level:
                self.level += 1
            elif self.recon_on and self.recon_return_on_real_win:
                self._enter_recon()
                return
            elif self.reset_on_max_loss:
                self.level = self.start_level
        if self.recon_on and not self.in_recon and not self.recon_return_on_real_win:
            self.real_left = max(0, self.real_left - 1)
            if self.real_left <= 0:
                self._enter_recon()

    @property
    def phase(self) -> str:
        if self.locked_to_probe():
            if self.probe_work > 0:
                return f"分析探针({self.probe_work})"
            return "分析探针"
        if self.recon_on and self.in_recon:
            return "侦察"
        return f"{self.level}档"

    @property
    def display_stage(self) -> str:
        return self.phase

    def choose_picks(
        self,
        draws: Sequence[Sequence[int]],
        pick_count: int,
        rng: Random,
        won_last: bool | None,
        manual: list[int] | None = None,
    ) -> list[int]:
        if manual and len(manual) == pick_count:
            self.picks = sorted(manual)
            return list(self.picks)
        if self.picks and self.keep_on_win and won_last:
            return list(self.picks)
        if self.picks and self.recon_on and self.recon_numbers_fixed and not self.in_recon and won_last is not False:
            return list(self.picks)
        analysis = analyze_numbers(draws)
        self.picks = recommend(analysis, pick_count, rng)
        return list(self.picks)
