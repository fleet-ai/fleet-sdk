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

import base64
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent
from starlette.requests import Request
from starlette.responses import JSONResponse

from playwright_utils import PlaywrightComputer, KEY_SPEC

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# Setup
# =============================================================================

computer: Optional[PlaywrightComputer] = None
PORT = int(os.environ.get("PORT", "8765"))


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


# =============================================================================
# MCP Tools
# =============================================================================

@mcp.tool()
async def computer_screenshot() -> list:
    """Takes a screenshot of the computer screen. Use this to see what's on screen."""
    logger.info("computer_screenshot()")
    try:
        result = await computer.screenshot()
        logger.info(f"computer_screenshot() -> {len(result)} bytes")
        return _screenshot_response(result)
    except Exception as e:
        logger.error(f"computer_screenshot() FAILED: {type(e).__name__}: {e}")
        raise


@mcp.tool()
async def mouse_click(x: int, y: int, button: str, repeats: int = 1) -> None:
    """Performs a mouse click.

    Args:
        x: The normalized x coordinate within the [0, 1000] range of the image.
        y: The normalized y coordinate within the [0, 1000] range of the image.
        button: The button to click. Either 'left', 'middle' or 'right'.
        repeats: The number of times to click. Default is 1.
    """
    logger.info(f"mouse_click({x}, {y}, {button}, {repeats})")
    try:
        await computer.mouse_click(_dx(x), _dy(y), button, repeats)
    except Exception as e:
        logger.error(f"mouse_click FAILED: {type(e).__name__}: {e}")
        raise


@mcp.tool()
async def mouse_move(x: int, y: int) -> None:
    """Moves the mouse to a new position.

    Args:
        x: The normalized x coordinate within the [0, 1000] range of the image.
        y: The normalized y coordinate within the [0, 1000] range of the image.
    """
    logger.info(f"mouse_move({x}, {y})")
    await computer.mouse_move(_dx(x), _dy(y))


@mcp.tool()
async def mouse_down(button: str) -> None:
    """Keeps a mouse button down.

    Args:
        button: The button to press down. Either 'left', 'middle' or 'right'.
    """
    logger.info(f"mouse_down({button})")
    await computer.mouse_down(button)


@mcp.tool()
async def mouse_up(button: str) -> None:
    """Releases a mouse button after executing a mouse down action.

    Args:
        button: The button to release. Either 'left', 'middle' or 'right'.
    """
    logger.info(f"mouse_up({button})")
    await computer.mouse_up(button)


@mcp.tool()
async def mouse_scroll(dx: int, dy: int) -> None:
    """Uses the mouse to perform a two dimensional scroll.

    Args:
        dx: The number of pixels to scroll horizontally.
        dy: The number of pixels to scroll vertically.
    """
    logger.info(f"mouse_scroll({dx}, {dy})")
    await computer.mouse_scroll(dx, dy)


@mcp.tool()
async def mouse_drag(x_start: int, y_start: int, x_end: int, y_end: int, button: str = "left") -> None:
    """Drag mouse from a point A to a point B.

    Args:
        x_start: The x coordinate of the starting point normalized within [0, 1000].
        y_start: The y coordinate of the starting point normalized within [0, 1000].
        x_end: The x coordinate of the destination point normalized within [0, 1000].
        y_end: The y coordinate of the destination point normalized within [0, 1000].
        button: The mouse button: left, right, middle. Default is 'left'.
    """
    logger.info(f"mouse_drag({x_start}, {y_start} -> {x_end}, {y_end})")
    await computer.mouse_drag(_dx(x_start), _dy(y_start), _dx(x_end), _dy(y_end), button)


@mcp.tool()
async def wait(seconds: int) -> None:
    """Waits for a given number of seconds. Use if the screen is blank or page is loading.

    Args:
        seconds: The number of seconds to wait.
    """
    logger.info(f"wait({seconds})")
    await computer.wait(seconds)


@mcp.tool()
async def type_text(input_text: str, press_enter: bool) -> None:
    """Type text on a keyboard.

    Args:
        input_text: The input text to type.
        press_enter: Whether to press enter after typing.
    """
    logger.info(f"type_text({input_text[:50]}{'...' if len(input_text) > 50 else ''}, enter={press_enter})")
    try:
        await computer.type_text(input_text, press_enter)
    except Exception as e:
        logger.error(f"type_text FAILED: {type(e).__name__}: {e}")
        raise


@mcp.tool()
async def key_combination(keys_to_press: list[str]) -> None:
    f"""Performs a key combination. {KEY_SPEC}

    Args:
        keys_to_press: The list of keys to press.
    """
    logger.info(f"key_combination({keys_to_press})")
    await computer.key_combination(keys_to_press)


@mcp.tool()
async def key_down(key: str) -> None:
    f"""Keeps a keyboard key down. {KEY_SPEC}

    Args:
        key: The key to press down.
    """
    logger.info(f"key_down({key})")
    await computer.key_down(key)


@mcp.tool()
async def key_up(key: str) -> None:
    f"""Releases a keyboard key after executing a key down action. {KEY_SPEC}

    Args:
        key: The key to press up.
    """
    logger.info(f"key_up({key})")
    await computer.key_up(key)


# =============================================================================
# Routes & Helpers
# =============================================================================

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "url": computer.current_url if computer else ""})


def _dx(x: int) -> int:
    """Denormalize x: [0,1000] -> pixels."""
    return int(x / 1000 * computer.width)


def _dy(y: int) -> int:
    """Denormalize y: [0,1000] -> pixels."""
    return int(y / 1000 * computer.height)


def _screenshot_response(img: bytes) -> list:
    """Return screenshot as proper MCP content types."""
    return [
        ImageContent(type="image", data=base64.b64encode(img).decode(), mimeType="image/png"),
        TextContent(type="text", text=f"URL: {computer.current_url}"),
    ]


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    logger.info(f"Starting CUA Server on port {PORT}")
    mcp.run(transport="streamable-http")
