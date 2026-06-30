"""REST routes for bot dashboard."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from bot_server.history import build_history_periods, local_today, parse_local_dt
from bot_server.state import get_engine, get_store
from ema_bot import broker
from ema_bot.strategy import next_lot_size, sync_martingale_from_positions
from ema_bot.models import SymbolState

router = APIRouter()

_ORDER_EVENT_TYPES = ("order", "take_profit", "secure_profit", "cross", "signal_flip", "close_all")


@router.get("/api/status")
def api_status() -> dict:
    engine = get_engine()
    return engine.build_status()


@router.get("/api/events")
def api_events(limit: int = 50, symbol: str | None = None) -> dict:
    store = get_store()
    return {"events": store.get_events(limit=limit, symbol=symbol)}


@router.get("/api/trades")
def api_trades(symbol: str | None = None) -> dict:
    """Trade-focused dashboard data: open positions, orders, realized P&L."""
    engine = get_engine()
    store = get_store()
    sym_filter = symbol.upper() if symbol else None
    symbols = [sym_filter] if sym_filter else engine.config.symbols

    open_trades: list[dict] = []
    unrealized = 0.0
    summary_state: SymbolState | None = None

    for sym in symbols:
        state = store.get_symbol_state(sym)
        if summary_state is None:
            summary_state = state
        positions = broker.get_bot_positions(sym, engine.config.magic)
        for p in positions:
            pnl = p.profit + p.swap
            unrealized += pnl
            open_trades.append(
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "side": "BUY" if p.direction == "long" else "SELL",
                    "lot_size": p.volume,
                    "entry_price": p.price_open,
                    "current_price": p.price_current,
                    "sl": p.sl,
                    "pnl": round(pnl, 2),
                    "status": "OPEN",
                }
            )

    completed: list[dict] = []
    today_pnl = 0.0
    for sym in symbols:
        for d in broker.get_bot_deal_history(engine.config.magic, sym):
            if d["entry"] != "OUT":
                continue
            net = d["profit"] + d["commission"] + d["swap"]
            row = {
                "time": d["time"],
                "symbol": d["symbol"],
                "side": d["side"],
                "lot_size": d["volume"],
                "price": d["price"],
                "pnl": round(net, 2),
                "status": "CLOSED",
                "ticket": d["ticket"],
            }
            if _is_today(d["time"]):
                today_pnl += net
                completed.append(row)

    order_log = _build_order_log(store.get_events(limit=200, symbol=sym_filter), today_only=True)

    next_lot = None
    if summary_state:
        cfg = engine.config
        live_positions = broker.get_bot_positions(summary_state.symbol, cfg.magic)
        sync_martingale_from_positions(summary_state, live_positions, cfg)
        next_lot = broker.normalize_lot(
            summary_state.symbol,
            next_lot_size(summary_state, cfg),
            cfg.max_lot_size,
        )

    return {
        "summary": {
            "unrealized_pnl": round(unrealized, 2),
            "realized_pnl": round(today_pnl, 2),
            "today_pnl": round(today_pnl, 2),
            "total_pnl": round(today_pnl, 2),
            "trading_day": local_today().isoformat(),
            "open_count": len(open_trades),
            "position_count": len(open_trades),
            "martingale_count": summary_state.position_count if summary_state else 0,
            "lot_size": (
                summary_state.lot_size
                if summary_state and len(open_trades) > 0
                else engine.config.initial_lot_size
            ),
            "total_lot_size": (
                summary_state.total_lot_size if summary_state and len(open_trades) > 0 else 0
            ),
            "next_lot_size": next_lot,
            "signal": summary_state.last_signal if summary_state else "",
            "ema_fast": summary_state.last_ema_fast if summary_state else 0,
            "ema_slow": summary_state.last_ema_slow if summary_state else 0,
            "secure_profit_usd": summary_state.secure_profit_usd if summary_state else 0,
            "secure_profit_pct": summary_state.secure_profit_pct if summary_state else 0,
        },
        "open_trades": open_trades,
        "completed_trades": completed,
        "order_log": order_log[:100],
    }


@router.get("/api/history")
def api_history(
    symbol: str | None = None,
    group_by: str = "day",
    days: int = 90,
) -> dict:
    """Historical trades grouped by day, week, or month (excludes today for day view)."""
    if group_by not in ("day", "week", "month"):
        raise HTTPException(400, "group_by must be day, week, or month")

    engine = get_engine()
    store = get_store()
    sym_filter = symbol.upper() if symbol else None
    symbols = [sym_filter] if sym_filter else engine.config.symbols

    closed_trades: list[dict] = []
    for sym in symbols:
        for d in broker.get_bot_deal_history(engine.config.magic, sym, days=days):
            if d["entry"] != "OUT":
                continue
            net = d["profit"] + d["commission"] + d["swap"]
            closed_trades.append(
                {
                    "time": d["time"],
                    "symbol": d["symbol"],
                    "side": d["side"],
                    "lot_size": d["volume"],
                    "price": d["price"],
                    "pnl": round(net, 2),
                    "status": "CLOSED",
                    "ticket": d["ticket"],
                }
            )

    orders = _build_order_log(
        store.get_events_since(days=days, symbol=sym_filter),
        today_only=False,
    )

    periods = build_history_periods(
        closed_trades,
        orders,
        group_by,  # type: ignore[arg-type]
        exclude_today=group_by == "day",
    )
    grand_total = round(sum(p["total_pnl"] for p in periods), 2)

    return {
        "group_by": group_by,
        "days": days,
        "trading_day": local_today().isoformat(),
        "grand_total_pnl": grand_total,
        "periods": periods,
    }


def _build_order_log(events: list[dict], *, today_only: bool) -> list[dict]:
    rows: list[dict] = []
    for ev in events:
        if ev["event_type"] not in _ORDER_EVENT_TYPES:
            continue
        if today_only and not _is_today(ev["created_at"]):
            continue
        row = _event_to_order_row(ev)
        if row:
            rows.append(row)
    return rows


def _event_to_order_row(ev: dict[str, Any]) -> dict[str, Any] | None:
    data = json.loads(ev.get("data") or "{}")
    side = "BUY" if data.get("signal") == "long" else "SELL"
    if ev["event_type"] == "take_profit":
        return {
            "time": ev["created_at"],
            "symbol": ev["symbol"],
            "side": "CLOSE ALL",
            "lot_size": data.get("closed", "—"),
            "price": "—",
            "pnl": round(float(data.get("profit", 0)), 2),
            "status": "COMPLETE",
            "message": ev["message"],
        }
    if ev["event_type"] == "close_all":
        return {
            "time": ev["created_at"],
            "symbol": ev["symbol"],
            "side": "CLOSE ALL (SL)",
            "lot_size": data.get("closed", "—"),
            "price": "—",
            "pnl": round(float(data.get("net_profit", data.get("profit", 0))), 2),
            "status": "SL EXIT",
            "message": ev["message"],
        }
    if ev["event_type"] == "cross":
        return {
            "time": ev["created_at"],
            "symbol": ev["symbol"],
            "side": f"CROSS {data.get('cross', '').upper()}",
            "lot_size": "—",
            "price": _parse_price(ev["message"]) if "@" in ev["message"] else "—",
            "pnl": None,
            "status": "CROSS",
            "message": ev["message"],
        }
    if ev["event_type"] == "signal_flip":
        return {
            "time": ev["created_at"],
            "symbol": ev["symbol"],
            "side": f"FLIP {data.get('from_signal', '')}→{data.get('to_signal', '')}",
            "lot_size": data.get("closed", "—"),
            "price": "—",
            "pnl": None,
            "status": "FLIP",
            "message": ev["message"],
        }
    if ev["event_type"] == "secure_profit":
        return {
            "time": ev["created_at"],
            "symbol": ev["symbol"],
            "side": "SECURE PROFIT",
            "lot_size": f"{float(data.get('secure_pct', 0)) * 100:.0f}%",
            "price": "—",
            "pnl": round(float(data.get("secure_usd", 0)), 2),
            "status": "SP",
            "message": ev["message"],
        }
    if ev["event_type"] == "order":
        return {
            "time": ev["created_at"],
            "symbol": ev["symbol"],
            "side": side,
            "lot_size": data.get("lot", "—"),
            "price": _parse_price(ev["message"]),
            "pnl": None,
            "status": "FILLED",
            "ticket": data.get("ticket"),
            "message": ev["message"],
        }
    return None


def _parse_price(message: str) -> str:
    if "@" in message:
        return message.split("@")[-1].strip()
    return "—"


def _is_today(iso_time: str) -> bool:
    """True if timestamp falls on the local calendar day."""
    dt = parse_local_dt(iso_time)
    if dt is None:
        return False
    return dt.date() == local_today()


@router.post("/api/bot/start")
async def api_start() -> dict:
    engine = get_engine()
    if engine.running:
        return {"ok": True, "message": "Already running"}
    err = await engine.start()
    if err:
        raise HTTPException(400, err)
    return {"ok": True}


@router.post("/api/bot/stop")
async def api_stop() -> dict:
    engine = get_engine()
    await engine.stop()
    return {"ok": True}


@router.get("/api/positions")
def api_positions() -> dict:
    engine = get_engine()
    result = []
    for symbol in engine.config.symbols:
        positions = broker.get_bot_positions(symbol, engine.config.magic)
        result.extend([p.to_dict() for p in positions])
    return {"positions": result}
