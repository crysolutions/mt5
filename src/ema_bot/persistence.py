"""SQLite persistence for bot state and events."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from ema_bot.models import BotEvent, SymbolState


class BotStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS symbol_state (
                    symbol TEXT PRIMARY KEY,
                    position_count INTEGER NOT NULL DEFAULT 0,
                    total_lot_size REAL NOT NULL DEFAULT 0,
                    lot_size REAL NOT NULL DEFAULT 0,
                    last_bar_time INTEGER NOT NULL DEFAULT 0,
                    last_signal TEXT NOT NULL DEFAULT '',
                    last_ema_fast REAL NOT NULL DEFAULT 0,
                    last_ema_slow REAL NOT NULL DEFAULT 0,
                    last_price REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS bot_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bot_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(symbol_state)")}
        if "secure_profit_usd" not in cols:
            conn.execute(
                "ALTER TABLE symbol_state ADD COLUMN secure_profit_usd REAL NOT NULL DEFAULT 0"
            )
        if "secure_profit_pct" not in cols:
            conn.execute(
                "ALTER TABLE symbol_state ADD COLUMN secure_profit_pct REAL NOT NULL DEFAULT 0"
            )
        if "last_position_tickets" not in cols:
            conn.execute(
                "ALTER TABLE symbol_state ADD COLUMN last_position_tickets TEXT NOT NULL DEFAULT '[]'"
            )

    @staticmethod
    def _parse_ticket_list(raw: str | None) -> list[int]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return [int(t) for t in data]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def get_symbol_state(self, symbol: str) -> SymbolState:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM symbol_state WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()
            if row is None:
                return SymbolState(symbol=symbol.upper())
            keys = row.keys()
            return SymbolState(
                symbol=row["symbol"],
                position_count=row["position_count"],
                total_lot_size=row["total_lot_size"],
                lot_size=row["lot_size"],
                last_bar_time=row["last_bar_time"],
                last_signal=row["last_signal"],
                last_ema_fast=row["last_ema_fast"],
                last_ema_slow=row["last_ema_slow"],
                last_price=row["last_price"],
                secure_profit_usd=row["secure_profit_usd"] if "secure_profit_usd" in keys else 0.0,
                secure_profit_pct=row["secure_profit_pct"] if "secure_profit_pct" in keys else 0.0,
                last_position_tickets=self._parse_ticket_list(
                    row["last_position_tickets"] if "last_position_tickets" in keys else "[]"
                ),
            )

    def save_symbol_state(self, state: SymbolState) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO symbol_state (
                    symbol, position_count, total_lot_size, lot_size,
                    last_bar_time, last_signal, last_ema_fast, last_ema_slow, last_price,
                    secure_profit_usd, secure_profit_pct, last_position_tickets
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    position_count=excluded.position_count,
                    total_lot_size=excluded.total_lot_size,
                    lot_size=excluded.lot_size,
                    last_bar_time=excluded.last_bar_time,
                    last_signal=excluded.last_signal,
                    last_ema_fast=excluded.last_ema_fast,
                    last_ema_slow=excluded.last_ema_slow,
                    last_price=excluded.last_price,
                    secure_profit_usd=excluded.secure_profit_usd,
                    secure_profit_pct=excluded.secure_profit_pct,
                    last_position_tickets=excluded.last_position_tickets
                """,
                (
                    state.symbol.upper(),
                    state.position_count,
                    state.total_lot_size,
                    state.lot_size,
                    state.last_bar_time,
                    state.last_signal,
                    state.last_ema_fast,
                    state.last_ema_slow,
                    state.last_price,
                    state.secure_profit_usd,
                    state.secure_profit_pct,
                    json.dumps(state.last_position_tickets),
                ),
            )

    def log_event(self, event: BotEvent) -> None:
        if not event.created_at:
            event.created_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO bot_events (event_type, symbol, message, data, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.event_type,
                    event.symbol,
                    event.message,
                    json.dumps(event.data),
                    event.created_at,
                ),
            )

    def get_events(self, limit: int = 50, symbol: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if symbol:
                rows = conn.execute(
                    """
                    SELECT * FROM bot_events WHERE symbol = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (symbol.upper(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bot_events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_events_since(self, days: int = 90, symbol: str | None = None) -> list[dict]:
        since = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            if symbol:
                rows = conn.execute(
                    """
                    SELECT * FROM bot_events
                    WHERE symbol = ? AND created_at >= ?
                    ORDER BY id DESC
                    """,
                    (symbol.upper(), since),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM bot_events
                    WHERE created_at >= ?
                    ORDER BY id DESC
                    """,
                    (since,),
                ).fetchall()
        return [dict(row) for row in rows]

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO bot_meta (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def get_meta(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM bot_meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def get_all_states(self) -> list[SymbolState]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM symbol_state").fetchall()
        return [
            SymbolState(
                symbol=row["symbol"],
                position_count=row["position_count"],
                total_lot_size=row["total_lot_size"],
                lot_size=row["lot_size"],
                last_bar_time=row["last_bar_time"],
                last_signal=row["last_signal"],
                last_ema_fast=row["last_ema_fast"],
                last_ema_slow=row["last_ema_slow"],
                last_price=row["last_price"],
                secure_profit_usd=row["secure_profit_usd"] if "secure_profit_usd" in row.keys() else 0.0,
                secure_profit_pct=row["secure_profit_pct"] if "secure_profit_pct" in row.keys() else 0.0,
                last_position_tickets=self._parse_ticket_list(
                    row["last_position_tickets"] if "last_position_tickets" in row.keys() else "[]"
                ),
            )
            for row in rows
        ]
