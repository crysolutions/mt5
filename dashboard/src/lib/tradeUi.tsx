export function secureProfitPct(pnl: number | null | undefined): number | null {
  if (pnl == null || pnl <= 5) return null;
  if (pnl > 10) return 75;
  return 50;
}

export function StopLossCell({ sl, pnl }: { sl?: number; pnl: number | null }) {
  if (!sl || sl <= 0) return <td>—</td>;
  const pct = secureProfitPct(pnl);
  return (
    <td>
      {sl}
      {pct !== null && pnl !== null && (
        <small className="sl-meta">
          {" "}
          ({pct}% of P&amp;L)
        </small>
      )}
    </td>
  );
}

export function PnlCell({ value }: { value: number | null }) {
  if (value === null) return <td>—</td>;
  const cls = value >= 0 ? "profit-pos" : "profit-neg";
  const sign = value >= 0 ? "+" : "";
  return (
    <td className={cls}>
      {sign}
      {value.toFixed(2)}
    </td>
  );
}

export function SideBadge({ side }: { side: string }) {
  const s = side.toUpperCase();
  if (s === "BUY") return <span className="side-buy">BUY</span>;
  if (s === "SELL") return <span className="side-sell">SELL</span>;
  if (s.includes("CLOSE")) return <span className="side-close">{side}</span>;
  if (s.includes("SECURE")) return <span className="side-sp">{side}</span>;
  if (s.includes("CROSS")) return <span className="side-cross">{side}</span>;
  if (s.includes("FLIP")) return <span className="side-flip">{side}</span>;
  return <span>{side}</span>;
}

export function formatTime(iso?: string) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function formatTradingDay(iso?: string) {
  if (!iso) return "Today";
  try {
    return new Date(iso + "T12:00:00").toLocaleDateString(undefined, {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}
