import { useEffect, useState } from "react";
import { HistoryView } from "./components/HistoryView";
import { SymbolSnapshot, useBotWs } from "./hooks/useBotWs";
import { PnlCell, SideBadge, StopLossCell, formatTime, formatTradingDay } from "./lib/tradeUi";

interface TradeRow {
  time?: string;
  ticket?: number;
  symbol: string;
  side: string;
  lot_size: number | string;
  entry_price?: number;
  current_price?: number;
  sl?: number;
  price?: number | string;
  pnl: number | null;
  status: string;
  message?: string;
}

interface TradesSummary {
  unrealized_pnl: number;
  realized_pnl: number;
  today_pnl: number;
  total_pnl: number;
  trading_day?: string;
  open_count: number;
  position_count: number;
  martingale_count?: number;
  lot_size: number;
  total_lot_size: number;
  next_lot_size: number | null;
  signal: string;
  ema_fast: number;
  ema_slow: number;
  secure_profit_usd: number;
  secure_profit_pct: number;
}

interface TradesData {
  summary: TradesSummary;
  open_trades: TradeRow[];
  completed_trades: TradeRow[];
  order_log: TradeRow[];
}

type PageTab = "today" | "history";

export default function App() {
  const { snapshots, running, connected } = useBotWs();
  const [symbols, setSymbols] = useState<string[]>(["XAUUSD"]);
  const [active, setActive] = useState("XAUUSD");
  const [page, setPage] = useState<PageTab>("today");
  const [trades, setTrades] = useState<TradesData | null>(null);

  useEffect(() => {
    fetch("/api/status")
      .then((r) => r.json())
      .then((d) => {
        const syms = (d.symbols ?? []).map((s: { symbol: string }) => s.symbol);
        if (syms.length) {
          setSymbols(syms);
          setActive(syms[0]);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (page !== "today") return;
    const load = () =>
      fetch(`/api/trades?symbol=${active}`)
        .then((r) => r.json())
        .then(setTrades)
        .catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [active, page]);

  const snap: SymbolSnapshot | undefined = snapshots[active];
  const summary = trades?.summary;
  const signalClass =
    summary?.signal === "long" ? "signal-long" : summary?.signal === "short" ? "signal-short" : "";

  const startBot = () => fetch("/api/bot/start", { method: "POST" });
  const stopBot = () => fetch("/api/bot/stop", { method: "POST" });

  return (
    <div className="app">
      <header>
        <div>
          <h1>EMA Martingale Bot</h1>
          <small style={{ color: "#8b949e" }}>
            Trade dashboard · Demo only · {connected ? "Live" : "Disconnected"}
          </small>
        </div>
        <div className="controls">
          <span className={`badge ${running ? "running" : "stopped"}`}>
            {running ? "RUNNING" : "STOPPED"}
          </span>
          <button className="primary" onClick={startBot}>
            Start
          </button>
          <button className="danger" onClick={stopBot}>
            Stop
          </button>
        </div>
      </header>

      <div className="page-tabs">
        <button
          className={`page-tab ${page === "today" ? "active" : ""}`}
          onClick={() => setPage("today")}
        >
          Today
        </button>
        <button
          className={`page-tab ${page === "history" ? "active" : ""}`}
          onClick={() => setPage("history")}
        >
          History
        </button>
      </div>

      <div className="tabs">
        {symbols.map((s) => (
          <button
            key={s}
            className={`tab ${s === active ? "active" : ""}`}
            onClick={() => setActive(s)}
          >
            {s}
          </button>
        ))}
      </div>

      {page === "history" ? (
        <HistoryView symbol={active} />
      ) : (
        <>
          <p className="today-banner">
            Trading day: <strong>{formatTradingDay(summary?.trading_day)}</strong> — orders and
            closed trades reset at midnight; prior days are in History.
          </p>

          <div className="summary-cards">
            <div className="card">
              <div className="card-label">Signal</div>
              <div className={`card-value ${signalClass}`}>
                {summary?.signal?.toUpperCase() ?? snap?.signal?.toUpperCase() ?? "—"}
              </div>
            </div>
            <div className="card">
              <div className="card-label">Lot Size</div>
              <div className="card-value">{summary?.lot_size ?? "—"}</div>
            </div>
            <div className="card">
              <div className="card-label">Next Lot</div>
              <div className="card-value">{summary?.next_lot_size ?? "—"}</div>
            </div>
            <div className="card">
              <div className="card-label">Open Trades</div>
              <div className="card-value">{summary?.open_count ?? summary?.position_count ?? 0}</div>
            </div>
            <div className="card">
              <div className="card-label">Unrealized P&amp;L</div>
              <div
                className={`card-value ${
                  (summary?.unrealized_pnl ?? 0) >= 0 ? "profit-pos" : "profit-neg"
                }`}
              >
                {(summary?.unrealized_pnl ?? 0).toFixed(2)}
              </div>
            </div>
            <div className="card">
              <div className="card-label">Today Realized</div>
              <div
                className={`card-value ${
                  (summary?.realized_pnl ?? 0) >= 0 ? "profit-pos" : "profit-neg"
                }`}
              >
                {(summary?.realized_pnl ?? 0).toFixed(2)}
              </div>
            </div>
            <div className="card">
              <div className="card-label">Secured (SP)</div>
              <div className="card-value profit-pos">
                ${(summary?.secure_profit_usd ?? 0).toFixed(2)}
                <small style={{ fontSize: "0.7rem", color: "#8b949e" }}>
                  {" "}
                  ({((summary?.secure_profit_pct ?? 0) * 100).toFixed(0)}% max)
                </small>
              </div>
              <small style={{ fontSize: "0.65rem", color: "#8b949e" }}>
                &gt;$5 → 50% SL · &gt;$10 → 75% SL per trade
              </small>
            </div>
          </div>

          <div className="panel" style={{ marginTop: "1rem" }}>
            <h2>Open Trades — BUY / SELL</h2>
            {!trades?.open_trades?.length ? (
              <p className="empty">No open positions</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Ticket</th>
                    <th>Side</th>
                    <th>Lot Size</th>
                    <th>Entry</th>
                    <th>Current</th>
                    <th>Stop Loss</th>
                    <th>P&amp;L</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.open_trades.map((t) => (
                    <tr key={t.ticket}>
                      <td>{t.ticket}</td>
                      <td>
                        <SideBadge side={t.side} />
                      </td>
                      <td>{t.lot_size}</td>
                      <td>{t.entry_price}</td>
                      <td>{t.current_price}</td>
                      <StopLossCell sl={t.sl} pnl={t.pnl} />
                      <PnlCell value={t.pnl} />
                      <td>{t.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel" style={{ marginTop: "1rem" }}>
              <h2>Today — Closed Trades</h2>
              {!trades?.completed_trades?.length ? (
                <p className="empty">No closed trades today</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Side</th>
                      <th>Lot</th>
                      <th>Price</th>
                      <th>P&amp;L</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.completed_trades.map((t) => (
                      <tr key={t.ticket}>
                        <td className="time-cell">{formatTime(t.time)}</td>
                        <td>
                          <SideBadge side={t.side} />
                        </td>
                        <td>{t.lot_size}</td>
                        <td>{t.price}</td>
                        <PnlCell value={t.pnl} />
                        <td>{t.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

          <div className="panel" style={{ marginTop: "1rem" }}>
              <h2>Today — Order Log</h2>
              {!trades?.order_log?.length ? (
                <p className="empty">No orders today</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Side</th>
                      <th>Lot Size</th>
                      <th>Price</th>
                      <th>P&amp;L</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.order_log.map((t, i) => (
                      <tr key={`${t.time}-${i}`}>
                        <td className="time-cell">{formatTime(t.time)}</td>
                        <td>
                          <SideBadge side={t.side} />
                        </td>
                        <td>{t.lot_size}</td>
                        <td>{t.price}</td>
                        <PnlCell value={t.pnl} />
                        <td>{t.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

          <div className="panel" style={{ marginTop: "1rem" }}>
            <h2>Pine EMA — cross-only entries</h2>
            <p className="hint">
              Trades open only when EMA 9 crosses EMA 21. If open P&amp;L is positive, all
              positions close first then a fresh lot opens. If negative, positions stay open
              and the next lot uses the martingale multiplier.
            </p>
            <div className="stat-grid">
              <div className="stat-row">
                <span className="ema-fast-label">EMA 9 (emaA)</span>
                <span className="ema-fast-value">{summary?.ema_fast?.toFixed(5) ?? "—"}</span>
              </div>
              <div className="stat-row">
                <span className="ema-slow-label">EMA 21 (emaB)</span>
                <span className="ema-slow-value">{summary?.ema_slow?.toFixed(5) ?? "—"}</span>
              </div>
              <div className="stat-row">
                <span>Last cross</span>
                <span className="side-cross">
                  {snap?.ema_cross ? snap.ema_cross.toUpperCase() : "—"}
                </span>
              </div>
              <div className="stat-row">
                <span>Signal (after cross)</span>
                <span className={signalClass}>{summary?.signal?.toUpperCase() ?? "—"}</span>
              </div>
              <div className="stat-row">
                <span>Price</span>
                <span>{snap?.price?.toFixed(5) ?? "—"}</span>
              </div>
              <div className="stat-row">
                <span>Last leg lot</span>
                <span>{summary?.total_lot_size ?? "—"}</span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
