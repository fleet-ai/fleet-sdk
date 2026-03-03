#!/usr/bin/env python3
"""
Shell Server - MCP server with bash and file tools for Harbor integration.

MCP server providing shell execution and file operations using FastMCP's
streamable-http transport.

Env vars:
    PORT: Server port (default: 8765)
    SHELL_WORKDIR: Default working directory for commands (default: /)
"""

import logging
import os

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from tools import register_tools

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# Setup
# =============================================================================

PORT = int(os.environ.get("PORT", "8765"))
WORKDIR = os.environ.get("SHELL_WORKDIR", "/")

mcp = FastMCP("shell-server", host="0.0.0.0", port=PORT)

# Register all tools
register_tools(mcp)


# =============================================================================
# Routes
# =============================================================================


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({
        "status": "ok",
        "server": "shell-server",
        "workdir": WORKDIR,
    })


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    logger.info(f"Starting Shell Server on port {PORT}, workdir={WORKDIR}")
    mcp.run(transport="streamable-http")
