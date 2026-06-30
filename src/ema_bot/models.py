"""Data models for the EMA martingale bot."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Signal(str, Enum):
    LONG = "long"
    SHORT = "short"


class BotEventType(str, Enum):
    STARTED = "started"
    STOPPED = "stopped"
    NEW_BAR = "new_bar"
    SIGNAL = "signal"
    ORDER = "order"
    CLOSE_ALL = "close_all"
    ERROR = "error"
    TAKE_PROFIT = "take_profit"
    SECURE_PROFIT = "secure_profit"
    CROSS = "cross"
    SIGNAL_FLIP = "signal_flip"


@dataclass
class BotConfig:
    symbols: list[str] = field(default_factory=lambda: ["USDJPY"])
    poll_interval_sec: float = 60.0
    timeframe_minutes: int = 1
    ema_fast: int = 9
    ema_slow: int = 21
    initial_lot_size: float = 0.01
    next_multiplier: float = 3.0
    deviation: float = 1.5
    magic: int = 234567
    max_position_count: int = 0  # 0 = unlimited
    max_lot_size: float = 1.0
    demo_only: bool = True
    trading_enabled: bool = True
    db_path: str = "data/bot_state.db"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    secure_profit_enabled: bool = True
    sp_threshold_half: float = 5.0
    sp_threshold_three_quarter: float = 10.0
    sl_hit_close_all: bool = True


@dataclass
class SymbolState:
    symbol: str
    position_count: int = 0
    total_lot_size: float = 0.0
    lot_size: float = 0.0
    last_bar_time: int = 0
    last_signal: str = ""
    last_ema_fast: float = 0.0
    last_ema_slow: float = 0.0
    last_price: float = 0.0
    secure_profit_usd: float = 0.0
    secure_profit_pct: float = 0.0
    last_position_tickets: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PositionSnapshot:
    ticket: int
    symbol: str
    direction: str
    volume: float
    price_open: float
    price_current: float
    profit: float
    swap: float
    sl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SymbolSnapshot:
    symbol: str
    state: SymbolState
    signal: str
    ema_fast: float
    ema_slow: float
    price: float
    total_profit: float
    positions: list[PositionSnapshot]
    last_bar_time: int
    bot_running: bool
    ema_cross: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "state": self.state.to_dict(),
            "signal": self.signal,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "price": self.price,
            "total_profit": self.total_profit,
            "positions": [p.to_dict() for p in self.positions],
            "last_bar_time": self.last_bar_time,
            "bot_running": self.bot_running,
            "ema_cross": self.ema_cross,
        }


@dataclass
class BotEvent:
    event_type: str
    symbol: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
