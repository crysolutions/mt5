"""FastAPI application — bot engine + REST + WebSocket."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from bot_server import state
from bot_server.routes import router
from ema_bot.config import load_config
from ema_bot.engine import TradingEngine
from ema_bot.models import BotEvent
from ema_bot.persistence import BotStore

logger = logging.getLogger("bot-server")

ws_clients: set[WebSocket] = set()


async def broadcast(payload: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_path = os.environ.get("EMA_BOT_CONFIG", "config/bot.yaml")
    config = load_config(config_path)
    state.store = BotStore(config.db_path)
    state.engine = TradingEngine(config)

    async def on_snapshot(payload: dict[str, Any]) -> None:
        await broadcast(payload)

    state.engine.on_snapshot(on_snapshot)
    err = await state.engine.start()
    if err:
        logger.error("Bot failed to start: %s", err)
        state.store.log_event(BotEvent(event_type="error", symbol="ALL", message=err))
    yield
    if state.engine:
        await state.engine.stop()
    import ema_bot.broker as broker

    broker.shutdown_mt5()


app = FastAPI(title="EMA Martingale Bot", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    ws_clients.add(ws)
    try:
        if state.engine:
            status = state.engine.build_status()
            await ws.send_json({"type": "status", **status})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)
