# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
"""Replay the reference 411-round screenshot: identities, curve, drawdown, luck vs typical."""
from __future__ import annotations

from math import comb
from pathlib import Path
from random import Random

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "photos" / "参考411局_复盘.png"

LADDER = (0.01, 0.11, 1.20, 13.30)
MULT = (0.0, 0.0, 1.1, 1.2, 1.3, 1.8, 3.5, 13.0, 50.0, 250.0, 1000.0)


def hg_p(k: int) -> float:
    if k < 0 or k > 10:
        return 0.0
    return comb(10, k) * comb(30, 10 - k) / comb(40, 10)


P_HIT = [hg_p(k) for k in range(11)]
P_WIN = sum(P_HIT[2:])
P_LOSS = 1.0 - P_WIN


def sample_hits(rng: Random) -> int:
    x = rng.random()
    acc = 0.0
    for k, p in enumerate(P_HIT):
        acc += p
        if x <= acc:
            return k
    return 10


def play_session(n: int, rng: Random) -> dict:
    level = 1
    profit = 0.0
    peak = 0.0
    trough = 0.0
    max_dd = 0.0
    curve = [0.0]
    staked = 0.0
    wins = 0
    l4 = 0
    l4_loss = 0
    run = 0
    max_streak = 0
    two = 0
    three = 0
    four = 0
    for _ in range(n):
        bet = LADDER[level - 1]
        hits = sample_hits(rng)
        payout = bet * MULT[hits]
        pnl = payout - bet
        profit += pnl
        staked += bet
        curve.append(profit)
        if profit > peak:
            peak = profit
        if profit < trough:
            trough = profit
        dd = peak - profit
        if dd > max_dd:
            max_dd = dd
        win = payout >= bet
        if win:
            wins += 1
            if run == 2:
                two += 1
            elif run == 3:
                three += 1
            elif run >= 4:
                four += 1
            run = 0
            if level == 4:
                l4 += 1
            level = 1
        else:
            run += 1
            max_streak = max(max_streak, run)
            if level == 4:
                l4 += 1
                l4_loss += 1
                # 参考图「最大档还输就重置」是关的：继续打 13.3
            else:
                level += 1
    return {
        "profit": profit,
        "staked": staked,
        "winrate": wins / n,
        "max_dd": max_dd,
        "trough": trough,
        "peak": peak,
        "l4": l4,
        "l4_loss": l4_loss,
        "two": two,
        "three": three,
        "four": four,
        "max_streak": max_streak,
        "curve": curve,
    }


def reference_cycles():
    """Exact bag of cycles implied by the screenshot (order unknown)."""
    cycles = []
    # L1 wins: 95@1.1, 105@1.2, 36@1.3, 14@1.8, 4@3.5, 1@13
    for n, m in ((95, 1.1), (105, 1.2), (36, 1.3), (14, 1.8), (4, 3.5), (1, 13.0)):
        cycles.extend([("L1W", (m,))] * n)
    # L2 wins after L1 loss: 19@1.1, 23@1.2, 14@1.3, 3@1.8
    for n, m in ((19, 1.1), (23, 1.2), (14, 1.3), (3, 1.8)):
        cycles.extend([("L2W", (0.0, m))] * n)
    # L3: 5 two-hit 1.1x, 5 four-hit 1.3x
    cycles.extend([("L3W", (0.0, 0.0, 1.1))] * 5)
    cycles.extend([("L3W", (0.0, 0.0, 1.3))] * 5)
    # L4 both 5-hit 1.8x
    cycles.extend([("L4W", (0.0, 0.0, 0.0, 1.8))] * 2)
    return cycles


def replay_cycles(cycles) -> tuple[list[float], float]:
    profit = 0.0
    peak = 0.0
    max_dd = 0.0
    curve = [0.0]
    for _kind, mults in cycles:
        for i, m in enumerate(mults):
            bet = LADDER[i]
            pnl = bet * m - bet
            profit += pnl
            curve.append(profit)
            if profit > peak:
                peak = profit
            dd = peak - profit
            if dd > max_dd:
                max_dd = dd
    return curve, max_dd


def main() -> None:
    cycles = reference_cycles()
    assert len(cycles) == 326
    n_games = sum(len(c[1]) for c in cycles)
    assert n_games == 411, n_games

    rng = Random(7)
    dds = []
    curves = []
    for i in range(400):
        bag = cycles[:]
        rng.shuffle(bag)
        curve, dd = replay_cycles(bag)
        dds.append(dd)
        if i < 30:
            curves.append(curve)
    # one representative: L4 climbs late (looks like a "big win session")
    late = [c for c in cycles if c[0] != "L4W"] + [c for c in cycles if c[0] == "L4W"]
    rng2 = Random(1)
    rest = [c for c in late if c[0] != "L4W"]
    rng2.shuffle(rest)
    late_bag = rest + [c for c in cycles if c[0] == "L4W"]
    late_curve, late_dd = replay_cycles(late_bag)
    # one with L4 early
    early_bag = [c for c in cycles if c[0] == "L4W"] + rest
    early_curve, early_dd = replay_cycles(early_bag)

    mc_rng = Random(42)
    mc = [play_session(411, mc_rng) for _ in range(8000)]
    profits = np.array([s["profit"] for s in mc])
    mdds = np.array([s["max_dd"] for s in mc])
    l4_loss = np.array([s["l4_loss"] for s in mc])
    twos = np.array([s["two"] for s in mc])
    threes = np.array([s["three"] for s in mc])
    fours = np.array([s["four"] for s in mc])
    l4s = np.array([s["l4"] for s in mc])

    # typical / lucky / ruin examples
    idx_med = int(np.argsort(profits)[len(profits) // 2])
    idx_p95 = int(np.argsort(profits)[int(0.95 * len(profits))])
    ruin_cands = [i for i, s in enumerate(mc) if s["l4_loss"] >= 1]
    idx_ruin = ruin_cands[int(np.argmin([mc[i]["profit"] for i in ruin_cands]))] if ruin_cands else 0

    print("=== identities ===")
    print("P(loss)", round(P_LOSS, 4), "P(win)", round(P_WIN, 4))
    print("expected hits in 411:", [round(411 * p, 1) for p in P_HIT[:8]])
    print("observed hits:", [17, 68, 119, 128, 55, 19, 4, 1])
    print("expected 2-loss completions ~", round(411 * (P_LOSS ** 2) * P_WIN, 1), "obs 10")
    print("expected 3-loss completions ~", round(411 * (P_LOSS ** 3) * P_WIN, 1), "obs 2")
    print("expected L4 bets ~", round(411 * (P_LOSS ** 3), 1), "obs 2")
    print("expected L4 losses ~", round(411 * (P_LOSS ** 4), 2), "obs 0")
    rtp = sum(P_HIT[k] * MULT[k] for k in range(11))
    print("low-10 RTP", round(rtp, 5))
    print("session RTP", round(73.506 / 52.07, 4), "profit 21.436 on 52.07 staked")
    print()
    print("=== this bag shuffled 400 times (same bets, different order) ===")
    print("profit always", round(late_curve[-1], 4))
    print("max DD min/median/max", round(min(dds), 4), round(float(np.median(dds)), 4), round(max(dds), 4))
    print("late L4 DD", round(late_dd, 4), "early L4 DD", round(early_dd, 4))
    print()
    print("=== 8000 fair 411-round sessions ===")
    print("profit mean/median", round(profits.mean(), 3), round(float(np.median(profits)), 3))
    print("profit p05 p25 p75 p95", [round(float(np.percentile(profits, p)), 2) for p in (5, 25, 75, 95)])
    print("P(profit>20)", round(float(np.mean(profits > 20)), 4))
    print("P(profit>21.4)", round(float(np.mean(profits >= 21.4)), 4))
    print("P(profit<0)", round(float(np.mean(profits < 0)), 4))
    print("P(profit<-10)", round(float(np.mean(profits < -10)), 4))
    print("maxDD mean/median/p95", round(mdds.mean(), 3), round(float(np.median(mdds)), 3), round(float(np.percentile(mdds, 95)), 3))
    print("P(at least 1 L4 loss)", round(float(np.mean(l4_loss >= 1)), 4))
    print("P(no L4 loss)", round(float(np.mean(l4_loss == 0)), 4))
    print("L4 bets mean", round(l4s.mean(), 2), "L4 losses mean", round(l4_loss.mean(), 2))
    print("2-loss mean/obs", round(twos.mean(), 1), 10)
    print("3-loss mean/obs", round(threes.mean(), 1), 2)
    print("4-loss mean/obs", round(fours.mean(), 1), 0)

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False
    fig = plt.figure(figsize=(14.2, 9.6), facecolor="#0f1218")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.15, 1], hspace=0.32, wspace=0.28)
    ax1 = fig.add_subplot(gs[0, :])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[1, 1])
    for ax in (ax1, ax2, ax3):
        ax.set_facecolor("#161b24")
        ax.tick_params(colors="#c5cdd8")
        for sp in ax.spines.values():
            sp.color = "#2a3342"
        ax.yaxis.label.set_color("#c5cdd8")
        ax.xaxis.label.set_color("#c5cdd8")
        ax.title.set_color("#e8eef6")

    x = np.arange(len(late_curve))
    ax1.plot(x, late_curve, color="#34d399", lw=2.0, label="参考盘的形状（同样的 411 把，第4档两枪放在后段）")
    ax1.plot(np.arange(len(early_curve)), early_curve, color="#60a5fa", lw=1.2, alpha=0.85, label="同样的把，两枪 13.3 放在开头")
    # a typical and a ruin from MC, resampled to 411
    ax1.plot(mc[idx_med]["curve"], color="#94a3b8", lw=1.0, alpha=0.9, label=f"同样打法随机一盘（中位 {mc[idx_med]['profit']:+.2f}）")
    ax1.plot(mc[idx_ruin]["curve"], color="#f87171", lw=1.1, alpha=0.95, label=f"第4档输了的一盘（{mc[idx_ruin]['profit']:+.2f}，回撤 {mc[idx_ruin]['max_dd']:.2f}）")
    ax1.axhline(0, color="#4b5563", lw=0.8)
    ax1.axhline(21.436, color="#34d399", lw=0.7, ls="--", alpha=0.6)
    ax1.annotate(
        "两次 13.3 打中 5 命中\n各约 +10.64，整盘 +21.44",
        xy=(len(late_curve) - 1, late_curve[-1]),
        xytext=(280, 12),
        color="#86efac",
        fontsize=10,
        arrowprops=dict(arrowstyle="->", color="#86efac"),
    )
    ax1.annotate(
        "爬到第4档前\n最大坑约 −1.32",
        xy=(int(np.argmin(late_curve[:350]) if min(late_curve[:350]) < 0 else 80), min(late_curve)),
        xytext=(40, -6),
        color="#fca5a5",
        fontsize=10,
        arrowprops=dict(arrowstyle="->", color="#fca5a5"),
    )
    ax1.set_title("参考 411 把收益曲线（拼出来的）vs 同样梯子随机盘")
    ax1.set_xlabel("局数")
    ax1.set_ylabel("累计盈亏 (USDT)")
    ax1.legend(loc="upper left", facecolor="#1f2733", edgecolor="#2a3342", labelcolor="#e8eef6", fontsize=9)
    ax1.set_xlim(0, 411)
    ax1.grid(True, color="#243044", lw=0.6)

    ax2.hist(profits, bins=60, color="#64748b", alpha=0.9, edgecolor="none")
    ax2.axvline(21.436, color="#34d399", lw=2, label="参考盘 +21.44")
    ax2.axvline(float(np.median(profits)), color="#fbbf24", lw=1.5, ls="--", label=f"中位 {float(np.median(profits)):+.2f}")
    ax2.axvline(0, color="#94a3b8", lw=0.8)
    ax2.set_title("8000 次「同样 411 把、同样四档」的最终盈亏")
    ax2.set_xlabel("最终盈亏")
    ax2.set_ylabel("次数")
    ax2.legend(facecolor="#1f2733", edgecolor="#2a3342", labelcolor="#e8eef6", fontsize=9)

    ax3.hist(mdds, bins=50, color="#fb7185", alpha=0.85, edgecolor="none")
    ax3.axvline(float(np.median(dds)), color="#34d399", lw=2, label=f"参考盘回撤 ≈ {float(np.median(dds)):.2f}（没输 13.3）")
    ax3.axvline(float(np.median(mdds)), color="#fbbf24", lw=1.5, ls="--", label=f"随机盘中位回撤 {float(np.median(mdds)):.2f}")
    ax3.set_title("最大回撤（从高峰跌到最低）")
    ax3.set_xlabel("最大回撤")
    ax3.set_ylabel("次数")
    ax3.legend(facecolor="#1f2733", edgecolor="#2a3342", labelcolor="#e8eef6", fontsize=9)

    fig.suptitle(
        "低等 10 选  0.01 / 0.11 / 1.20 / 13.30   ·  411 把  26 分 36 秒",
        color="#e8eef6",
        fontsize=14,
        y=0.98,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    print("wrote", OUT)


if __name__ == "__main__":
    main()
