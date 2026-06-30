# MT5 MCP + EMA Martingale Bot

This project connects **MetaTrader 5** to AI tools (Cursor, Claude) via the [Model Context Protocol](https://modelcontextprotocol.io), and includes an automated **EMA crossover trading bot** with a **live web dashboard**.

```
MetaTrader 5 (demo account, Algo Trading ON)
        │
        ▼
Python bot (ema_bot) ──► SQLite state + event log
        │
        ▼
FastAPI server (:8000) ──► React dashboard (:5173)
        │
        ▼
MCP server (optional) ──► Cursor / Claude agent tools
```

**Requirements:** Windows, Python 3.10+, Node.js 18+ (for dashboard), MetaTrader 5 terminal running locally.

---

## 1. Install MetaTrader 5

1. Download and install **MetaTrader 5** from the official site:  
   [https://www.metatrader5.com/en/download](https://www.metadatrader5.com/en/download)

2. Launch MT5 and log in (or create an account — see below).

3. Add your symbol to **Market Watch** (e.g. right-click → Symbols → find `XAUUSD` → Show).

4. **Enable algorithmic trading** (required for the bot):
   - Click **Algo Trading** in the toolbar (or press **Ctrl+E**) until it is **green / ON**.
   - Also check: **Tools → Options → Expert Advisors → Allow algorithmic trading**.

> The Python `MetaTrader5` package talks to MT5 over Windows IPC. The terminal must be **open and logged in** on the same machine while the bot runs.

---

## 2. Open a demo account

Use a **demo account** for testing. The bot defaults to `demo_only: true` and will refuse live accounts.

1. In MT5: **File → Open an Account**
2. Pick any broker from the list (e.g. MetaQuotes demo server).
3. Choose **Open a demo account**, set balance/leverage, finish registration.
4. Note your **login** and **server** — you should see `(demo)` in the account line at the bottom of MT5.

If your broker uses a suffix symbol (e.g. `XAUUSDm` instead of `XAUUSD`), put the **exact** symbol name in `config/bot.yaml`.

---

## 3. Install this project

```bash
git clone https://github.com/mrblacksheep91/mt5-mcp.git
cd mt5-mcp

# Python dependencies (bot + API + MCP)
pip install -e .

# Dashboard dependencies
cd dashboard
npm install
cd ..
```

Copy and edit the bot config:

```bash
copy config\bot.example.yaml config\bot.yaml
```

Key settings in `config/bot.yaml`:

| Setting | Default | Meaning |
|---------|---------|---------|
| `symbols` | `XAUUSD` | Symbol(s) to trade |
| `timeframe_minutes` | `1` | M1 bars |
| `poll_interval_sec` | `60` | How often the bot checks MT5 |
| `initial_lot_size` | `0.01` | First leg lot size |
| `next_multiplier` | `3.0` | 2nd leg: last lot × 3 |
| `deviation` | `1.5` | 3rd+ leg: last lot × 1.5 |
| `demo_only` | `true` | Block live accounts |
| `trading_enabled` | `true` | Place real orders in MT5 |
| `max_position_count` | `0` | `0` = unlimited legs |
| `secure_profit_enabled` | `true` | Auto stop-loss to lock profit |

---

## 4. What the bot does

Strategy is based on TradingView Pine **EMA 9 / 21 crossover** on **M1**:

### Entries (cross only)

Trades open **only** when EMA 9 crosses EMA 21 on a new bar:

| Cross | Action |
|-------|--------|
| **Bullish** (9 crosses above 21) | BUY — comment `EMA Long` |
| **Bearish** (9 crosses below 21) | SELL — comment `EMA Short` |

Before each cross entry:

- **Open P&L > 0** → close all positions, reset martingale, enter fresh at `0.01`
- **Open P&L ≤ 0** → keep positions, add next leg with martingale lot sizing

### Martingale lot sizing

| Open legs | Next lot |
|-----------|----------|
| 0 | `initial_lot_size` (0.01) |
| 1 | last lot × `next_multiplier` (×3) |
| 2+ | last lot × `deviation` (×1.5) |

When **no open trades**, Next Lot resets to **0.01**.

### Secure Profit (per position)

Every poll, for each **individual** open leg:

| Unrealized profit | Stop-loss locks |
|-------------------|-----------------|
| > **$5** | **50%** of that leg's profit |
| > **$10** | **75%** of that leg's profit |

SL only moves tighter (never loosened).

### SL hit → close all

If any leg's **stop-loss is triggered** and **net P&L** (SL profit + remaining unrealized) is **positive**, the bot **closes all remaining** positions and resets martingale.

---

## 5. What the dashboard does

Open **http://localhost:5173** after starting the dev server.

### Today tab

Resets each calendar day (local midnight):

| Section | Description |
|---------|-------------|
| **Summary cards** | Signal, lot size, next lot, open trades, unrealized P&L, today realized, secure profit |
| **Open Trades** | Live positions with side, lot, entry, current price, **stop loss** (with % of P&L), P&L |
| **Today — Closed Trades** | All closed deals today; **Today Realized** = sum of this table |
| **Today — Order Log** | Bot events today (orders, crosses, secure profit, SL close-all) |
| **Pine EMA panel** | EMA 9/21 values, last cross, signal |

**Start / Stop** buttons control the bot via the API.

### History tab

Past performance grouped by **Daily**, **Weekly**, or **Monthly**:

- Total P&L per period
- Closed trades and order log per period (expand a row)
- Today is excluded from daily history (stays on Today tab)

---

## 6. How to run

You need **three things** running: MT5 terminal, Python bot+API, React dashboard.

### Terminal 1 — MetaTrader 5

- Logged into **demo** account
- **Algo Trading ON** (Ctrl+E)
- Symbol visible in Market Watch

### Terminal 2 — Bot + API server

From the project root:

```bash
py -m ema_bot.cli serve --config config/bot.yaml
```

This starts:

- Trading engine (poll loop, EMA signals, orders, secure profit)
- FastAPI on **http://127.0.0.1:8000**
- WebSocket at **ws://127.0.0.1:8000/ws**

Bot-only (no API / dashboard backend):

```bash
py -m ema_bot.cli run --config config/bot.yaml
```

### Terminal 3 — Dashboard

```bash
cd dashboard
npm run dev
```

Open **http://localhost:5173** in your browser.

The Vite dev server proxies `/api` and `/ws` to port 8000.

### Production build (optional)

```bash
cd dashboard
npm run build
# Serve dist/ with any static host; API must still run on :8000
```

---

## 7. Cursor MCP (optional)

Let Cursor's AI read bot status and MT5 data. Add to `.cursor/mcp.json` in the project (or your global Cursor MCP config):

```json
{
  "mcpServers": {
    "mt5": {
      "command": "py",
      "args": ["-m", "mt5_mcp.server"],
      "env": {
        "MT5_MCP_DEMO_ONLY": "true",
        "MT5_MCP_TRADING_ENABLED": "true",
        "EMA_BOT_DB_PATH": "data/bot_state.db"
      }
    }
  }
}
```

Restart Cursor. The agent can use tools like `get_tick`, `get_ema_pair`, `get_bot_status`, `get_bot_events`.

Trading via MCP is **disabled by default** unless `MT5_MCP_TRADING_ENABLED=true`.

---

## 8. Project layout

```
mt5-mcp/
├── config/
│   ├── bot.yaml              # Active bot config
│   └── bot.example.yaml      # Template
├── dashboard/                # React + Vite UI
├── data/
│   └── bot_state.db          # SQLite (created at runtime)
├── src/
│   ├── ema_bot/              # Trading engine, strategy, broker
│   ├── bot_server/           # FastAPI REST + WebSocket
│   └── mt5_mcp/              # MCP server for Cursor/Claude
└── pyproject.toml
```

---

## 9. MCP server (AI tools)

The MCP server exposes read-only market/account/indicator tools and optional trading tools. Quick install for Claude Desktop:

```bash
pip install mt5-mcp
```

```json
{
  "mcpServers": {
    "mt5": {
      "command": "py",
      "args": ["-m", "mt5_mcp.server"]
    }
  }
}
```

| Category | Examples |
|----------|----------|
| Market | `get_tick`, `get_bars`, `get_symbols` |
| Account | `get_account_info`, `get_positions`, `get_trade_history` |
| Indicators | `get_rsi`, `get_macd`, `get_ema`, `get_ema_pair` |
| Bot | `get_bot_status`, `get_bot_events` |
| Trading (opt-in) | `place_order`, `close_position`, `modify_position` |

All data stays on your machine. No cloud API keys required.

---

## 10. Troubleshooting

| Problem | Fix |
|---------|-----|
| `MT5 initialize failed` | Open MT5 and log in first |
| `Algo Trading is OFF` | Enable Algo Trading (Ctrl+E) |
| `Demo-only mode` error | Use a demo account or set `demo_only: false` (not recommended) |
| `Symbol not found` | Add symbol to Market Watch; use exact broker symbol name |
| Orders not appearing | Check `trading_enabled: true` in `bot.yaml` |
| Dashboard disconnected | Ensure `py -m ema_bot.cli serve` is running on :8000 |
| Next Lot stuck high | Should reset to 0.01 when open trades = 0; restart bot after update |

---

## 11. Development

```bash
pip install -e ".[dev]"
pytest
```

---

## License

MIT

## Credits

Built by [Innova Trading](https://innova-trading.com).
