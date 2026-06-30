"""MCP Server for MetaTrader 5."""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("mt5-mcp")

mcp = FastMCP("MT5 MCP Server")

# Import tools to register them with the server
import mt5_mcp.tools.market  # noqa: F401, E402
import mt5_mcp.tools.account  # noqa: F401, E402
import mt5_mcp.tools.trading  # noqa: F401, E402
import mt5_mcp.tools.indicators  # noqa: F401, E402
import mt5_mcp.tools.terminal  # noqa: F401, E402
import mt5_mcp.tools.analytics  # noqa: F401, E402
import mt5_mcp.tools.bot  # noqa: F401, E402


def main():
    """Entry point for the MCP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s: %(message)s",
        stream=sys.stderr,
    )

    if sys.platform != "win32":
        logger.error(
            "MetaTrader 5 Python API requires Windows. "
            "For Mac/Linux, use Docker mode (see README.md)."
        )
        sys.exit(1)

    mcp.run()


if __name__ == "__main__":
    main()
