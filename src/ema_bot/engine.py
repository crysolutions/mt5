"""Trading engine — poll loop with new-bar gate."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import MetaTrader5 as mt5
import numpy as np

from ema_bot import broker
from ema_bot.models import BotConfig, BotEvent, BotEventType, SymbolSnapshot, SymbolState
from ema_bot.persistence import BotStore
from ema_bot.secure_profit import ratchet_sp
from ema_bot.strategy import (
    compute_signal,
    entry_comment,
    next_lot_size,
    signal_from_cross,
    sync_martingale_from_positions,
)

logger = logging.getLogger("ema-bot")

SnapshotCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class TradingEngine:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.store = BotStore(config.db_path)
        self.running = False
        self._task: asyncio.Task | None = None
        self._snapshot_callbacks: list[SnapshotCallback] = []

    def on_snapshot(self, callback: SnapshotCallback) -> None:
        self._snapshot_callbacks.append(callback)

    async def _emit_snapshot(self, payload: dict[str, Any]) -> None:
        for cb in self._snapshot_callbacks:
            result = cb(payload)
            if asyncio.iscoroutine(result):
                await result

    def _log(self, event_type: BotEventType, symbol: str, message: str, **data: Any) -> None:
        event = BotEvent(
            event_type=event_type.value,
            symbol=symbol,
            message=message,
            data=data,
        )
        self.store.log_event(event)
        logger.info("[%s] %s: %s", symbol, event_type.value, message)

    def validate_startup(self) -> str | None:
        ok, err = broker.ensure_mt5_connected()
        if not ok:
            return err
        demo_err = broker.check_demo_only(self.config.demo_only)
        if demo_err:
            return demo_err
        return None

    async def start(self) -> str | None:
        err = self.validate_startup()
        if err:
            return err
        if self.running:
            return None
        self.running = True
        self.store.set_meta("bot_running", "true")
        self._log(BotEventType.STARTED, "ALL", "Bot started")
        self._task = asyncio.create_task(self._run_loop())
        return None

    async def stop(self) -> None:
        self.running = False
        self.store.set_meta("bot_running", "false")
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._log(BotEventType.STOPPED, "ALL", "Bot stopped")

    async def _run_loop(self) -> None:
        try:
            while self.running:
                snapshots: list[dict[str, Any]] = []
                for symbol in self.config.symbols:
                    snap = await self._poll_symbol(symbol)
                    if snap:
                        snapshots.append(snap.to_dict())
                if snapshots:
                    await self._emit_snapshot({"type": "snapshot", "symbols": snapshots})
                await asyncio.sleep(self.config.poll_interval_sec)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Engine loop error: %s", exc)
            self._log(BotEventType.ERROR, "ALL", str(exc))

    async def _poll_symbol(self, symbol: str) -> SymbolSnapshot | None:
        sym = symbol.upper()
        state = self.store.get_symbol_state(sym)
        positions = broker.get_bot_positions(sym, self.config.magic)
        current_tickets = {p.ticket for p in positions}
        previous_tickets = set(state.last_position_tickets)

        if previous_tickets:
            positions = await self._on_sl_hit_close_all(
                sym, state, previous_tickets, current_tickets, positions
            )
            current_tickets = {p.ticket for p in positions}

        sync_martingale_from_positions(state, positions, self.config)
        if not positions:
            state.secure_profit_usd = 0.0
            state.secure_profit_pct = 0.0

        total_profit = broker.total_unrealized_profit(positions)

        await self._on_tick_secure_profit(sym, state, positions, total_profit)

        rates = broker.get_rates(sym, self.config.timeframe_minutes, self.config.ema_slow + 50)
        price = broker.get_tick_price(sym) or state.last_price
        ema_fast = state.last_ema_fast
        ema_slow = state.last_ema_slow
        signal_str = state.last_signal or "unknown"
        ema_cross: str | None = None

        if rates is not None and len(rates) >= self.config.ema_slow + 1:
            closes = np.array([r["close"] for r in rates], dtype=np.float64)
            try:
                sig, ema_fast, ema_slow, ema_cross = compute_signal(
                    closes, self.config.ema_fast, self.config.ema_slow
                )
                signal_str = sig.value
                state.last_ema_fast = ema_fast
                state.last_ema_slow = ema_slow
                state.last_price = float(closes[-1])
            except ValueError:
                pass

        bar_time = broker.get_bar_time(sym, self.config.timeframe_minutes) or 0

        if bar_time and bar_time != state.last_bar_time:
            await self._on_new_bar(
                sym, state, signal_str, ema_fast, ema_slow, total_profit, ema_cross
            )
            state.last_bar_time = bar_time
            self.store.save_symbol_state(state)
        else:
            state.last_price = price

        state.last_position_tickets = sorted(current_tickets)
        self.store.save_symbol_state(state)

        return SymbolSnapshot(
            symbol=sym,
            state=state,
            signal=signal_str,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            price=price,
            total_profit=total_profit,
            positions=positions,
            last_bar_time=bar_time,
            bot_running=self.running,
            ema_cross=ema_cross,
        )

    def _reset_martingale_state(self, state: SymbolState) -> None:
        state.position_count = 0
        state.lot_size = self.config.initial_lot_size
        state.total_lot_size = 0.0
        state.secure_profit_usd = 0.0
        state.secure_profit_pct = 0.0
        state.last_position_tickets = []

    async def _on_sl_hit_close_all(
        self,
        symbol: str,
        state: SymbolState,
        previous_tickets: set[int],
        current_tickets: set[int],
        positions: list,
    ) -> list:
        """If any tracked leg was stopped out, close all remaining when net P&L > 0."""
        if not self.config.sl_hit_close_all:
            return positions

        sl_hits = broker.detect_sl_hits(previous_tickets, current_tickets, self.config.magic)
        if not sl_hits:
            return positions

        sl_profit = sum(h["profit"] for h in sl_hits)
        remaining_profit = broker.total_unrealized_profit(positions)
        net_profit = sl_profit + remaining_profit

        hit_tickets = ", ".join(f"#{h['ticket']}" for h in sl_hits)
        if net_profit <= 0:
            self._log(
                BotEventType.ERROR,
                symbol,
                f"SL hit on {hit_tickets} but net P&L ${net_profit:.2f} — keeping open legs",
                sl_hits=sl_hits,
                sl_profit=sl_profit,
                remaining_profit=remaining_profit,
            )
            return positions

        if not self.config.trading_enabled:
            return positions

        closed = 0
        msg = "No remaining legs"
        if positions:
            closed, msg = broker.close_all_positions(symbol, self.config.magic)

        self._reset_martingale_state(state)
        self.store.save_symbol_state(state)
        self._log(
            BotEventType.CLOSE_ALL,
            symbol,
            f"SL hit on {hit_tickets} (+${sl_profit:.2f}) — closed {closed} remaining "
            f"leg(s) at net +${net_profit:.2f} — {msg}",
            sl_hits=sl_hits,
            sl_profit=sl_profit,
            remaining_profit=remaining_profit,
            net_profit=net_profit,
            closed=closed,
        )
        return broker.get_bot_positions(symbol, self.config.magic)

    async def _on_tick_secure_profit(
        self,
        symbol: str,
        state: SymbolState,
        positions: list,
        total_profit: float,
    ) -> None:
        """OnTick-style Secure Profit — ratcheting SL to lock gains."""
        if not self.config.secure_profit_enabled:
            return

        if not positions:
            if state.secure_profit_usd > 0 or state.secure_profit_pct > 0:
                state.secure_profit_usd = 0.0
                state.secure_profit_pct = 0.0
                self.store.save_symbol_state(state)
            return

        updated, msgs, target_usd, target_pct = broker.apply_secure_profit_stops(
            positions,
            self.config.magic,
            self.config.sp_threshold_half,
            self.config.sp_threshold_three_quarter,
        )
        if target_usd <= 0 and updated == 0:
            return

        new_usd, new_pct = ratchet_sp(
            state.secure_profit_usd,
            state.secure_profit_pct,
            target_usd,
            target_pct,
        )

        if new_usd <= state.secure_profit_usd and updated == 0:
            failed = [m for m in msgs if "failed" in m.lower()]
            if failed:
                self._log(
                    BotEventType.ERROR,
                    symbol,
                    f"Secure Profit SL failed — {'; '.join(failed)}",
                    details=msgs,
                )
            return

        state.secure_profit_usd = new_usd
        state.secure_profit_pct = new_pct
        self.store.save_symbol_state(state)

        if updated:
            profitable = sum(
                1 for p in positions if (p.profit + p.swap) > self.config.sp_threshold_half
            )
            self._log(
                BotEventType.SECURE_PROFIT,
                symbol,
                f"SP up to {new_pct * 100:.0f}% — ${new_usd:.2f} locked on "
                f"{updated}/{profitable} profitable leg(s) "
                f"(portfolio unrealized ${total_profit:.2f})",
                secure_usd=new_usd,
                secure_pct=new_pct,
                unrealized=total_profit,
                sl_updates=updated,
                details=msgs,
            )

    async def _on_new_bar(
        self,
        symbol: str,
        state: SymbolState,
        signal_str: str,
        ema_fast: float,
        ema_slow: float,
        total_profit: float,
        ema_cross: str | None,
    ) -> None:
        state.last_signal = signal_str
        self._log(
            BotEventType.NEW_BAR,
            symbol,
            f"New M{self.config.timeframe_minutes} bar — signal={signal_str} "
            f"EMA9={ema_fast:.5f} EMA21={ema_slow:.5f}"
            + (f" cross={ema_cross}" if ema_cross else ""),
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            total_profit=total_profit,
            cross=ema_cross,
        )

        if not ema_cross:
            self.store.save_symbol_state(state)
            return

        self._log(
            BotEventType.CROSS,
            symbol,
            f"EMA cross {ema_cross} @ EMA9={ema_fast:.5f} EMA21={ema_slow:.5f}",
            cross=ema_cross,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
        )

        signal = signal_from_cross(ema_cross)
        signal_str = signal.value
        state.last_signal = signal_str

        if not self.config.trading_enabled:
            self.store.save_symbol_state(state)
            return

        positions = broker.get_bot_positions(symbol, self.config.magic)
        total_profit = broker.total_unrealized_profit(positions)
        sync_martingale_from_positions(state, positions, self.config)

        if total_profit > 0 and positions:
            closed, msg = broker.close_all_positions(symbol, self.config.magic)
            state.position_count = 0
            state.lot_size = self.config.initial_lot_size
            state.total_lot_size = 0.0
            state.secure_profit_usd = 0.0
            state.secure_profit_pct = 0.0
            self._log(
                BotEventType.TAKE_PROFIT,
                symbol,
                f"Cross entry — closed {closed} legs at +${total_profit:.2f} — {msg}",
                closed=closed,
                profit=total_profit,
                cross=ema_cross,
            )
            lot = self.config.initial_lot_size
        elif (
            self.config.max_position_count > 0
            and state.position_count >= self.config.max_position_count
        ):
            self._log(
                BotEventType.ERROR,
                symbol,
                f"Max position count ({self.config.max_position_count}) reached — skipping cross entry",
            )
            self.store.save_symbol_state(state)
            return
        else:
            lot = next_lot_size(state, self.config)

        lot = broker.normalize_lot(symbol, lot, self.config.max_lot_size)

        if lot <= 0:
            self._log(BotEventType.ERROR, symbol, "Computed lot size is zero")
            self.store.save_symbol_state(state)
            return

        ok, msg, ticket = broker.place_market_order(
            symbol,
            signal,
            lot,
            self.config.magic,
            comment=entry_comment(signal),
        )
        if ok:
            state.total_lot_size = lot
            state.lot_size = lot
            state.position_count += 1
            self._log(
                BotEventType.ORDER,
                symbol,
                msg,
                ticket=ticket,
                lot=lot,
                signal=signal_str,
                position_count=state.position_count,
                entry_name=entry_comment(signal),
                cross=ema_cross,
                unrealized_before=total_profit,
            )
        else:
            self._log(BotEventType.ERROR, symbol, msg)

        self.store.save_symbol_state(state)

    def build_status(self) -> dict[str, Any]:
        states = []
        for symbol in self.config.symbols:
            state = self.store.get_symbol_state(symbol)
            positions = broker.get_bot_positions(symbol, self.config.magic)
            states.append(
                {
                    "symbol": symbol,
                    "state": state.to_dict(),
                    "total_profit": broker.total_unrealized_profit(positions),
                    "open_positions": len(positions),
                }
            )
        return {
            "running": self.running,
            "demo_only": self.config.demo_only,
            "symbols": states,
            "config": {
                "timeframe_minutes": self.config.timeframe_minutes,
                "poll_interval_sec": self.config.poll_interval_sec,
                "trading_enabled": self.config.trading_enabled,
                "initial_lot_size": self.config.initial_lot_size,
                "next_multiplier": self.config.next_multiplier,
                "deviation": self.config.deviation,
                "max_position_count": self.config.max_position_count,
                "max_lot_size": self.config.max_lot_size,
            },
        }

    def get_chart_bars(self, symbol: str, count: int = 100) -> list[dict[str, Any]]:
        rates = broker.get_rates(symbol, self.config.timeframe_minutes, count)
        if rates is None:
            return []
        return [
            {
                "time": int(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }
            for r in rates
        ]
