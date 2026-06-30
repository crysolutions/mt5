"""CLI entry point for the EMA martingale bot."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import uvicorn

from ema_bot.config import load_config
from ema_bot.engine import TradingEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="EMA Martingale Bot for MT5")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run bot loop only (no API)")
    run_parser.add_argument("--config", default="config/bot.yaml")

    serve_parser = sub.add_parser("serve", help="Run bot + FastAPI server")
    serve_parser.add_argument("--config", default="config/bot.yaml")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s: %(message)s",
    )

    if args.command == "run":
        asyncio.run(_run_bot_only(args.config))
    elif args.command == "serve":
        _run_serve(args.config)


async def _run_bot_only(config_path: str) -> None:
    config = load_config(config_path)
    engine = TradingEngine(config)
    err = await engine.start()
    if err:
        print(f"Failed to start: {err}", file=sys.stderr)
        sys.exit(1)
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await engine.stop()


def _run_serve(config_path: str) -> None:
    import os

    os.environ["EMA_BOT_CONFIG"] = config_path
    config = load_config(config_path)
    uvicorn.run(
        "bot_server.main:app",
        host=config.api_host,
        port=config.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
