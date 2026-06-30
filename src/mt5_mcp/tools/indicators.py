"""Technical indicators — RSI, MACD, ATR, SMA, EMA, Bollinger Bands.

All computed locally with numpy from MT5 bar data.
"""

from __future__ import annotations

import logging

import MetaTrader5 as mt5
import numpy as np

from mt5_mcp.server import mcp
from mt5_mcp.connection import ensure_access

logger = logging.getLogger("mt5-mcp")

# Reuse timeframe mapping
TF_MAP = {
    1: mt5.TIMEFRAME_M1, 5: mt5.TIMEFRAME_M5, 15: mt5.TIMEFRAME_M15,
    30: mt5.TIMEFRAME_M30, 60: mt5.TIMEFRAME_H1, 240: mt5.TIMEFRAME_H4,
    1440: mt5.TIMEFRAME_D1, 10080: mt5.TIMEFRAME_W1, 43200: mt5.TIMEFRAME_MN1,
}


def _get_closes(symbol: str, timeframe: int, count: int) -> np.ndarray | None:
    """Fetch close prices as numpy array."""
    tf = TF_MAP.get(timeframe)
    if tf is None:
        return None
    rates = mt5.copy_rates_from_pos(symbol.upper(), tf, 0, count)
    if rates is None or len(rates) == 0:
        return None
    return np.array([r['close'] for r in rates], dtype=np.float64)


def _get_hlc(symbol: str, timeframe: int, count: int):
    """Fetch high, low, close as numpy arrays."""
    tf = TF_MAP.get(timeframe)
    if tf is None:
        return None, None, None
    rates = mt5.copy_rates_from_pos(symbol.upper(), tf, 0, count)
    if rates is None or len(rates) == 0:
        return None, None, None
    h = np.array([r['high'] for r in rates], dtype=np.float64)
    l = np.array([r['low'] for r in rates], dtype=np.float64)
    c = np.array([r['close'] for r in rates], dtype=np.float64)
    return h, l, c


def _calc_ema(closes: np.ndarray, length: int) -> np.ndarray:
    """Compute EMA series for close prices."""
    ema_vals = np.zeros(len(closes))
    ema_vals[length - 1] = np.mean(closes[:length])
    mult = 2.0 / (length + 1)
    for i in range(length, len(closes)):
        ema_vals[i] = (closes[i] - ema_vals[i - 1]) * mult + ema_vals[i - 1]
    return ema_vals


@mcp.tool()
async def get_rsi(symbol: str, timeframe: int, length: int = 14) -> str:
    """Calculate RSI (Relative Strength Index) using Wilder's smoothing.

    Args:
        symbol: Instrument (e.g. EURUSD).
        timeframe: Timeframe in minutes.
        length: RSI period (default 14).

    Returns:
        Current RSI value, zone, and recent history.
    """
    if err := ensure_access():
        return f"Error: {err}"

    closes = _get_closes(symbol, timeframe, length + 100)
    if closes is None or len(closes) < length + 1:
        return f"Not enough data for RSI({length}) on {symbol.upper()} TF{timeframe}."

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.zeros(len(deltas))
    avg_loss = np.zeros(len(deltas))
    avg_gain[length - 1] = np.mean(gains[:length])
    avg_loss[length - 1] = np.mean(losses[:length])

    for i in range(length, len(deltas)):
        avg_gain[i] = (avg_gain[i - 1] * (length - 1) + gains[i]) / length
        avg_loss[i] = (avg_loss[i - 1] * (length - 1) + losses[i]) / length

    rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0)
    rsi = 100 - (100 / (1 + rs))

    current = rsi[-1]
    zone = "OVERBOUGHT" if current > 70 else "OVERSOLD" if current < 30 else "NEUTRAL"

    recent = [f"{rsi[i]:.1f}" for i in range(-5, 0)]

    return (
        f"RSI({length}) {symbol.upper()} TF{timeframe}: {current:.1f} [{zone}]\n"
        f"  Recent: {' -> '.join(recent)} -> {current:.1f}"
    )


@mcp.tool()
async def get_macd(
    symbol: str, timeframe: int,
    fast: int = 12, slow: int = 26, signal: int = 9,
) -> str:
    """Calculate MACD (Moving Average Convergence Divergence).

    Args:
        symbol: Instrument (e.g. EURUSD).
        timeframe: Timeframe in minutes.
        fast: Fast EMA period (default 12).
        slow: Slow EMA period (default 26).
        signal: Signal EMA period (default 9).

    Returns:
        MACD line, signal line, histogram, and crossover status.
    """
    if err := ensure_access():
        return f"Error: {err}"

    closes = _get_closes(symbol, timeframe, slow + signal + 50)
    if closes is None or len(closes) < slow + signal:
        return f"Not enough data for MACD on {symbol.upper()} TF{timeframe}."

    def ema(data, period):
        result = np.zeros(len(data))
        result[period - 1] = np.mean(data[:period])
        mult = 2.0 / (period + 1)
        for i in range(period, len(data)):
            result[i] = (data[i] - result[i - 1]) * mult + result[i - 1]
        return result

    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line[slow - 1:], signal)

    # Pad signal line to match macd_line length
    padded_signal = np.zeros(len(macd_line))
    padded_signal[slow - 1:slow - 1 + len(signal_line)] = signal_line
    histogram = macd_line - padded_signal

    m = macd_line[-1]
    s = padded_signal[-1]
    h = histogram[-1]

    crossover = ""
    if macd_line[-2] < padded_signal[-2] and m > s:
        crossover = " | BULLISH CROSSOVER"
    elif macd_line[-2] > padded_signal[-2] and m < s:
        crossover = " | BEARISH CROSSOVER"

    return (
        f"MACD({fast},{slow},{signal}) {symbol.upper()} TF{timeframe}:\n"
        f"  MACD: {m:.5f} | Signal: {s:.5f} | Histogram: {h:.5f}{crossover}"
    )


@mcp.tool()
async def get_atr(symbol: str, timeframe: int, length: int = 14) -> str:
    """Calculate ATR (Average True Range).

    Args:
        symbol: Instrument (e.g. EURUSD).
        timeframe: Timeframe in minutes.
        length: ATR period (default 14).

    Returns:
        Current ATR value and recent history.
    """
    if err := ensure_access():
        return f"Error: {err}"

    highs, lows, closes = _get_hlc(symbol, timeframe, length + 50)
    if highs is None or len(highs) < length + 1:
        return f"Not enough data for ATR({length}) on {symbol.upper()} TF{timeframe}."

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )

    atr = np.zeros(len(tr))
    atr[length - 1] = np.mean(tr[:length])
    for i in range(length, len(tr)):
        atr[i] = (atr[i - 1] * (length - 1) + tr[i]) / length

    current = atr[-1]

    return (
        f"ATR({length}) {symbol.upper()} TF{timeframe}: {current:.5f}\n"
        f"  In pips: ~{current / 0.0001:.1f} pips" if current < 1 else
        f"ATR({length}) {symbol.upper()} TF{timeframe}: {current:.2f}"
    )


@mcp.tool()
async def get_sma(symbol: str, timeframe: int, length: int = 20) -> str:
    """Calculate SMA (Simple Moving Average).

    Args:
        symbol: Instrument (e.g. EURUSD).
        timeframe: Timeframe in minutes.
        length: SMA period (default 20).

    Returns:
        Current SMA value and price position relative to it.
    """
    if err := ensure_access():
        return f"Error: {err}"

    closes = _get_closes(symbol, timeframe, length + 10)
    if closes is None or len(closes) < length:
        return f"Not enough data for SMA({length}) on {symbol.upper()} TF{timeframe}."

    sma = np.mean(closes[-length:])
    price = closes[-1]
    position = "ABOVE" if price > sma else "BELOW"
    distance = abs(price - sma)

    return (
        f"SMA({length}) {symbol.upper()} TF{timeframe}: {sma:.5f}\n"
        f"  Price: {price:.5f} ({position}, distance: {distance:.5f})"
    )


@mcp.tool()
async def get_ema(symbol: str, timeframe: int, length: int = 20) -> str:
    """Calculate EMA (Exponential Moving Average).

    Args:
        symbol: Instrument (e.g. EURUSD).
        timeframe: Timeframe in minutes.
        length: EMA period (default 20).

    Returns:
        Current EMA value and price position relative to it.
    """
    if err := ensure_access():
        return f"Error: {err}"

    closes = _get_closes(symbol, timeframe, length + 50)
    if closes is None or len(closes) < length:
        return f"Not enough data for EMA({length}) on {symbol.upper()} TF{timeframe}."

    ema_vals = _calc_ema(closes, length)
    current = ema_vals[-1]
    price = closes[-1]
    position = "ABOVE" if price > current else "BELOW"

    return (
        f"EMA({length}) {symbol.upper()} TF{timeframe}: {current:.5f}\n"
        f"  Price: {price:.5f} ({position})"
    )


@mcp.tool()
async def get_ema_pair(
    symbol: str,
    timeframe: int,
    fast: int = 9,
    slow: int = 21,
) -> str:
    """Calculate a fast/slow EMA pair (default EMA 9 / EMA 21).

    Args:
        symbol: Instrument (e.g. USDJPY, EURUSD).
        timeframe: Timeframe in minutes (1, 5, 15, 30, 60, 240, 1440, ...).
        fast: Fast EMA period (default 9).
        slow: Slow EMA period (default 21).

    Returns:
        Both EMA values, price vs EMAs, and crossover status.
    """
    if err := ensure_access():
        return f"Error: {err}"

    if fast >= slow:
        return "Error: fast period must be less than slow period."

    closes = _get_closes(symbol, timeframe, slow + 50)
    if closes is None or len(closes) < slow:
        return f"Not enough data for EMA({fast}/{slow}) on {symbol.upper()} TF{timeframe}."

    fast_ema = _calc_ema(closes, fast)
    slow_ema = _calc_ema(closes, slow)
    price = closes[-1]
    f, s = fast_ema[-1], slow_ema[-1]
    prev_f, prev_s = fast_ema[-2], slow_ema[-2]

    if f > s and prev_f <= prev_s:
        cross = "BULLISH CROSSOVER"
    elif f < s and prev_f >= prev_s:
        cross = "BEARISH CROSSOVER"
    elif f > s:
        cross = "bullish (fast above slow)"
    else:
        cross = "bearish (fast below slow)"

    return (
        f"EMA {fast}/{slow} {symbol.upper()} TF{timeframe}:\n"
        f"  EMA({fast}): {f:.5f}\n"
        f"  EMA({slow}): {s:.5f}\n"
        f"  Price: {price:.5f}\n"
        f"  Trend: {cross}"
    )


@mcp.tool()
async def get_bollinger(
    symbol: str, timeframe: int, length: int = 20, std_dev: float = 2.0,
) -> str:
    """Calculate Bollinger Bands.

    Args:
        symbol: Instrument (e.g. EURUSD).
        timeframe: Timeframe in minutes.
        length: SMA period (default 20).
        std_dev: Standard deviation multiplier (default 2.0).

    Returns:
        Upper, middle (SMA), and lower bands with price position.
    """
    if err := ensure_access():
        return f"Error: {err}"

    closes = _get_closes(symbol, timeframe, length + 10)
    if closes is None or len(closes) < length:
        return f"Not enough data for Bollinger({length}) on {symbol.upper()} TF{timeframe}."

    window = closes[-length:]
    middle = np.mean(window)
    std = np.std(window)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    price = closes[-1]

    # Position within bands (0% = lower, 100% = upper)
    band_width = upper - lower
    pct_b = ((price - lower) / band_width * 100) if band_width > 0 else 50

    zone = "UPPER" if pct_b > 80 else "LOWER" if pct_b < 20 else "MIDDLE"

    return (
        f"Bollinger({length}, {std_dev}) {symbol.upper()} TF{timeframe}:\n"
        f"  Upper: {upper:.5f} | Middle: {middle:.5f} | Lower: {lower:.5f}\n"
        f"  Price: {price:.5f} | %B: {pct_b:.1f}% [{zone}]\n"
        f"  Bandwidth: {band_width:.5f}"
    )
