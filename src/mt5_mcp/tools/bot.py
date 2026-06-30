"""MCP tools for EMA bot status and events (read-only)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ema_bot.persistence import BotStore

from mt5_mcp.server import mcp


def _get_store() -> BotStore:
    db_path = os.environ.get("EMA_BOT_DB_PATH", "data/bot_state.db")
    return BotStore(db_path)


@mcp.tool()
async def get_bot_status() -> str:
    """Get EMA martingale bot status: running state, per-symbol martingale counters, open P&L.

    Reads from the bot SQLite database (data/bot_state.db by default).
    Requires the bot server to have been run at least once.

    Returns:
        Bot running status and per-symbol state.
    """
    store = _get_store()
    running = store.get_meta("bot_running", "false") == "true"
    states = store.get_all_states()

    if not states and not Path(store.db_path).exists():
        return (
            "Bot database not found. Start the bot with: ema-bot serve --config config/bot.yaml"
        )

    lines = [f"EMA Bot Status: {'RUNNING' if running else 'STOPPED'}", ""]
    if not states:
        lines.append("No symbol state yet. Bot may be starting or no symbols configured.")
    for state in states:
        lines.append(
            f"  {state.symbol}: PositionCount={state.position_count} "
            f"LotSize={state.lot_size} TotalLotSize={state.total_lot_size} "
            f"Signal={state.last_signal or 'n/a'}"
        )
        lines.append(
            f"    EMA9={state.last_ema_fast:.5f} EMA21={state.last_ema_slow:.5f} "
            f"Price={state.last_price:.5f}"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_bot_events(limit: int = 20, symbol: str = "") -> str:
    """Get recent EMA bot trade events from the event log.

    Args:
        limit: Max events to return (default 20, max 100).
        symbol: Filter by symbol (optional).

    Returns:
        Recent bot events: orders, closes, errors, new bars.
    """
    limit = min(limit, 100)
    store = _get_store()
    sym = symbol.upper() if symbol else None
    events = store.get_events(limit=limit, symbol=sym)

    if not events:
        return "No bot events found. Start the bot with: ema-bot serve --config config/bot.yaml"

    lines = [f"Bot Events (last {len(events)}):", ""]
    for ev in events:
        data = json.loads(ev.get("data") or "{}")
        extra = f" {data}" if data else ""
        lines.append(
            f"  [{ev['created_at']}] {ev['symbol']} {ev['event_type']}: "
            f"{ev['message']}{extra}"
        )
    return "\n".join(lines)
