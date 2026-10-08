# -*- coding: utf-8 -*-
"""
本地实盘选号完整一份（Combo V2，侦察默认关）。

和页面 /live 同一条链：
  近 100 局开奖
    → analyze_numbers  每个号：频率/空窗/升/连出/标签/分数（热力图格子）
    → zone_rows        五个分区 1–8 … 33–40（均分、热号个数）
    → recommend        混「热+升 / 空窗到期 / 稳定或在升」凑 10 个
    → 赢了留号，输了重选

下注用的 10 个号：
  1) 棋盘上已经点满 10 个 → 用手选
  2) 赢了且「赢了留号」开着 → 上一把那 10 个不动
  3) 否则走 recommend（实盘 rng）

界面「推荐号码」会再用 Random(1) 跑一遍 recommend，只给热力图旁边展示，
和实际下注那 10 个在「输了换号」时可能差几个（两个随机源）。
分区标签只展示，不另算一套号；但「稳定/热/升」这些标签 recommend 会用。

热力图不改变 RTP。
"""

from __future__ import annotations

from random import Random
from typing import Iterable, Sequence

EXPECT_PCT = 25.0  # 10/40
WINDOW = 100
ZONES = ((1, 8), (9, 16), (17, 24), (25, 32), (33, 40))
KEEP_DRAWS = 200  # 引擎里超过 400 局会裁到最近 200


def analyze_numbers(draws: Sequence[Sequence[int]], window: int = WINDOW) -> dict[int, dict]:
    """热力图每个号一格。"""
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
    """自动选号。"""
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
    """分区标签：1–8 / 9–16 / 17–24 / 25–32 / 33–40。"""
    rows = []
    for start, end in ZONES:
        cells = [analysis[n] for n in range(start, end + 1)]
        avg = sum(c["freq"] for c in cells) / len(cells) if cells else 0.0
        hot = sum(1 for c in cells if c["hot"])
        rows.append({"label": f"{start}–{end}", "avg": round(avg, 1), "hot": hot})
    return rows


def recommended_with_tags(analysis: dict[int, dict], pick_count: int, rng: Random) -> list[dict]:
    """界面「推荐号码」那一排：号 + 频率 + 标签。"""
    recs = []
    for n in recommend(analysis, pick_count, rng):
        cell = analysis.get(n) or {}
        recs.append({"n": n, "freq": cell.get("freq"), "tags": cell.get("tags") or []})
    return recs


class Picker:
    """和 /live 引擎同一套：热力 + 分区 + 推荐 + 赢了留号。侦察默认关。"""

    def __init__(self, pick_count: int = 10, keep_on_win: bool = True, rng_seed: int = 7) -> None:
        self.pick_count = pick_count
        self.keep_on_win = keep_on_win
        self.rng = Random(rng_seed)
        self.draws: list[list[int]] = []
        self.picks: list[int] | None = None
        self.last_win: bool | None = None
        self.recon_on = False
        self.recon_numbers_fixed = True
        self.in_recon = False

    def heatmap(self) -> dict[int, dict]:
        return analyze_numbers(self.draws)

    def zones(self) -> list[dict]:
        heat = self.heatmap()
        return zone_rows(heat) if heat else []

    def ui_recommended(self) -> list[dict]:
        """页面推荐条，固定 Random(1)，和实际下注可能不完全相同。"""
        heat = self.heatmap()
        if not heat:
            return []
        return recommended_with_tags(heat, min(10, self.pick_count), Random(1))

    def choose(
        self,
        won_last: bool | None = None,
        manual: list[int] | None = None,
    ) -> list[int]:
        if won_last is None:
            won_last = self.last_win
        if manual and len(manual) == self.pick_count:
            self.picks = sorted(int(x) for x in manual)
            return list(self.picks)
        if self.picks and self.keep_on_win and won_last:
            return list(self.picks)
        if (
            self.picks
            and self.recon_on
            and self.recon_numbers_fixed
            and not self.in_recon
            and won_last is not False
        ):
            return list(self.picks)
        rng = Random()
        rng.setstate(self.rng.getstate())
        heat = analyze_numbers(self.draws)
        self.picks = recommend(heat, self.pick_count, rng)
        return list(self.picks)

    def preview(self, manual: list[int] | None = None) -> dict:
        picks = self.choose(self.last_win, manual)
        heat = self.heatmap()
        return {
            "picks": picks,
            "picks_why": (
                "赢了留号，输了按 100 局热力/空窗/热号重选。"
                if self.keep_on_win
                else "每局按热力重选。"
            ),
            "heatmap": heat,
            "recommended": self.ui_recommended(),
            "zones": zone_rows(heat) if heat else [],
        }

    def commit(self, profit, drawn: Sequence[int], selected: Sequence[int] | None = None) -> None:
        """Stake 确认之后才推进。赢且留号则号不动；否则清空，下一把重选。"""
        win = profit >= 0
        if selected:
            self.picks = sorted(int(x) for x in selected)
        if not (win and self.keep_on_win):
            self.picks = None
        self.last_win = win
        self.draws.append(list(drawn or []))
        if len(self.draws) > 400:
            self.draws = self.draws[-KEEP_DRAWS:]
