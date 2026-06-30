"""Shared app state for bot server."""

from __future__ import annotations

from ema_bot.engine import TradingEngine
from ema_bot.persistence import BotStore

engine: TradingEngine | None = None
store: BotStore | None = None


def get_engine() -> TradingEngine:
    if engine is None:
        raise RuntimeError("Engine not initialized")
    return engine


def get_store() -> BotStore:
    if store is None:
        raise RuntimeError("Store not initialized")
    return store
