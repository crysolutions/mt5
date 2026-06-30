import { useEffect, useState } from "react";

export interface SymbolSnapshot {
  symbol: string;
  signal: string;
  ema_fast: number;
  ema_slow: number;
  price: number;
  total_profit: number;
  last_bar_time: number;
  bot_running: boolean;
  ema_cross?: string | null;
  state: {
    position_count: number;
    total_lot_size: number;
    lot_size: number;
    last_signal: string;
  };
  positions: Array<{
    ticket: number;
    direction: string;
    volume: number;
    price_open: number;
    price_current: number;
    profit: number;
  }>;
}

export interface BotEvent {
  id?: number;
  event_type: string;
  symbol: string;
  message: string;
  created_at: string;
}

export function useBotWs() {
  const [snapshots, setSnapshots] = useState<Record<string, SymbolSnapshot>>({});
  const [running, setRunning] = useState(false);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/ws`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      if (data.type === "snapshot" && data.symbols) {
        const map: Record<string, SymbolSnapshot> = {};
        for (const s of data.symbols as SymbolSnapshot[]) {
          map[s.symbol] = s;
        }
        setSnapshots(map);
        setRunning(data.symbols[0]?.bot_running ?? false);
      }
      if (data.type === "status") {
        setRunning(data.running ?? false);
      }
    };

    return () => ws.close();
  }, []);

  return { snapshots, running, connected };
}
