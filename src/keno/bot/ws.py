from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import websockets
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from ..data.schema import RoundRecord, jsonable
from ..game.paytable import Paytable
from .bot import KenoBot
from .live import BotConfig, build_bot, build_summary
from .datasource import iter_synthetic_rounds


async def _serve_mock_keno(port: int, rounds: int, interval: float, seed: str, client_seed: str) -> None:
    """Broadcast locally generated keno rounds as JSON events over WebSocket.

    This is a training stand-in for the real platform socket: it lets the bot
    practice the connect -> receive -> parse -> classify -> persist loop without
    touching stake.com or any real account.
    """
    clients: set = set()

    async def handler(ws) -> None:
        clients.add(ws)
        try:
            await ws.wait_closed()
        finally:
            clients.discard(ws)

    async with serve(handler, "127.0.0.1", port):
        # Hold the stream until the first client connects; a zero-interval
        # broadcast would otherwise finish before any client can arrive.
        for _ in range(200):
            if clients:
                break
            await asyncio.sleep(0.05)
        for record in iter_synthetic_rounds(rounds, seed=seed, client_seed=client_seed):
            if clients:
                message = json.dumps({"type": "keno_round", **jsonable(record)}, ensure_ascii=False)
                await asyncio.gather(*(c.send(message) for c in list(clients)))
            await asyncio.sleep(interval)
        for ws in list(clients):
            await ws.send(json.dumps({"type": "end"}))


async def _run_ws_client(config: BotConfig, bot: KenoBot, log_path: Path) -> None:
    uri = f"ws://127.0.0.1:{config.ws_port}"
    received = 0
    with log_path.open("w", encoding="utf-8") as log_file:

        def logger(payload: dict) -> None:
            log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")

        async with connect(uri) as ws:
            async for raw in ws:
                event = json.loads(raw)
                kind = event.get("type")
                if kind == "keno_round":
                    record = RoundRecord(
                        round_id=str(event["round_id"]),
                        timestamp=datetime.fromisoformat(event["timestamp"]),
                        numbers=[int(n) for n in event["numbers"]],
                        server_seed=event.get("server_seed"),
                        client_seed=event.get("client_seed"),
                        nonce=event.get("nonce"),
                        cursor=event.get("cursor"),
                        source="mock-ws",
                    )
                    bot.handle_round(record, logger)
                    received += 1
                    if received % config.display_every == 0 and bot.stop_reason is None:
                        print(bot.stats.render(config.pick_count, bot.money_manager.phase))
                    if bot.stop_reason is not None or received >= config.rounds:
                        break
                elif kind == "end":
                    break
                else:
                    print(f"unclassified event type: {kind}")


def run_mock_ws_bot(config: BotConfig) -> dict:
    """Run a local mock keno WebSocket server plus the bot client against it."""
    config.validate()
    if config.source != "ws":
        raise ValueError("run_mock_ws_bot requires source='ws'")
    paytable = Paytable.from_yaml(config.paytable_path)
    bot = build_bot(config, paytable)
    log_path = Path(config.out_prefix + "_rounds.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    async def main() -> None:
        server_task = asyncio.create_task(
            _serve_mock_keno(config.ws_port, config.rounds, config.interval, config.seed, "ws-client-seed")
        )
        try:
            # Let the server task enter serve() and bind the port before connecting.
            await asyncio.sleep(0.5)
            await _run_ws_client(config, bot, log_path)
        finally:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass

    asyncio.run(main())
    summary = build_summary(config, bot, log_path)
    from .live import write_bot_outputs

    write_bot_outputs(config, bot, summary)
    print(bot.stats.render(config.pick_count, bot.money_manager.phase))
    print(f"stop_reason={bot.stop_reason or 'rounds completed'}")
    print(f"summary={Path(config.out_prefix).with_suffix('.json')}")
    return summary
