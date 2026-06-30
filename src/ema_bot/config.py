"""Load bot configuration from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

from ema_bot.models import BotConfig


def _parse_max_position_count(value: object) -> int:
    """0 or null in YAML means unlimited open legs."""
    if value is None:
        return 0
    return int(value)


def load_config(path: str | Path) -> BotConfig:
    """Load BotConfig from a YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return BotConfig(
        symbols=[s.upper() for s in raw.get("symbols", ["USDJPY"])],
        poll_interval_sec=float(raw.get("poll_interval_sec", 60.0)),
        timeframe_minutes=int(raw.get("timeframe_minutes", 1)),
        ema_fast=int(raw.get("ema_fast", 9)),
        ema_slow=int(raw.get("ema_slow", 21)),
        initial_lot_size=float(raw.get("initial_lot_size", 0.01)),
        next_multiplier=float(raw.get("next_multiplier", 3.0)),
        deviation=float(raw.get("deviation", 1.5)),
        magic=int(raw.get("magic", 234567)),
        max_position_count=_parse_max_position_count(raw.get("max_position_count", 5)),
        max_lot_size=float(raw.get("max_lot_size", 1.0)),
        demo_only=bool(raw.get("demo_only", True)),
        trading_enabled=bool(raw.get("trading_enabled", True)),
        db_path=str(raw.get("db_path", "data/bot_state.db")),
        api_host=str(raw.get("api_host", "127.0.0.1")),
        api_port=int(raw.get("api_port", 8000)),
        secure_profit_enabled=bool(raw.get("secure_profit_enabled", True)),
        sp_threshold_half=float(raw.get("sp_threshold_half", 5.0)),
        sp_threshold_three_quarter=float(raw.get("sp_threshold_three_quarter", 10.0)),
        sl_hit_close_all=bool(raw.get("sl_hit_close_all", True)),
    )
