#!/usr/bin/env python3
"""
CUA Server - Computer Use Agent MCP Server

MCP server with playwright browser control using FastMCP's streamable-http transport.

Env vars:
    FLEET_ENV_URL: URL to navigate to
    PORT: Server port (default: 8765)
    SCREEN_WIDTH/HEIGHT: Browser size
    HEADLESS: "true" or "false" (default: true)
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from fleet.utils.playwright import PlaywrightComputer

# Support both module and standalone execution
try:
    from .tools import register_tools
except ImportError:
    from tools import register_tools

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# Setup
# =============================================================================

computer: Optional[PlaywrightComputer] = None
PORT = int(os.environ.get("PORT", "8765"))


def get_computer() -> PlaywrightComputer:
    """Get the current computer instance."""
    if computer is None:
        raise RuntimeError("Computer not initialized")
    return computer


@asynccontextmanager
async def lifespan(app):
    """Initialize browser on startup, cleanup on shutdown."""
    global computer
    
    url = os.environ.get("FLEET_ENV_URL", "about:blank")
    width = int(os.environ.get("SCREEN_WIDTH", "1366"))
    height = int(os.environ.get("SCREEN_HEIGHT", "768"))
    headless = os.environ.get("HEADLESS", "true").lower() == "true"
    highlight = os.environ.get("HIGHLIGHT_MOUSE", "false").lower() == "true"
    
    logger.info(f"CUA Server: {width}x{height}, headless={headless}, url={url}")
    
    computer = PlaywrightComputer(
        screen_size=(width, height),
        initial_url=url,
        headless=headless,
        highlight_mouse=highlight or not headless,
    )
    
    try:
        logger.info("Starting Playwright browser...")
        await computer.start()
        logger.info(f"Browser started, navigated to: {computer.current_url}")
        yield
    except Exception as e:
        logger.error(f"Browser startup FAILED: {type(e).__name__}: {e}")
        raise
    finally:
        logger.info("Stopping Playwright browser...")
        try:
            await computer.stop()
            logger.info("Browser stopped")
        except Exception as e:
            logger.error(f"Browser stop error: {type(e).__name__}: {e}")


mcp = FastMCP("cua-server", lifespan=lifespan, host="0.0.0.0", port=PORT)

# Register all tools
register_tools(mcp, get_computer)


# =============================================================================
# Routes
# =============================================================================

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "url": computer.current_url if computer else ""})


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    logger.info(f"Starting CUA Server on port {PORT}")
    mcp.run(transport="streamable-http")
