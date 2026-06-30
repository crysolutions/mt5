"""MT5 connection manager — singleton that handles MetaTrader 5 terminal connection."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import MetaTrader5 as mt5

logger = logging.getLogger("mt5-mcp")

_initialized = False


@dataclass
class ConnectionInfo:
    connected: bool
    terminal_path: str | None = None
    account: int | None = None
    server: str | None = None
    company: str | None = None
    build: int | None = None


def _demo_only_enabled() -> bool:
    """Demo-only mode is on by default; set MT5_MCP_DEMO_ONLY=false to allow live accounts."""
    return os.environ.get("MT5_MCP_DEMO_ONLY", "true").lower() in ("true", "1", "yes")


def ensure_connected() -> bool:
    """Initialize MT5 connection if not already connected."""
    global _initialized
    if _initialized:
        return True

    if not mt5.initialize():
        logger.error(f"MT5 initialize() failed: {mt5.last_error()}")
        return False

    _initialized = True
    info = mt5.terminal_info()
    account = mt5.account_info()
    if info:
        mode = "demo" if account and account.trade_mode != mt5.ACCOUNT_TRADE_MODE_REAL else "live"
        logger.info(
            f"Connected to MT5: {info.company} | "
            f"Account: {account.login if account else 'N/A'} ({mode}) | "
            f"Build: {info.build}"
        )
    return True


def ensure_access() -> str | None:
    """Ensure MT5 is connected and the account is allowed. Returns an error message or None."""
    if not ensure_connected():
        return "Could not connect to MT5 terminal. Is MetaTrader 5 running?"

    if not _demo_only_enabled():
        return None

    account = mt5.account_info()
    if account is None:
        return "Could not get account info."

    if account.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
        return (
            f"DEMO-ONLY MODE: account {account.login} on {account.server} is LIVE. "
            "Switch to a demo account in MT5, or set MT5_MCP_DEMO_ONLY=false "
            "(not recommended for AI-assisted use)."
        )

    return None


def get_connection_info() -> ConnectionInfo:
    """Get current connection status and details."""
    if not _initialized or not mt5.terminal_info():
        return ConnectionInfo(connected=False)

    info = mt5.terminal_info()
    account = mt5.account_info()
    return ConnectionInfo(
        connected=True,
        terminal_path=info.path if info else None,
        account=account.login if account else None,
        server=account.server if account else None,
        company=info.company if info else None,
        build=info.build if info else None,
    )


def shutdown():
    """Shutdown MT5 connection."""
    global _initialized
    if _initialized:
        mt5.shutdown()
        _initialized = False
        logger.info("MT5 connection closed")
