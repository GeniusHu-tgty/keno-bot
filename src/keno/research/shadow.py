from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from ..bot.datasource import iter_replay_rounds
from ..bot.live import BotConfig, build_bot
from ..game.paytable import Paytable


def run_shadow(
    replay_file: str,
    *,
    strategy: str = "random",
    money: str = "flat",
    pick_count: int = 10,
    bet: str = "0.0001",
    bankroll: str = "10",
    risk: str = "medium",
    rounds: int | None = None,
    pace_seconds: float = 3.5,
    out_prefix: str = "reports/shadow",
) -> dict:
    """Replay real read-only collected rounds as paper decisions.

    This function reads a local replay file only.  It never sends a request or
    submits a wager to the real platform.
    """
    official = json.loads(paths.official_payouts().read_text(encoding="utf-8"))
    if risk not in official["risks"]:
        raise ValueError(f"unknown risk: {risk}")
    tables = {
        int(picks): {
            hits: Decimal(str(multiplier))
            for hits, multiplier in enumerate(values)
        }
        for picks, values in official["risks"][risk].items()
    }
    config = BotConfig(
        source="replay",
        rounds=rounds or 1000000,
        strategy=strategy,
        pick_count=pick_count,
        bet=bet,
        bankroll=bankroll,
        money=money,
        difficulty=risk,
        paytable_path="configs/payout_low_official.yaml",
        replay_file=replay_file,
        stop_win=None,
        stop_loss=None,
    )
    paytable = Paytable(
        version="official-shadow",
        difficulty=risk,
        payouts=tables,
    )
    bot = build_bot(config, paytable)
    out = Path(out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    log_path = out.with_name(out.name + "_rounds.jsonl")
    rows = []
    for record in iter_replay_rounds(replay_file, limit=rounds):
        bet_record = bot.handle_round(record)
        if bet_record is None:
            break
        row = {
            "round_id": record.round_id,
            "timestamp": record.timestamp.isoformat(),
            "observed_numbers": record.numbers,
            "proposed_numbers": bet_record.selected_numbers,
            "bet": str(bet_record.bet_amount),
            "hits": bet_record.hits,
            "multiplier": str(bet_record.multiplier),
            "profit": str(bet_record.profit),
            "bankroll_after": str(bot.bankroll),
            "stage": bet_record.decision_reason,
            "strategy": strategy,
            "money": money,
            "real_bet_submitted": False,
        }
        rows.append(row)
    with log_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    total_bet = sum((Decimal(row["bet"]) for row in rows), Decimal("0"))
    total_profit = sum((Decimal(row["profit"]) for row in rows), Decimal("0"))
    report = {
        "mode": "read_only_shadow",
        "real_money": False,
        "real_bet_submitted": False,
        "source": replay_file,
        "strategy": strategy,
        "money": money,
        "risk": risk,
        "pick_count": pick_count,
        "pace_seconds": pace_seconds,
        "rounds": len(rows),
        "total_bet": str(total_bet),
        "profit": str(total_profit),
        "roi": str(total_profit / total_bet if total_bet else Decimal("0")),
        "bankroll": str(bot.bankroll),
        "max_drawdown": str(bot.stats.max_drawdown),
        "longest_loss_streak": bot.stats.longest_loss_streak,
        "log": str(log_path),
        "note": "只读回放：提出纸面决策并与已采集结果对照，不连接下注接口。",
    }
    out.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    out.with_suffix(".md").write_text(
        "\n".join([
            "# Read-only Shadow Run",
            "",
            f"- source: `{replay_file}`",
            f"- strategy: `{strategy}` / money: `{money}`",
            f"- rounds: {len(rows)} / pace: {pace_seconds}s",
            f"- total bet: `{total_bet}` / profit: `{total_profit}` / ROI: `{report['roi']}`",
            f"- real_bet_submitted: `false`",
            "",
            "该报告只表示纸面决策在已采集历史上的表现。",
        ]) + "\n",
        encoding="utf-8",
    )
    return report
