"""Market data tools — ticks, bars, and symbol information from local MT5."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import MetaTrader5 as mt5

from mt5_mcp.server import mcp
from mt5_mcp.connection import ensure_access

logger = logging.getLogger("mt5-mcp")

# MT5 timeframe mapping
TF_MAP = {
    1: mt5.TIMEFRAME_M1,
    5: mt5.TIMEFRAME_M5,
    15: mt5.TIMEFRAME_M15,
    30: mt5.TIMEFRAME_M30,
    60: mt5.TIMEFRAME_H1,
    240: mt5.TIMEFRAME_H4,
    1440: mt5.TIMEFRAME_D1,
    10080: mt5.TIMEFRAME_W1,
    43200: mt5.TIMEFRAME_MN1,
}


@mcp.tool()
async def get_tick(symbol: str) -> str:
    """Get the latest tick (bid/ask) for a symbol.

    Args:
        symbol: Instrument name (e.g. EURUSD, XAUUSD, BTCUSD).

    Returns:
        Current bid, ask, spread, and timestamp.
    """
    if err := ensure_access():
        return f"Error: {err}"

    tick = mt5.symbol_info_tick(symbol.upper())
    if tick is None:
        return f"No tick data for {symbol.upper()}. Check if the symbol exists and Market Watch is enabled."

    spread = (tick.ask - tick.bid)
    ts = datetime.fromtimestamp(tick.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return (
        f"{symbol.upper()} | Bid: {tick.bid} | Ask: {tick.ask} | "
        f"Spread: {spread:.5f} | Volume: {tick.volume} | Time: {ts}"
    )


@mcp.tool()
async def get_bars(symbol: str, timeframe: int, limit: int = 500) -> str:
    """Fetch OHLCV bars from MT5 terminal.

    Args:
        symbol: Instrument name (e.g. EURUSD, XAUUSD).
        timeframe: Timeframe in minutes (1, 5, 15, 30, 60, 240, 1440, 10080, 43200).
        limit: Number of bars (default 500, max 10000).

    Returns:
        Bar count, last 5 bars with OHLCV, and price range summary.
    """
    if err := ensure_access():
        return f"Error: {err}"

    tf = TF_MAP.get(timeframe)
    if tf is None:
        return f"Invalid timeframe {timeframe}. Valid: {', '.join(str(k) for k in sorted(TF_MAP.keys()))}"

    limit = min(limit, 10000)
    rates = mt5.copy_rates_from_pos(symbol.upper(), tf, 0, limit)

    if rates is None or len(rates) == 0:
        err = mt5.last_error()
        return f"No bars for {symbol.upper()} TF{timeframe}. Error: {err}"

    lines = [f"Bars: {symbol.upper()} TF{timeframe} — {len(rates)} bars", ""]

    # Last 5 bars
    lines.append("Last 5 bars:")
    for bar in rates[-5:]:
        ts = datetime.fromtimestamp(bar['time'], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        lines.append(
            f"  {ts}  O={bar['open']}  H={bar['high']}  "
            f"L={bar['low']}  C={bar['close']}  V={bar['tick_volume']}"
        )

    # Range summary
    if len(rates) > 1:
        highs = [b['high'] for b in rates]
        lows = [b['low'] for b in rates]
        lines.append("")
        lines.append(
            f"Range: High={max(highs)}, Low={min(lows)}, "
            f"Latest close={rates[-1]['close']}"
        )

    return "\n".join(lines)


@mcp.tool()
async def get_symbols(filter_text: str = "") -> str:
    """List available symbols in MT5 terminal.

    Args:
        filter_text: Optional filter (e.g. "USD", "BTC", "XAU"). Empty = all visible symbols.

    Returns:
        List of available symbols with their descriptions.
    """
    if err := ensure_access():
        return f"Error: {err}"

    if filter_text:
        symbols = mt5.symbols_get(filter_text.upper())
    else:
        symbols = mt5.symbols_get()

    if symbols is None or len(symbols) == 0:
        return f"No symbols found{' matching ' + filter_text if filter_text else ''}."

    # Only show visible symbols (in Market Watch)
    visible = [s for s in symbols if s.visible]
    hidden = len(symbols) - len(visible)

    lines = [f"Symbols: {len(visible)} visible ({hidden} hidden)", ""]

    # Group by type
    for sym in sorted(visible, key=lambda s: s.name)[:100]:
        spread = sym.spread
        lines.append(f"  {sym.name:<12} {sym.description:<30} spread={spread}")

    if len(visible) > 100:
        lines.append(f"  ... and {len(visible) - 100} more")

    return "\n".join(lines)


@mcp.tool()
async def get_symbol_info(symbol: str) -> str:
    """Get detailed information about a symbol.

    Args:
        symbol: Instrument name (e.g. EURUSD).

    Returns:
        Symbol details: digits, point, spread, lot size, trade mode, etc.
    """
    if err := ensure_access():
        return f"Error: {err}"

    info = mt5.symbol_info(symbol.upper())
    if info is None:
        return f"Symbol {symbol.upper()} not found."

    return (
        f"{info.name} — {info.description}\n"
        f"  Digits: {info.digits} | Point: {info.point} | Spread: {info.spread}\n"
        f"  Lot min: {info.volume_min} | Lot max: {info.volume_max} | Lot step: {info.volume_step}\n"
        f"  Contract size: {info.trade_contract_size} | Tick value: {info.trade_tick_value}\n"
        f"  Trade mode: {'Full' if info.trade_mode == 4 else info.trade_mode} | "
        f"Swap long: {info.swap_long} | Swap short: {info.swap_short}\n"
        f"  Session: {'Open' if info.session_deals > 0 else 'Closed/Unknown'}"
    )
