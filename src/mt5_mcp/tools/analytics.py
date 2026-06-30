"""Trade analytics — performance stats, P&L breakdown, and risk analysis."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import MetaTrader5 as mt5
import numpy as np

from mt5_mcp.server import mcp
from mt5_mcp.connection import ensure_access

logger = logging.getLogger("mt5-mcp")


def _get_closed_deals(days: int):
    """Fetch closed trade deals for the given period."""
    from_date = datetime.now(tz=timezone.utc) - timedelta(days=days)
    to_date = datetime.now(tz=timezone.utc)

    deals = mt5.history_deals_get(from_date, to_date)
    if deals is None:
        return []

    # Filter: entry=1 means exit deal (closed trade)
    return [d for d in deals if d.entry == 1 and d.profit != 0]


@mcp.tool()
async def get_trade_stats(days: int = 30) -> str:
    """Calculate trading performance statistics.

    Args:
        days: Period to analyze (default 30, max 365).

    Returns:
        Win rate, profit factor, expectancy, max drawdown, best/worst trade,
        average win/loss, consecutive wins/losses, and Sharpe-like ratio.
    """
    if err := ensure_access():
        return f"Error: {err}"

    days = min(days, 365)
    trades = _get_closed_deals(days)

    if not trades:
        return f"No closed trades in the last {days} days."

    profits = [t.profit for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]

    total_profit = sum(profits)
    win_count = len(wins)
    loss_count = len(losses)
    total_trades = win_count + loss_count

    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses else float('inf')
    expectancy = np.mean(profits) if profits else 0

    # Max drawdown (from equity curve)
    cumulative = np.cumsum(profits)
    peak = np.maximum.accumulate(cumulative)
    drawdown = peak - cumulative
    max_dd = np.max(drawdown) if len(drawdown) > 0 else 0

    # Consecutive wins/losses
    max_consec_wins = 0
    max_consec_losses = 0
    current_streak = 0
    for p in profits:
        if p > 0:
            current_streak = current_streak + 1 if current_streak > 0 else 1
            max_consec_wins = max(max_consec_wins, current_streak)
        else:
            current_streak = current_streak - 1 if current_streak < 0 else -1
            max_consec_losses = max(max_consec_losses, abs(current_streak))

    # Best/worst
    best = max(profits) if profits else 0
    worst = min(profits) if profits else 0

    # Risk/reward ratio
    rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

    sign = "+" if total_profit >= 0 else ""

    return (
        f"Trading Stats — Last {days} days ({total_trades} trades)\n"
        f"\n"
        f"  P&L: {sign}${total_profit:,.2f}\n"
        f"  Win Rate: {win_rate:.1f}% ({win_count}W / {loss_count}L)\n"
        f"  Profit Factor: {profit_factor:.2f}\n"
        f"  Expectancy: ${expectancy:,.2f} per trade\n"
        f"  Risk/Reward: 1:{rr_ratio:.2f}\n"
        f"\n"
        f"  Avg Win: +${avg_win:,.2f} | Avg Loss: ${avg_loss:,.2f}\n"
        f"  Best: +${best:,.2f} | Worst: ${worst:,.2f}\n"
        f"  Max Drawdown: ${max_dd:,.2f}\n"
        f"  Max Consecutive: {max_consec_wins} wins / {max_consec_losses} losses"
    )


@mcp.tool()
async def get_pnl_by_symbol(days: int = 30) -> str:
    """Break down P&L by trading symbol/instrument.

    Args:
        days: Period to analyze (default 30, max 365).

    Returns:
        P&L, trade count, and win rate per symbol, sorted by profit.
    """
    if err := ensure_access():
        return f"Error: {err}"

    days = min(days, 365)
    trades = _get_closed_deals(days)

    if not trades:
        return f"No closed trades in the last {days} days."

    by_symbol: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by_symbol[t.symbol].append(t.profit)

    lines = [f"P&L by Symbol — Last {days} days", ""]

    # Sort by total profit descending
    sorted_symbols = sorted(by_symbol.items(), key=lambda x: sum(x[1]), reverse=True)

    for symbol, profits in sorted_symbols:
        total = sum(profits)
        wins = sum(1 for p in profits if p > 0)
        wr = wins / len(profits) * 100
        sign = "+" if total >= 0 else ""
        lines.append(
            f"  {symbol:<12} {sign}${total:>10,.2f}  "
            f"{len(profits):>3} trades  WR: {wr:.0f}%"
        )

    total_all = sum(sum(p) for p in by_symbol.values())
    sign = "+" if total_all >= 0 else ""
    lines.append(f"\n  {'TOTAL':<12} {sign}${total_all:>10,.2f}  {len(trades):>3} trades")

    return "\n".join(lines)


@mcp.tool()
async def get_pnl_by_time(days: int = 30) -> str:
    """Break down P&L by day of week and hour of day.

    Helps identify when you trade best/worst.

    Args:
        days: Period to analyze (default 30, max 365).

    Returns:
        P&L and win rate by day of week and by hour.
    """
    if err := ensure_access():
        return f"Error: {err}"

    days = min(days, 365)
    trades = _get_closed_deals(days)

    if not trades:
        return f"No closed trades in the last {days} days."

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    by_day: dict[int, list[float]] = defaultdict(list)
    by_hour: dict[int, list[float]] = defaultdict(list)

    for t in trades:
        dt = datetime.fromtimestamp(t.time, tz=timezone.utc)
        by_day[dt.weekday()].append(t.profit)
        by_hour[dt.hour].append(t.profit)

    lines = [f"P&L by Time — Last {days} days", "", "By Day of Week:"]

    for day_idx in range(7):
        if day_idx in by_day:
            profits = by_day[day_idx]
            total = sum(profits)
            wins = sum(1 for p in profits if p > 0)
            wr = wins / len(profits) * 100
            sign = "+" if total >= 0 else ""
            lines.append(
                f"  {day_names[day_idx]:<12} {sign}${total:>10,.2f}  "
                f"{len(profits):>3} trades  WR: {wr:.0f}%"
            )

    lines.append("")
    lines.append("By Hour (UTC):")

    for hour in sorted(by_hour.keys()):
        profits = by_hour[hour]
        total = sum(profits)
        wins = sum(1 for p in profits if p > 0)
        wr = wins / len(profits) * 100
        sign = "+" if total >= 0 else ""
        bar = "#" * min(int(abs(total) / 10), 20)  # Visual bar
        lines.append(
            f"  {hour:02d}:00  {sign}${total:>8,.2f}  {len(profits):>2}t  WR:{wr:>3.0f}%  {bar}"
        )

    return "\n".join(lines)


@mcp.tool()
async def check_order(
    symbol: str, direction: str, volume: float,
    sl: float = 0.0, tp: float = 0.0,
) -> str:
    """Validate an order WITHOUT executing it. Checks margin, limits, and restrictions.

    Args:
        symbol: Instrument (e.g. EURUSD).
        direction: "buy" or "sell".
        volume: Lot size.
        sl: Stop loss price (optional).
        tp: Take profit price (optional).

    Returns:
        Whether the order would succeed, required margin, and any errors.
    """
    if err := ensure_access():
        return f"Error: {err}"

    direction = direction.lower().strip()
    if direction not in ("buy", "sell"):
        return "Error: direction must be 'buy' or 'sell'."

    sym = symbol.upper()
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
        "comment": "mt5-mcp check",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_check(request)
    if result is None:
        return f"Error: order_check returned None. Last error: {mt5.last_error()}"

    account = mt5.account_info()
    margin_pct = (result.margin / account.equity * 100) if account and account.equity > 0 else 0

    status = "WOULD SUCCEED" if result.retcode == 0 else f"WOULD FAIL: {result.comment}"

    return (
        f"Order Check: {sym} {direction.upper()} {volume} lots @ {price}\n"
        f"  Status: {status}\n"
        f"  Required margin: ${result.margin:,.2f} ({margin_pct:.1f}% of equity)\n"
        f"  Free margin after: ${result.margin_free:,.2f}\n"
        f"  Expected profit: ${result.profit:,.2f}\n"
        f"  Balance: ${result.balance:,.2f} | Equity: ${result.equity:,.2f}"
    )


@mcp.tool()
async def get_tick_history(
    symbol: str, count: int = 1000,
) -> str:
    """Get historical tick-by-tick data for spread and timing analysis.

    Args:
        symbol: Instrument (e.g. EURUSD).
        count: Number of ticks (default 1000, max 10000).

    Returns:
        Tick statistics: avg/min/max spread, tick frequency, and volume.
    """
    if err := ensure_access():
        return f"Error: {err}"

    count = min(count, 10000)
    ticks = mt5.copy_ticks_from(
        symbol.upper(),
        datetime.now(tz=timezone.utc) - timedelta(hours=1),
        count,
        mt5.COPY_TICKS_ALL,
    )

    if ticks is None or len(ticks) == 0:
        return f"No tick data for {symbol.upper()}."

    bids = np.array([t['bid'] for t in ticks])
    asks = np.array([t['ask'] for t in ticks])
    spreads = asks - bids
    times = np.array([t['time'] for t in ticks])

    # Tick frequency
    if len(times) > 1:
        intervals = np.diff(times)
        avg_interval = np.mean(intervals[intervals > 0]) if np.any(intervals > 0) else 0
        ticks_per_sec = 1.0 / avg_interval if avg_interval > 0 else 0
    else:
        avg_interval = 0
        ticks_per_sec = 0

    first_ts = datetime.fromtimestamp(int(times[0]), tz=timezone.utc).strftime("%H:%M:%S")
    last_ts = datetime.fromtimestamp(int(times[-1]), tz=timezone.utc).strftime("%H:%M:%S")

    return (
        f"Tick Analysis: {symbol.upper()} ({len(ticks)} ticks, {first_ts}-{last_ts} UTC)\n"
        f"\n"
        f"  Spread: avg={np.mean(spreads):.5f} | min={np.min(spreads):.5f} | max={np.max(spreads):.5f}\n"
        f"  Price range: {np.min(bids):.5f} - {np.max(bids):.5f}\n"
        f"  Tick frequency: {ticks_per_sec:.1f} ticks/sec (avg interval: {avg_interval:.2f}s)\n"
        f"  Latest: bid={bids[-1]:.5f} ask={asks[-1]:.5f}"
    )
