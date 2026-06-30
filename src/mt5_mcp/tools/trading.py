"""Trading tools — place, modify, and close orders via MT5.

IMPORTANT: These tools execute real trades. They are disabled by default.
Enable with MT5_MCP_TRADING_ENABLED=true environment variable.
"""

from __future__ import annotations

import logging
import os

import MetaTrader5 as mt5

from mt5_mcp.server import mcp
from mt5_mcp.connection import ensure_access

logger = logging.getLogger("mt5-mcp")


def _trading_enabled() -> bool:
    """Check if trading tools are enabled via environment variable."""
    return os.environ.get("MT5_MCP_TRADING_ENABLED", "").lower() in ("true", "1", "yes")


@mcp.tool()
async def place_order(
    symbol: str,
    direction: str,
    volume: float,
    sl: float = 0.0,
    tp: float = 0.0,
    comment: str = "mt5-mcp",
) -> str:
    """Place a market order.

    REQUIRES: MT5_MCP_TRADING_ENABLED=true environment variable.

    Args:
        symbol: Instrument (e.g. EURUSD).
        direction: "buy" or "sell".
        volume: Lot size (e.g. 0.01, 0.1, 1.0).
        sl: Stop loss price (0 = no SL).
        tp: Take profit price (0 = no TP).
        comment: Order comment (default "mt5-mcp").

    Returns:
        Order result with ticket number or error.
    """
    if not _trading_enabled():
        return (
            "Trading is DISABLED. Set MT5_MCP_TRADING_ENABLED=true to enable.\n"
            "WARNING: This will execute REAL trades on your account."
        )

    if err := ensure_access():
        return f"Error: {err}"

    direction = direction.lower().strip()
    if direction not in ("buy", "sell"):
        return "Error: direction must be 'buy' or 'sell'."

    sym = symbol.upper()
    info = mt5.symbol_info(sym)
    if info is None:
        return f"Error: Symbol {sym} not found."

    if not info.visible:
        mt5.symbol_select(sym, True)

    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        return f"Error: No tick data for {sym}."

    price = tick.ask if direction == "buy" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": sym,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl if sl > 0 else 0.0,
        "tp": tp if tp > 0 else 0.0,
        "deviation": 20,
        "magic": 123456,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        return f"Error: order_send returned None. Last error: {mt5.last_error()}"

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return f"Order FAILED: {result.comment} (code: {result.retcode})"

    return (
        f"Order EXECUTED: #{result.order}\n"
        f"  {sym} {direction.upper()} {volume} lots @ {result.price}\n"
        f"  SL: {sl or 'None'}  TP: {tp or 'None'}"
    )


@mcp.tool()
async def close_position(ticket: int) -> str:
    """Close an open position by ticket number.

    REQUIRES: MT5_MCP_TRADING_ENABLED=true environment variable.

    Args:
        ticket: Position ticket number (from get_positions).

    Returns:
        Close result or error.
    """
    if not _trading_enabled():
        return "Trading is DISABLED. Set MT5_MCP_TRADING_ENABLED=true to enable."

    if err := ensure_access():
        return f"Error: {err}"

    positions = mt5.positions_get(ticket=ticket)
    if positions is None or len(positions) == 0:
        return f"Error: Position #{ticket} not found."

    pos = positions[0]
    close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(pos.symbol)
    if tick is None:
        return f"Error: No tick for {pos.symbol}."

    price = tick.bid if pos.type == 0 else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": close_type,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": 123456,
        "comment": "mt5-mcp close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        return f"Error: order_send returned None. Last error: {mt5.last_error()}"

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return f"Close FAILED: {result.comment} (code: {result.retcode})"

    profit_sign = "+" if pos.profit >= 0 else ""
    return (
        f"Position #{ticket} CLOSED\n"
        f"  {pos.symbol} {'BUY' if pos.type == 0 else 'SELL'} {pos.volume} lots\n"
        f"  Entry: {pos.price_open} -> Exit: {result.price}\n"
        f"  P&L: {profit_sign}${pos.profit:,.2f}"
    )


@mcp.tool()
async def modify_position(
    ticket: int,
    sl: float = 0.0,
    tp: float = 0.0,
) -> str:
    """Modify SL/TP of an open position.

    REQUIRES: MT5_MCP_TRADING_ENABLED=true environment variable.

    Args:
        ticket: Position ticket number.
        sl: New stop loss (0 = remove SL).
        tp: New take profit (0 = remove TP).

    Returns:
        Modification result or error.
    """
    if not _trading_enabled():
        return "Trading is DISABLED. Set MT5_MCP_TRADING_ENABLED=true to enable."

    if err := ensure_access():
        return f"Error: {err}"

    positions = mt5.positions_get(ticket=ticket)
    if positions is None or len(positions) == 0:
        return f"Error: Position #{ticket} not found."

    pos = positions[0]

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": pos.symbol,
        "position": ticket,
        "sl": sl,
        "tp": tp,
    }

    result = mt5.order_send(request)
    if result is None:
        return f"Error: order_send returned None. Last error: {mt5.last_error()}"

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return f"Modify FAILED: {result.comment} (code: {result.retcode})"

    return (
        f"Position #{ticket} MODIFIED\n"
        f"  SL: {sl or 'Removed'}  TP: {tp or 'Removed'}"
    )
