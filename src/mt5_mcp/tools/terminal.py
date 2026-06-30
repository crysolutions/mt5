"""Terminal tools — logs, EAs, journal, and terminal info from local MT5."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from datetime import datetime, timezone

import MetaTrader5 as mt5

from mt5_mcp.server import mcp
from mt5_mcp.connection import ensure_access

logger = logging.getLogger("mt5-mcp")


def _get_data_path() -> Path | None:
    """Get MT5 terminal data path."""
    info = mt5.terminal_info()
    if info is None:
        return None
    return Path(info.data_path)


@mcp.tool()
async def get_terminal_info() -> str:
    """Get MT5 terminal information: version, build, paths, and trading status.

    Returns:
        Terminal version, data path, expert trading status, and connection info.
    """
    if err := ensure_access():
        return f"Error: {err}"

    info = mt5.terminal_info()
    if info is None:
        return "Error: Could not get terminal info."

    version = mt5.version()

    return (
        f"MetaTrader 5 Terminal\n"
        f"  Version: {version[0]} | Build: {version[1]} | Date: {version[2]}\n"
        f"  Company: {info.company}\n"
        f"  Path: {info.path}\n"
        f"  Data path: {info.data_path}\n"
        f"  Connected: {bool(info.connected)}\n"
        f"  Trade allowed: {bool(info.trade_allowed)}\n"
        f"  Expert trading: {bool(info.trade_expert)}\n"
        f"  Community account: {bool(info.community_account)}\n"
        f"  Max bars in chart: {info.maxbars}"
    )


@mcp.tool()
async def list_experts() -> str:
    """List Expert Advisors (EAs) installed in the MT5 terminal.

    Returns:
        List of .ex5 and .mq5 files in MQL5/Experts/ with file sizes and dates.
    """
    if err := ensure_access():
        return f"Error: {err}"

    data_path = _get_data_path()
    if data_path is None:
        return "Error: Could not get data path."

    experts_dir = data_path / "MQL5" / "Experts"
    if not experts_dir.exists():
        return f"Experts directory not found: {experts_dir}"

    lines = ["Installed Expert Advisors:", ""]
    count = 0

    for root, dirs, files in os.walk(experts_dir):
        rel = Path(root).relative_to(experts_dir)
        for f in sorted(files):
            if f.endswith((".ex5", ".mq5")):
                filepath = Path(root) / f
                size = filepath.stat().st_size
                mtime = datetime.fromtimestamp(
                    filepath.stat().st_mtime, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M")

                prefix = f"  {rel}/" if str(rel) != "." else "  "
                size_str = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
                ext = "compiled" if f.endswith(".ex5") else "source"

                lines.append(f"{prefix}{f} ({ext}, {size_str}, {mtime})")
                count += 1

    if count == 0:
        return "No Expert Advisors found in MQL5/Experts/"

    lines.insert(1, f"  Total: {count} files")
    return "\n".join(lines)


@mcp.tool()
async def read_ea_logs(expert_name: str = "", lines_count: int = 50) -> str:
    """Read Expert Advisor logs from the MT5 terminal.

    Args:
        expert_name: Filter by EA name (optional). Empty = all EA logs.
        lines_count: Number of lines to read from the end (default 50, max 200).

    Returns:
        Recent EA log entries with timestamps.
    """
    if err := ensure_access():
        return f"Error: {err}"

    data_path = _get_data_path()
    if data_path is None:
        return "Error: Could not get data path."

    logs_dir = data_path / "MQL5" / "Logs"
    if not logs_dir.exists():
        return f"EA logs directory not found: {logs_dir}"

    # Find the most recent log file
    log_files = sorted(logs_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not log_files:
        return "No EA log files found."

    lines_count = min(lines_count, 200)
    result_lines = [f"EA Logs (latest file: {log_files[0].name}):", ""]

    try:
        with open(log_files[0], "r", encoding="utf-16-le", errors="replace") as f:
            all_lines = f.readlines()

        # Filter by expert name if provided
        if expert_name:
            all_lines = [l for l in all_lines if expert_name.lower() in l.lower()]

        # Take last N lines
        recent = all_lines[-lines_count:]
        for line in recent:
            result_lines.append(f"  {line.rstrip()}")

        if not recent:
            return f"No log entries found{' for ' + expert_name if expert_name else ''}."

    except Exception as e:
        return f"Error reading log file: {e}"

    return "\n".join(result_lines)


@mcp.tool()
async def read_ea_config(expert_name: str) -> str:
    """Read EA configuration (.set file) to see its parameters.

    Args:
        expert_name: EA name to search for (e.g. "InnovaTrading", "MyEA").

    Returns:
        EA parameter settings from the .set file.
    """
    if err := ensure_access():
        return f"Error: {err}"

    data_path = _get_data_path()
    if data_path is None:
        return "Error: Could not get data path."

    # Search in Presets and Tester directories
    search_dirs = [
        data_path / "MQL5" / "Presets",
        data_path / "MQL5" / "Profiles",
        data_path / "Tester",
    ]

    found_files = []
    for search_dir in search_dirs:
        if search_dir.exists():
            for f in search_dir.rglob("*.set"):
                if expert_name.lower() in f.stem.lower():
                    found_files.append(f)

    if not found_files:
        return f"No .set config file found for '{expert_name}'. Available EAs: use list_experts() first."

    # Read the most recent one
    found_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    config_file = found_files[0]

    lines = [f"EA Config: {config_file.name} (from {config_file.parent.name}/)", ""]

    try:
        with open(config_file, "r", encoding="utf-16-le", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith(";"):
                    lines.append(f"  {line}")
    except Exception as e:
        return f"Error reading config: {e}"

    if len(lines) <= 2:
        return f"Config file {config_file.name} is empty."

    return "\n".join(lines)


@mcp.tool()
async def get_journal(lines_count: int = 30) -> str:
    """Read the MT5 terminal journal (connection events, errors, etc.).

    Args:
        lines_count: Number of lines from the end (default 30, max 100).

    Returns:
        Recent terminal journal entries.
    """
    if err := ensure_access():
        return f"Error: {err}"

    data_path = _get_data_path()
    if data_path is None:
        return "Error: Could not get data path."

    logs_dir = data_path / "Logs"
    if not logs_dir.exists():
        return f"Terminal logs directory not found: {logs_dir}"

    log_files = sorted(logs_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not log_files:
        return "No terminal journal files found."

    lines_count = min(lines_count, 100)
    result_lines = [f"Terminal Journal ({log_files[0].name}):", ""]

    try:
        with open(log_files[0], "r", encoding="utf-16-le", errors="replace") as f:
            all_lines = f.readlines()

        for line in all_lines[-lines_count:]:
            result_lines.append(f"  {line.rstrip()}")

    except Exception as e:
        return f"Error reading journal: {e}"

    return "\n".join(result_lines)
