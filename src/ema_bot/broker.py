"""MT5 broker operations for the EMA bot."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import MetaTrader5 as mt5

from ema_bot.models import PositionSnapshot, Signal

logger = logging.getLogger("ema-bot")

TF_MAP = {
    1: mt5.TIMEFRAME_M1,
    5: mt5.TIMEFRAME_M5,
    15: mt5.TIMEFRAME_M15,
    30: mt5.TIMEFRAME_M30,
    60: mt5.TIMEFRAME_H1,
    240: mt5.TIMEFRAME_H4,
    1440: mt5.TIMEFRAME_D1,
}


def ensure_mt5_connected() -> tuple[bool, str]:
    """Initialize MT5 and verify terminal is reachable."""
    if not mt5.initialize():
        return False, f"MT5 initialize failed: {mt5.last_error()}"

    terminal = mt5.terminal_info()
    if terminal is None:
        return False, "Could not get terminal info."

    account = mt5.account_info()
    if account is None:
        return False, "Could not get account info."

    if not account.trade_allowed:
        return False, "Trading is disabled on this account."

    if not terminal.trade_allowed:
        return False, (
            "Algo Trading is OFF in MetaTrader 5. "
            "Click the 'Algo Trading' button in the MT5 toolbar (or press Ctrl+E), "
            "then restart the bot."
        )

    if not account.trade_expert:
        return False, (
            "Expert Advisor trading is disabled for this account. "
            "Enable it in MT5: Tools → Options → Expert Advisors."
        )

    return True, ""


def check_demo_only(demo_only: bool) -> str | None:
    """Return error message if live account blocked in demo-only mode."""
    if not demo_only:
        return None
    account = mt5.account_info()
    if account and account.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
        return (
            f"Demo-only mode: account {account.login} on {account.server} is LIVE. "
            "Set demo_only: false in config to allow live (not recommended)."
        )
    return None


def shutdown_mt5() -> None:
    mt5.shutdown()


def ensure_symbol(symbol: str) -> bool:
    sym = symbol.upper()
    info = mt5.symbol_info(sym)
    if info is None:
        return False
    if not info.visible:
        mt5.symbol_select(sym, True)
    return True


def get_bar_time(symbol: str, timeframe_minutes: int) -> int | None:
    """Return open time of the current bar (index 0)."""
    tf = TF_MAP.get(timeframe_minutes)
    if tf is None:
        return None
    rates = mt5.copy_rates_from_pos(symbol.upper(), tf, 0, 1)
    if rates is None or len(rates) == 0:
        return None
    return int(rates[0]["time"])


def get_rates(symbol: str, timeframe_minutes: int, count: int) -> list[dict[str, Any]] | None:
    tf = TF_MAP.get(timeframe_minutes)
    if tf is None:
        return None
    rates = mt5.copy_rates_from_pos(symbol.upper(), tf, 0, count)
    if rates is None or len(rates) == 0:
        return None
    return list(rates)


def get_tick_price(symbol: str) -> float | None:
    tick = mt5.symbol_info_tick(symbol.upper())
    if tick is None:
        return None
    return float(tick.bid)


def normalize_lot(symbol: str, volume: float, max_lot: float) -> float:
    info = mt5.symbol_info(symbol.upper())
    if info is None:
        return volume

    vol = min(volume, max_lot, info.volume_max)
    vol = max(vol, info.volume_min)
    step = info.volume_step
    if step > 0:
        vol = round(vol / step) * step
    decimals = max(0, len(str(step).split(".")[-1]) if "." in str(step) else 0)
    return round(vol, decimals)


def get_filling_type(symbol: str) -> int:
    """Pick a filling mode supported by the broker for this symbol."""
    info = mt5.symbol_info(symbol.upper())
    if info is None:
        return mt5.ORDER_FILLING_RETURN
    # SYMBOL_FILLING_FOK=1, SYMBOL_FILLING_IOC=2, SYMBOL_FILLING_RETURN=4
    if info.filling_mode & 1:
        return mt5.ORDER_FILLING_FOK
    if info.filling_mode & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def get_bot_positions(symbol: str, magic: int) -> list[PositionSnapshot]:
    positions = mt5.positions_get(symbol=symbol.upper())
    if positions is None:
        return []

    result: list[PositionSnapshot] = []
    for pos in positions:
        if pos.magic != magic:
            continue
        result.append(
            PositionSnapshot(
                ticket=pos.ticket,
                symbol=pos.symbol,
                direction="long" if pos.type == 0 else "short",
                volume=pos.volume,
                price_open=pos.price_open,
                price_current=pos.price_current,
                profit=pos.profit,
                swap=pos.swap,
                sl=pos.sl,
            )
        )
    return result


def total_unrealized_profit(positions: list[PositionSnapshot]) -> float:
    return sum(p.profit + p.swap for p in positions)


def position_closed_by_sl(position_ticket: int, magic: int) -> tuple[bool, float]:
    """Return whether a position was closed by stop-loss and its net realized P&L."""
    deals = mt5.history_deals_get(position=position_ticket)
    if deals is None:
        return False, 0.0

    out_deals = [
        d
        for d in deals
        if d.entry == mt5.DEAL_ENTRY_OUT and d.magic == magic
    ]
    if not out_deals:
        return False, 0.0

    last = out_deals[-1]
    if last.reason != mt5.DEAL_REASON_SL:
        return False, 0.0

    net = float(last.profit + last.commission + last.swap)
    return True, net


def detect_sl_hits(
    previous_tickets: set[int],
    current_tickets: set[int],
    magic: int,
) -> list[dict[str, Any]]:
    """Find positions that disappeared because their stop-loss was hit."""
    hits: list[dict[str, Any]] = []
    for ticket in previous_tickets - current_tickets:
        by_sl, profit = position_closed_by_sl(ticket, magic)
        if by_sl:
            hits.append({"ticket": ticket, "profit": profit})
    return hits


def place_market_order(
    symbol: str,
    signal: Signal,
    volume: float,
    magic: int,
    comment: str = "ema-bot",
) -> tuple[bool, str, int | None]:
    sym = symbol.upper()
    if not ensure_symbol(sym):
        return False, f"Symbol {sym} not found", None

    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        return False, f"No tick for {sym}", None

    direction = "buy" if signal == Signal.LONG else "sell"
    price = tick.ask if direction == "buy" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL
    filling = get_filling_type(sym)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": sym,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": 0.0,
        "tp": 0.0,
        "deviation": 20,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    result = mt5.order_send(request)
    if result is None:
        return False, f"order_send None: {mt5.last_error()}", None
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return False, f"Order failed: {result.comment} ({result.retcode})", None

    return True, f"{direction.upper()} {volume} @ {result.price}", result.order


def close_all_positions(symbol: str, magic: int) -> tuple[int, str]:
    positions = get_bot_positions(symbol, magic)
    if not positions:
        return 0, "No positions to close"

    closed = 0
    errors: list[str] = []
    for pos in positions:
        close_type = mt5.ORDER_TYPE_SELL if pos.direction == "long" else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol.upper())
        if tick is None:
            errors.append(f"No tick for {pos.ticket}")
            continue
        price = tick.bid if pos.direction == "long" else tick.ask
        filling = get_filling_type(symbol)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol.upper(),
            "volume": pos.volume,
            "type": close_type,
            "position": pos.ticket,
            "price": price,
            "deviation": 20,
            "magic": magic,
            "comment": "ema-bot close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            closed += 1
        else:
            msg = result.comment if result else str(mt5.last_error())
            errors.append(f"#{pos.ticket}: {msg}")

    msg = f"Closed {closed}/{len(positions)} positions"
    if errors:
        msg += "; " + "; ".join(errors)
    return closed, msg


def get_bot_deal_history(
    magic: int,
    symbol: str | None = None,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Closed deals for bot positions (realized P&L)."""
    from_date = datetime.now(tz=timezone.utc) - timedelta(days=days)
    to_date = datetime.now(tz=timezone.utc)
    deals = mt5.history_deals_get(from_date, to_date)
    if deals is None:
        return []

    result: list[dict[str, Any]] = []
    for d in deals:
        if d.magic != magic:
            continue
        if symbol and d.symbol.upper() != symbol.upper():
            continue
        side = "BUY" if d.type == 0 else "SELL"
        entry = "IN" if d.entry == 0 else "OUT"
        ts = datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat()
        result.append(
            {
                "ticket": d.ticket,
                "order": d.order,
                "symbol": d.symbol,
                "side": side,
                "entry": entry,
                "volume": d.volume,
                "price": d.price,
                "profit": d.profit,
                "commission": d.commission,
                "swap": d.swap,
                "time": ts,
            }
        )
    result.sort(key=lambda x: x["time"], reverse=True)
    return result


def _sl_is_better(is_long: bool, new_sl: float, old_sl: float) -> bool:
    if new_sl <= 0:
        return False
    if old_sl <= 0:
        return True
    return new_sl > old_sl if is_long else new_sl < old_sl


def calc_sl_for_locked_profit(
    symbol: str,
    is_long: bool,
    volume: float,
    price_open: float,
    lock_usd: float,
) -> float:
    """Find SL price that locks approximately lock_usd profit on this leg."""
    sym = symbol.upper()
    info = mt5.symbol_info(sym)
    tick = mt5.symbol_info_tick(sym)
    if not info or not tick or lock_usd <= 0 or volume <= 0:
        return 0.0

    order_type = mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL
    current = tick.bid if is_long else tick.ask
    if is_long and current <= price_open:
        return 0.0
    if not is_long and current >= price_open:
        return 0.0

    lo = price_open if is_long else current
    hi = current if is_long else price_open
    best = 0.0

    for _ in range(50):
        mid = (lo + hi) / 2.0
        profit = mt5.order_calc_profit(order_type, sym, volume, price_open, mid)
        if profit is None:
            break
        if profit < lock_usd:
            if is_long:
                lo = mid
            else:
                hi = mid
        else:
            best = mid
            if is_long:
                hi = mid
            else:
                lo = mid

    return round(best, info.digits) if best > 0 else 0.0


def modify_position_sl(
    ticket: int,
    symbol: str,
    sl: float,
    magic: int,
) -> tuple[bool, str]:
    pos_list = mt5.positions_get(ticket=ticket)
    tp = float(pos_list[0].tp) if pos_list else 0.0
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol.upper(),
        "position": ticket,
        "sl": sl,
        "tp": tp,
        "magic": magic,
    }
    result = mt5.order_send(request)
    if result is None:
        return False, str(mt5.last_error())
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return False, f"{result.comment} ({result.retcode})"
    return True, f"SL set to {sl}"


def apply_secure_profit_stops(
    positions: list[PositionSnapshot],
    magic: int,
    threshold_half: float = 5.0,
    threshold_three_quarter: float = 10.0,
) -> tuple[int, list[str], float, float]:
    """Per-position SP: move SL to lock 50% / 75% of each leg's unrealized profit.

    - position profit > threshold_half ($5) → stop-loss locks 50%
    - position profit > threshold_three_quarter ($10) → stop-loss locks 75%
    SL only moves in the securing direction (never loosened).
    Returns (updated_count, messages, best_lock_usd, best_lock_pct).
    """
    from ema_bot.secure_profit import compute_sp_target

    if not positions:
        return 0, [], 0.0, 0.0

    updated = 0
    messages: list[str] = []
    best_usd = 0.0
    best_pct = 0.0

    for pos in positions:
        pos_profit = pos.profit + pos.swap
        target_pct, lock_usd = compute_sp_target(
            pos_profit, threshold_half, threshold_three_quarter
        )
        if lock_usd <= 0:
            continue

        lock_amount = min(lock_usd, pos_profit)
        best_usd = max(best_usd, lock_amount)
        best_pct = max(best_pct, target_pct)

        is_long = pos.direction == "long"
        new_sl = calc_sl_for_locked_profit(
            pos.symbol, is_long, pos.volume, pos.price_open, lock_amount
        )
        if not _sl_is_better(is_long, new_sl, pos.sl):
            continue

        ok, msg = modify_position_sl(pos.ticket, pos.symbol, new_sl, magic)
        if ok:
            updated += 1
            messages.append(
                f"#{pos.ticket} SP {target_pct * 100:.0f}% "
                f"(${lock_amount:.2f} of ${pos_profit:.2f}) SL={new_sl}"
            )
        else:
            messages.append(f"#{pos.ticket} failed: {msg}")

    return updated, messages, best_usd, best_pct
