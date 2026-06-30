import { useEffect, useState } from "react";
import { PnlCell, SideBadge, formatTime } from "../lib/tradeUi";

interface TradeRow {
  time?: string;
  ticket?: number;
  symbol: string;
  side: string;
  lot_size: number | string;
  price?: number | string;
  pnl: number | null;
  status: string;
}

interface HistoryPeriod {
  key: string;
  label: string;
  total_pnl: number;
  closed_count: number;
  order_count: number;
  closed_trades: TradeRow[];
  orders: TradeRow[];
}

interface HistoryData {
  group_by: string;
  grand_total_pnl: number;
  periods: HistoryPeriod[];
}

type GroupBy = "day" | "week" | "month";

export function HistoryView({ symbol }: { symbol: string }) {
  const [groupBy, setGroupBy] = useState<GroupBy>("day");
  const [data, setData] = useState<HistoryData | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/history?symbol=${symbol}&group_by=${groupBy}&days=90`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => {});
  }, [symbol, groupBy]);

  const toggle = (key: string) => {
    setExpanded((prev) => (prev === key ? null : key));
  };

  return (
    <div className="history-view">
      <div className="history-toolbar">
        <div className="history-group-btns">
          {(["day", "week", "month"] as GroupBy[]).map((g) => (
            <button
              key={g}
              className={`tab ${groupBy === g ? "active" : ""}`}
              onClick={() => {
                setGroupBy(g);
                setExpanded(null);
              }}
            >
              {g === "day" ? "Daily" : g === "week" ? "Weekly" : "Monthly"}
            </button>
          ))}
        </div>
        <div className="history-grand-total">
          <span className="card-label">Period total</span>
          <span
            className={`card-value ${
              (data?.grand_total_pnl ?? 0) >= 0 ? "profit-pos" : "profit-neg"
            }`}
          >
            {(data?.grand_total_pnl ?? 0).toFixed(2)}
          </span>
        </div>
      </div>

      {!data?.periods?.length ? (
        <p className="empty">No history for this period yet.</p>
      ) : (
        <div className="history-periods">
          {data.periods.map((period) => (
            <div key={period.key} className="history-period panel">
              <button
                className="history-period-header"
                onClick={() => toggle(period.key)}
                type="button"
              >
                <div>
                  <strong>{period.label}</strong>
                  <small className="history-meta">
                    {period.closed_count} closed · {period.order_count} orders
                  </small>
                </div>
                <span
                  className={`history-pnl ${
                    period.total_pnl >= 0 ? "profit-pos" : "profit-neg"
                  }`}
                >
                  {period.total_pnl >= 0 ? "+" : ""}
                  {period.total_pnl.toFixed(2)}
                </span>
              </button>

              {expanded === period.key && (
                <div className="history-period-body">
                  <h3>Closed trades</h3>
                  {!period.closed_trades.length ? (
                    <p className="empty">No closed trades</p>
                  ) : (
                    <table>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Side</th>
                          <th>Lot</th>
                          <th>Price</th>
                          <th>P&amp;L</th>
                        </tr>
                      </thead>
                      <tbody>
                        {period.closed_trades.map((t) => (
                          <tr key={t.ticket}>
                            <td className="time-cell">{formatTime(t.time)}</td>
                            <td>
                              <SideBadge side={t.side} />
                            </td>
                            <td>{t.lot_size}</td>
                            <td>{t.price}</td>
                            <PnlCell value={t.pnl} />
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}

                  <h3 style={{ marginTop: "1rem" }}>Order log</h3>
                  {!period.orders.length ? (
                    <p className="empty">No orders</p>
                  ) : (
                    <table>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Side</th>
                          <th>Lot</th>
                          <th>Price</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {period.orders.map((t, i) => (
                          <tr key={`${t.time}-${i}`}>
                            <td className="time-cell">{formatTime(t.time)}</td>
                            <td>
                              <SideBadge side={t.side} />
                            </td>
                            <td>{t.lot_size}</td>
                            <td>{t.price}</td>
                            <td>{t.status}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
