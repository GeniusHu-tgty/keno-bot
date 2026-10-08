# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
from .synthetic import generate_rounds
from .reporting.report import write_simulation_report
from .paper import run_paper_experiment
from .bot import BotConfig, run_paper_bot, run_mock_ws_bot

def main() -> None:
    parser = argparse.ArgumentParser(prog="keno")
    sub = parser.add_subparsers(dest="command", required=True)
    sim = sub.add_parser("simulate")
    sim.add_argument("--rounds", type=int, default=100_000)
    sim.add_argument("--pick-count", type=int, default=5)
    sim.add_argument("--seed", default="keno-synthetic-v1")
    sim.add_argument("--out", default="reports")
    paper = sub.add_parser("paper-trade")
    paper.add_argument("--rounds", type=int, default=100_000)
    paper.add_argument("--pick-count", type=int, default=1)
    paper.add_argument("--bet", default="0.00010000")
    paper.add_argument("--seed", default="keno-synthetic-v1")
    paper.add_argument("--paytable", default="configs/payout.yaml")
    paper.add_argument("--out", default="reports/paper_trade.json")
    bot = sub.add_parser("bot", help="run the paper-trading bot (no real money)")
    bot.add_argument("--source", choices=["synthetic", "replay", "ws"], default="synthetic")
    bot.add_argument("--rounds", type=int, default=1000)
    bot.add_argument(
        "--strategy",
        choices=[
            "random",
            "hot",
            "cold",
            "pattern",
            "block-random",
            "fixed-pattern",
            "avoid-cold-zone",
            "balanced-random",
        ],
        default="random",
    )
    bot.add_argument("--pick-count", type=int, default=1)
    bot.add_argument("--bet", default="0.00010000")
    bot.add_argument("--bankroll", default="0.01000000")
    bot.add_argument(
        "--money",
        choices=["flat", "recovery", "phase", "fractional", "adaptive", "probe", "capped"],
        default="flat",
    )
    bot.add_argument("--recovery-multiplier", default="2")
    bot.add_argument("--max-recovery-steps", type=int, default=8)
    bot.add_argument("--paytable", default="configs/payout.yaml")
    bot.add_argument("--phase-config", default="configs/bot_phase.yaml")
    bot.add_argument("--seed", default="keno-bot-v1")
    bot.add_argument("--rng-seed", type=int, default=7)
    bot.add_argument("--interval", type=float, default=0.0)
    bot.add_argument("--display-every", type=int, default=100)
    bot.add_argument("--replay-file", default=None)
    bot.add_argument("--ws-port", type=int, default=8765)
    bot.add_argument("--stop-win", default=None, help="end the session when cumulative profit >= this")
    bot.add_argument("--stop-loss", default=None, help="end the session when cumulative profit <= this")
    bot.add_argument("--unattended", action="store_true", help="cycle sessions until hours/max-sessions/bankroll stop")
    bot.add_argument("--hours", type=float, default=0.0, help="unattended wall-clock hours (default 24 if unattended)")
    bot.add_argument("--max-sessions", type=int, default=0, help="unattended session cap, 0=unlimited")
    bot.add_argument("--out", default="reports/bot")
    sessions = sub.add_parser("sessions", help="Monte Carlo over bot sessions (null model)")
    sessions.add_argument("--sessions", type=int, default=1000)
    sessions.add_argument("--rounds", type=int, default=176)
    sessions.add_argument("--pick-count", type=int, default=10)
    sessions.add_argument("--bankroll", default="1.00000000")
    sessions.add_argument("--paytable", default="configs/payout.yaml")
    sessions.add_argument("--phase-config", default="configs/bot_phase.yaml")
    sessions.add_argument("--seed", default="keno-sessions-v1")
    sessions.add_argument("--rng-seed", type=int, default=11)
    sessions.add_argument("--benchmark-profit", default="0.7129")
    sessions.add_argument("--flat-control-bet", default="0.01")
    sessions.add_argument("--out", default="reports/sessions")
    daily = sub.add_parser("daily", help="simulate full days of unattended bot operation")
    daily.add_argument("--days", type=int, default=30)
    daily.add_argument("--hours", type=float, default=24.0)
    daily.add_argument("--pace-seconds", type=float, default=3.5)
    daily.add_argument("--stop-win", default="0.5")
    daily.add_argument("--stop-loss", default="2.0")
    daily.add_argument("--pick-count", type=int, default=10)
    daily.add_argument("--bankroll", default="10.00000000")
    daily.add_argument("--paytable", default="configs/payout.yaml")
    daily.add_argument("--phase-config", default="configs/bot_phase.yaml")
    daily.add_argument("--seed", default="keno-daily-v1")
    daily.add_argument("--rng-seed", type=int, default=23)
    daily.add_argument("--out", default="reports/daily")
    grid = sub.add_parser("strategy-grid", help="large paper-only comparison of staking policies")
    grid.add_argument("--sessions", type=int, default=5000)
    grid.add_argument("--rounds", type=int, default=176)
    grid.add_argument("--risk", choices=["classic", "low", "medium", "high"], default="medium")
    grid.add_argument("--pick-count", type=int, default=10)
    grid.add_argument("--bankroll", default="10")
    grid.add_argument("--pace-seconds", type=float, default=3.5)
    grid.add_argument("--seed", default="keno-grid-2026-09-11")
    grid.add_argument("--selection-seed", type=int, default=9911)
    grid.add_argument("--candidates", default=None, help="comma-separated candidate names")
    grid.add_argument(
        "--selection-modes",
        default="random",
        help="comma-separated: random,block-random,fixed-pattern,hot,cold,avoid-cold-zone,balanced-random",
    )
    grid.add_argument("--stop-win", default=None)
    grid.add_argument("--stop-loss", default=None)
    grid.add_argument("--max-drawdown", default=None)
    grid.add_argument("--out", default="reports/strategy_grid")
    validation = sub.add_parser("strategy-validate", help="freeze parameters through train/validation/test")
    validation.add_argument("--train-seeds", default="0,1,2")
    validation.add_argument("--validation-seeds", default="3,4,5")
    validation.add_argument("--test-seeds", default="6,7,8")
    validation.add_argument("--sessions-per-seed", type=int, default=1000)
    validation.add_argument("--rounds", type=int, default=176)
    validation.add_argument("--risk", choices=["classic", "low", "medium", "high"], default="medium")
    validation.add_argument("--pick-count", type=int, default=10)
    validation.add_argument("--bankroll", default="10")
    validation.add_argument("--pace-seconds", type=float, default=3.5)
    validation.add_argument("--candidates", default=None)
    validation.add_argument("--selection-modes", default="random,block-random,fixed-pattern,hot,cold,avoid-cold-zone,balanced-random")
    validation.add_argument("--stop-win", default=None)
    validation.add_argument("--stop-loss", default=None)
    validation.add_argument("--max-drawdown", default=None)
    validation.add_argument("--out", default="reports/strategy_validation")
    risk_grid = sub.add_parser("risk-grid", help="grid-search paper-only stop/target/session risk controls")
    risk_grid.add_argument("--sessions", type=int, default=1000)
    risk_grid.add_argument("--risk", choices=["classic", "low", "medium", "high"], default="medium")
    risk_grid.add_argument("--pick-count", type=int, default=10)
    risk_grid.add_argument("--bankroll", default="10")
    risk_grid.add_argument("--pace-seconds", type=float, default=3.5)
    risk_grid.add_argument("--candidate", default="flat-min")
    risk_grid.add_argument("--selection-mode", default="random")
    risk_grid.add_argument("--seed", default="keno-risk-grid-2026-09-11")
    risk_grid.add_argument("--selection-seed", type=int, default=9911)
    risk_grid.add_argument("--out", default="reports/risk_grid")
    export_history = sub.add_parser(
        "export-history", help="将采集历史转换为截图风格七列表格"
    )
    export_history.add_argument("--input", required=True, help="输入 JSONL 历史文件")
    export_history.add_argument(
        "--out", default=None, help="输出前缀，默认在输入文件旁生成 *_formatted"
    )
    export_history.add_argument(
        "--oldest-first", action="store_true", help="按最早到最新输出"
    )
    serve = sub.add_parser("serve", help="run the local Keno BOT web workbench")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    collect = sub.add_parser("collect", help="log real keno rounds (manual clipboard or automated CDP collection)")
    collect.add_argument("--out", default="data/raw/manual.jsonl")
    collect.add_argument("--clipboard", action="store_true", help="read rounds from the clipboard (select history rows on the site, copy, run)")
    collect.add_argument("--cdp", default=None, help="CDP endpoint of a logged-in Chrome for read-only collection, e.g. http://127.0.0.1:9222")
    collect.add_argument("--seeds-file", default=None, help="output path for collected seed data (default: <out stem>.seeds.json)")
    verify = sub.add_parser("verify-rounds", help="deterministically verify logged rounds against revealed seeds")
    verify.add_argument("--replay-file", required=True)
    verify.add_argument("--seeds-file", default=None, help="per-round seed data from collect --cdp (fills rounds missing seed fields)")
    verify.add_argument("--server-seed", default=None, help="fallback server seed for rounds without one")
    verify.add_argument("--client-seed", default=None, help="fallback client seed for rounds without one")
    verify.add_argument("--start-nonce", type=int, default=1)
    verify.add_argument("--nonce-step", type=int, default=1)
    live = sub.add_parser("live", help="connect the bot to a real Stake Chrome session")
    live.add_argument("action", choices=["connect", "status", "run"], help="connect / status / run")
    live.add_argument("--cdp", default="http://127.0.0.1:9222")
    live.add_argument("--wait-login", type=float, default=180.0, help="seconds to wait for manual login")
    live.add_argument("--live-bets", action="store_true", help="actually place keno bets (real money)")
    live.add_argument("--rounds", type=int, default=1)
    live.add_argument("--risk", default="low")
    live.add_argument("--pick-count", type=int, default=10)
    live.add_argument("--stop-loss", default="0.5")
    live.add_argument("--pace-seconds", type=float, default=3.5)
    args = parser.parse_args()
    if args.command == "simulate":
        records = generate_rounds(args.rounds, seed=args.seed)
        selected = list(range(1, args.pick_count + 1))
        hits = [len(set(selected).intersection(record.numbers)) for record in records]
        summary = write_simulation_report(args.out, hits, args.pick_count, seed=args.seed)
        print(f"rounds={summary['rounds']} pick_count={summary['pick_count']} chi_square={summary['chi_square']:.4f}")
        print(f"report={args.out}/simulation_report.md")
    elif args.command == "paper-trade":
        summary = run_paper_experiment(
            rounds=args.rounds,
            pick_count=args.pick_count,
            bet_amount=Decimal(args.bet),
            paytable_path=args.paytable,
            seed=args.seed,
        )
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown = [
            "# Paper Trading / Strict Backtest",
            "",
            "- real_money: `false`",
            f"- rounds: {summary['rounds']}",
            f"- pick_count: {summary['pick_count']}",
            f"- bet_amount: `{summary['bet_amount']}`",
            f"- seed: `{summary['seed']}`",
            "",
            "| Strategy | Split | ROI | Profit | Average Hits | Max Drawdown | Loss Streak |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for strategy, splits in summary["strategies"].items():
            for split, row in splits.items():
                markdown.append(
                    f"| {strategy} | {split} | {row['roi']} | {row['profit']} | "
                    f"{row['average_hits']:.6f} | {row['max_drawdown']} | "
                    f"{row['longest_loss_streak']} |"
                )
        output.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
        print(f"real_money={summary['real_money']}")
        print(f"rounds={summary['rounds']} pick_count={summary['pick_count']}")
        print(f"report={output}")
    elif args.command == "bot":
        config = BotConfig(
            source=args.source,
            rounds=args.rounds,
            strategy=args.strategy,
            pick_count=args.pick_count,
            bet=args.bet,
            bankroll=args.bankroll,
            money=args.money,
            recovery_multiplier=args.recovery_multiplier,
            max_recovery_steps=args.max_recovery_steps,
            paytable_path=args.paytable,
            phase_config=args.phase_config,
            seed=args.seed,
            rng_seed=args.rng_seed,
            interval=args.interval,
            display_every=args.display_every,
            replay_file=args.replay_file,
            out_prefix=args.out,
            ws_port=args.ws_port,
            stop_win=args.stop_win,
            stop_loss=args.stop_loss,
            unattended=args.unattended,
            hours=args.hours,
            max_sessions=args.max_sessions,
        )
        if args.source == "ws":
            run_mock_ws_bot(config)
        else:
            run_paper_bot(config)
    elif args.command == "sessions":
        from .research import run_session_monte_carlo

        benchmark = args.benchmark_profit
        if benchmark is not None and benchmark.lower() in ("none", "off"):
            benchmark = None
        run_session_monte_carlo(
            sessions=args.sessions,
            rounds_per_session=args.rounds,
            paytable_path=args.paytable,
            phase_config=args.phase_config,
            pick_count=args.pick_count,
            bankroll=args.bankroll,
            seed=args.seed,
            rng_seed=args.rng_seed,
            benchmark_profit=benchmark,
            flat_control_bet=args.flat_control_bet,
            out_prefix=args.out,
        )
    elif args.command == "daily":
        from .research import run_daily_simulation

        run_daily_simulation(
            days=args.days,
            hours=args.hours,
            pace_seconds=args.pace_seconds,
            stop_win=args.stop_win,
            stop_loss=args.stop_loss,
            paytable_path=args.paytable,
            phase_config=args.phase_config,
            pick_count=args.pick_count,
            bankroll=args.bankroll,
            seed=args.seed,
            rng_seed=args.rng_seed,
            out_prefix=args.out,
        )
    elif args.command == "strategy-grid":
        from .research import run_strategy_grid

        candidates = None
        if args.candidates:
            candidates = tuple(x.strip() for x in args.candidates.split(",") if x.strip())
        selection_modes = tuple(
            x.strip() for x in args.selection_modes.split(",") if x.strip()
        )
        report = run_strategy_grid(
            sessions=args.sessions,
            rounds_per_session=args.rounds,
            risk=args.risk,
            pick_count=args.pick_count,
            bankroll=args.bankroll,
            seed=args.seed,
            selection_seed=args.selection_seed,
            pace_seconds=args.pace_seconds,
            candidates=candidates,
            selection_modes=selection_modes,
            stop_win=args.stop_win,
            stop_loss=args.stop_loss,
            max_drawdown=args.max_drawdown,
            out_prefix=args.out,
        )
        print(f"strategy-grid: {len(report['rows'])} candidates, {args.sessions} sessions")
        for row in report["rows"]:
            print(
                f"{row['name']}: ROI={row['mean_roi_pct']:.3f}% "
                f"CI=+/-{row['roi_ci95_pct']:.3f}% ruin={row['ruin_pct']:.1%}"
            )
    elif args.command == "strategy-validate":
        from .research import run_strategy_validation

        parse_seeds = lambda text: tuple(int(x.strip()) for x in text.split(",") if x.strip())
        candidates = (
            tuple(x.strip() for x in args.candidates.split(",") if x.strip())
            if args.candidates
            else None
        )
        report = run_strategy_validation(
            train_seeds=parse_seeds(args.train_seeds),
            validation_seeds=parse_seeds(args.validation_seeds),
            test_seeds=parse_seeds(args.test_seeds),
            sessions_per_seed=args.sessions_per_seed,
            rounds_per_session=args.rounds,
            risk=args.risk,
            pick_count=args.pick_count,
            bankroll=args.bankroll,
            candidates=candidates or (
                "flat-min",
                "flat-001",
                "fractional",
                "adaptive",
                "probe-window",
                "capped-recovery",
                "phase",
                "martingale",
            ),
            selection_modes=tuple(
                x.strip() for x in args.selection_modes.split(",") if x.strip()
            ),
            pace_seconds=args.pace_seconds,
            stop_win=args.stop_win,
            stop_loss=args.stop_loss,
            max_drawdown=args.max_drawdown,
            out_prefix=args.out,
        )
        print(
            f"selected={report['selected_train_winner']} "
            f"test={report['test'][0]['mean_roi_pct']:.3f}%"
        )
    elif args.command == "risk-grid":
        from .research import run_risk_grid

        report = run_risk_grid(
            sessions=args.sessions,
            risk=args.risk,
            pick_count=args.pick_count,
            bankroll=args.bankroll,
            pace_seconds=args.pace_seconds,
            candidate=args.candidate,
            selection_mode=args.selection_mode,
            seed=args.seed,
            selection_seed=args.selection_seed,
            out_prefix=args.out,
        )
        print(
            f"risk-grid: {report['completed_cells']}/{report['total_cells']} cells; "
            f"top={report['rows'][0]['name'] if report['rows'] else 'none'}"
        )
    elif args.command == "export-history":
        from .reporting.history_export import write_history_exports

        report = write_history_exports(
            args.input,
            out_prefix=args.out,
            newest_first=not args.oldest_first,
        )
        print(
            f"export-history: {report['rows']} rows -> "
            f"{report['csv']} and {report['jsonl']}"
        )
    elif args.command == "serve":
        from .webapp.server import main as serve_main

        serve_main(host=args.host, port=args.port)
    elif args.command == "live":
        from .bot.stake_session import connect_stake, public_status

        if args.action == "connect":
            result = connect_stake(cdp=args.cdp, wait_login=args.wait_login)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result.get("status") != "connected":
                raise SystemExit(2)
        elif args.action == "status":
            print(json.dumps(public_status(), ensure_ascii=False, indent=2))
        else:
            from .bot.stake_live import run_stake_live

            result = run_stake_live(
                {
                    "live_bets": bool(args.live_bets),
                    "cdp": args.cdp,
                    "wait_login": args.wait_login,
                    "rounds": args.rounds,
                    "risk": args.risk,
                    "pick_count": args.pick_count,
                    "stop_loss": args.stop_loss,
                    "pace_seconds": args.pace_seconds,
                    "force_min": True,
                    "money": "flat",
                    "picks": "pattern",
                    "base_bet": "0.0001",
                }
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if not result.get("ok"):
                raise SystemExit(2)
    elif args.command == "collect":
        if args.cdp:
            from .collect_cdp import collect_from_cdp

            collect_from_cdp(args.out, cdp=args.cdp, seeds_out=args.seeds_file)
        else:
            from .collect import collect_from_clipboard, main_collect

            if args.clipboard:
                collect_from_clipboard(args.out)
            else:
                main_collect(args.out)
    elif args.command == "verify-rounds":
        from .bot.datasource import iter_replay_rounds
        from .provably_fair.verifier import verify_round

        rounds = list(iter_replay_rounds(args.replay_file))
        if not rounds:
            raise SystemExit(f"no rounds found in {args.replay_file}")
        seeds_by_id: dict[str, dict] = {}
        if args.seeds_file:
            payload = json.loads(Path(args.seeds_file).read_text(encoding="utf-8"))
            for item in payload.get("rounds", []):
                round_id = str(item.get("round_id", ""))
                if round_id:
                    seeds_by_id[round_id] = item
        passed = 0
        verified = 0
        skipped: list[str] = []
        for index, record in enumerate(rounds):
            fallback = seeds_by_id.get(record.round_id, {})
            server_seed = record.server_seed or fallback.get("server_seed") or args.server_seed
            client_seed = record.client_seed or fallback.get("client_seed") or args.client_seed
            nonce = record.nonce if record.nonce is not None else fallback.get("nonce")
            if nonce is None:
                nonce = args.start_nonce + index * args.nonce_step
            if not server_seed or not client_seed:
                skipped.append(record.round_id)
                continue
            result = verify_round(str(server_seed), str(client_seed), int(nonce), record.numbers)
            verified += 1
            passed += result.passed
            if not result.passed:
                print(f"round {record.round_id} nonce={nonce}: FAIL expected={result.expected} observed={result.observed}")
        summary = f"{passed}/{verified} rounds PASS"
        if skipped:
            summary += f" ({len(skipped)} round(s) skipped: no seeds)"
        print(summary)
        if verified == 0:
            raise SystemExit("no rounds verifiable: provide --seeds-file or --server-seed/--client-seed")
        if passed != verified:
            raise SystemExit(1)

if __name__ == "__main__":
    main()
