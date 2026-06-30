"""EMA signal and martingale lot sizing.

Pine Script parity (TradingView strategy "EMA"):
    emaA = ema(close, 9)   # fast — plotted red  ("Short" line in TV)
    emaB = ema(close, 21)  # slow — plotted green ("Long" line in TV)
    cross(emaA, emaB)      # entries only on bullish / bearish crossover
    bullish → strategy.entry("EMA Long",  strategy.long)
    bearish → strategy.entry("EMA Short", strategy.short)

Entry rules on cross:
    - If open P&L > 0: close all positions, then enter with initial lot
    - If open P&L <= 0: keep positions, add leg with martingale lot sizing
"""

from __future__ import annotations

import numpy as np

from ema_bot.models import BotConfig, Signal, SymbolState


def calc_ema(closes: np.ndarray, length: int) -> np.ndarray:
    ema_vals = np.zeros(len(closes))
    ema_vals[length - 1] = np.mean(closes[:length])
    mult = 2.0 / (length + 1)
    for i in range(length, len(closes)):
        ema_vals[i] = (closes[i] - ema_vals[i - 1]) * mult + ema_vals[i - 1]
    return ema_vals


def detect_ema_cross(fast: np.ndarray, slow: np.ndarray) -> str | None:
    """Pine cross(emaA, emaB) — bullish or bearish crossover on the latest bar."""
    if len(fast) < 2 or len(slow) < 2:
        return None
    prev_fast, cur_fast = fast[-2], fast[-1]
    prev_slow, cur_slow = slow[-2], slow[-1]
    if prev_fast <= prev_slow and cur_fast > cur_slow:
        return "bullish"
    if prev_fast >= prev_slow and cur_fast < cur_slow:
        return "bearish"
    return None


def pine_long(ema_fast: float, ema_slow: float) -> bool:
    """long = emaA > emaB"""
    return ema_fast > ema_slow


def pine_short(ema_fast: float, ema_slow: float) -> bool:
    """short = emaA < emaB"""
    return ema_fast < ema_slow


def compute_signal(
    closes: np.ndarray,
    ema_fast: int,
    ema_slow: int,
) -> tuple[Signal, float, float, str | None]:
    """Return Pine signal direction, EMA values, and optional crossover."""
    if len(closes) < ema_slow + 1:
        raise ValueError("Not enough bars for EMA calculation")

    fast = calc_ema(closes, ema_fast)
    slow = calc_ema(closes, ema_slow)
    ema9 = float(fast[-1])
    ema21 = float(slow[-1])

    if pine_long(ema9, ema21):
        signal = Signal.LONG
    else:
        signal = Signal.SHORT

    cross = detect_ema_cross(fast, slow)
    return signal, ema9, ema21, cross


def entry_comment(signal: Signal) -> str:
    """Pine strategy.entry names."""
    return "EMA Long" if signal == Signal.LONG else "EMA Short"


def signal_from_cross(cross: str) -> Signal:
    """Map EMA crossover direction to trade signal."""
    if cross == "bullish":
        return Signal.LONG
    if cross == "bearish":
        return Signal.SHORT
    raise ValueError(f"Unknown cross direction: {cross}")


def sync_martingale_from_positions(
    state: SymbolState,
    positions: list,
    config: BotConfig,
) -> None:
    """Align martingale counters with open bot positions."""
    state.position_count = len(positions)
    if positions:
        last = max(positions, key=lambda p: p.ticket)
        state.total_lot_size = last.volume
        state.lot_size = last.volume
    else:
        state.total_lot_size = 0.0
        state.lot_size = config.initial_lot_size


def next_lot_size(state: SymbolState, config: BotConfig) -> float:
    """Calculate next lot size per martingale rules."""
    count = state.position_count
    total = state.total_lot_size

    if count == 0:
        lot = config.initial_lot_size
    elif count == 1:
        lot = total * config.next_multiplier
    else:
        lot = total * config.deviation

    return min(lot, config.max_lot_size)
