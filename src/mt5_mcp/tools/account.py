"""Account tools — balance, positions, orders, and history from local MT5."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

from mt5_mcp.server import mcp
from mt5_mcp.connection import ensure_access, get_connection_info

logger = logging.getLogger("mt5-mcp")


@mcp.tool()
async def get_account_info() -> str:
    """Get account information: balance, equity, margin, and connection details.

    Returns:
        Account balance, equity, free margin, leverage, and connection info.
    """
    if err := ensure_access():
        return f"Error: {err}"

    account = mt5.account_info()
    if account is None:
        return "Error: Could not get account info."

    conn = get_connection_info()

    return (
        f"Account: {account.login} | Server: {account.server}\n"
        f"  Name: {account.name}\n"
        f"  Balance: ${account.balance:,.2f}\n"
        f"  Equity: ${account.equity:,.2f}\n"
        f"  Free Margin: ${account.margin_free:,.2f}\n"
        f"  Margin Level: {account.margin_level:.1f}%\n"
        f"  Leverage: 1:{account.leverage}\n"
        f"  Profit: ${account.profit:,.2f}\n"
        f"  Currency: {account.currency}\n"
        f"  Company: {conn.company or 'N/A'}"
    )


@mcp.tool()
async def get_positions(symbol: str = "") -> str:
    """Get open positions.

    Args:
        symbol: Filter by symbol (optional). Empty = all positions.

    Returns:
        List of open positions with entry price, P&L, and volume.
    """
    if err := ensure_access():
        return f"Error: {err}"

    if symbol:
        positions = mt5.positions_get(symbol=symbol.upper())
    else:
        positions = mt5.positions_get()

    if positions is None or len(positions) == 0:
        return f"No open positions{' for ' + symbol.upper() if symbol else ''}."

    total_profit = 0.0
    lines = [f"Open Positions: {len(positions)}", ""]

    for pos in positions:
        direction = "BUY" if pos.type == 0 else "SELL"
        profit_sign = "+" if pos.profit >= 0 else ""
        total_profit += pos.profit

        lines.append(
            f"  #{pos.ticket} {pos.symbol} {direction} {pos.volume} lots\n"
            f"    Entry: {pos.price_open}  Current: {pos.price_current}  "
            f"P&L: {profit_sign}${pos.profit:,.2f}\n"
            f"    SL: {pos.sl or 'None'}  TP: {pos.tp or 'None'}  "
            f"Swap: ${pos.swap:,.2f}"
        )

    profit_sign = "+" if total_profit >= 0 else ""
    lines.append(f"\nTotal P&L: {profit_sign}${total_profit:,.2f}")

    return "\n".join(lines)


@mcp.tool()
async def get_orders() -> str:
    """Get pending orders (limit, stop, etc.).

    Returns:
        List of pending orders with type, price, and volume.
    """
    if err := ensure_access():
        return f"Error: {err}"

    orders = mt5.orders_get()
    if orders is None or len(orders) == 0:
        return "No pending orders."

    order_types = {
        0: "BUY_LIMIT", 1: "SELL_LIMIT",
        2: "BUY_STOP", 3: "SELL_STOP",
        4: "BUY_STOP_LIMIT", 5: "SELL_STOP_LIMIT",
    }

    lines = [f"Pending Orders: {len(orders)}", ""]

    for order in orders:
        otype = order_types.get(order.type, f"TYPE_{order.type}")
        lines.append(
            f"  #{order.ticket} {order.symbol} {otype} {order.volume_current} lots\n"
            f"    Price: {order.price_open}  SL: {order.sl or 'None'}  "
            f"TP: {order.tp or 'None'}"
        )

    return "\n".join(lines)


@mcp.tool()
async def get_trade_history(days: int = 7) -> str:
    """Get closed trades history.

    Args:
        days: Number of days to look back (default 7, max 90).

    Returns:
        List of closed trades with entry/exit prices and P&L.
    """
    if err := ensure_access():
        return f"Error: {err}"

    days = min(days, 90)
    from_date = datetime.now(tz=timezone.utc) - timedelta(days=days)
    to_date = datetime.now(tz=timezone.utc)

    deals = mt5.history_deals_get(from_date, to_date)
    if deals is None or len(deals) == 0:
        return f"No closed trades in the last {days} days."

    # Filter only trade deals (not balance operations)
    trades = [d for d in deals if d.entry > 0]  # entry=1 is out, entry=0 is in

    if not trades:
        return f"No closed trades in the last {days} days."

    total_profit = sum(d.profit for d in trades)
    wins = sum(1 for d in trades if d.profit > 0)
    losses = sum(1 for d in trades if d.profit < 0)

    lines = [
        f"Trade History: {len(trades)} closed trades (last {days} days)",
        f"  Wins: {wins} | Losses: {losses} | Win Rate: {wins/(wins+losses)*100:.1f}%" if (wins + losses) > 0 else "",
        f"  Total P&L: ${total_profit:,.2f}",
        "",
        "Recent trades:",
    ]

    for deal in trades[-10:]:  # Last 10
        direction = "BUY" if deal.type == 0 else "SELL"
        profit_sign = "+" if deal.profit >= 0 else ""
        ts = datetime.fromtimestamp(deal.time, tz=timezone.utc).strftime("%m-%d %H:%M")
        lines.append(
            f"  {ts} {deal.symbol} {direction} {deal.volume} lots  "
            f"Price: {deal.price}  P&L: {profit_sign}${deal.profit:,.2f}"
        )

    return "\n".join(lines)
