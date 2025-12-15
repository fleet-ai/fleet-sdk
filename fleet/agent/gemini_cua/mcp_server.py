#!/usr/bin/env python3
"""
CUA Server - Computer Use Agent MCP Server

MCP server with playwright browser control using FastMCP's streamable-http transport.

Env vars:
    FLEET_ENV_URL: URL to navigate to
    FLEET_TASK_PROMPT: Task prompt (resource)
    FLEET_TASK_KEY: Task key (resource)
    PORT: Server port (default: 8765)
    SCREEN_WIDTH/HEIGHT: Browser size
    HEADLESS: "true" or "false" (default: true)
"""

import asyncio
import base64
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import List, Optional, Tuple

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from starlette.requests import Request
from starlette.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# Key Mapping - Action spec keys to Playwright keys
# =============================================================================

PLAYWRIGHT_KEY_MAP = {
    # Common keys
    "enter": "Enter", "return": "Enter", "tab": "Tab",
    "escape": "Escape", "esc": "Escape", "space": " ",
    "backspace": "Backspace", "delete": "Delete", "insert": "Insert",
    
    # Modifiers
    "alt": "Alt", "alt_left": "Alt", "alt_right": "Alt",
    "control": "Control", "control_left": "Control", "control_right": "Control",
    "ctrl": "Control", "ctrl_left": "Control", "ctrl_right": "Control",
    "shift": "Shift", "shift_left": "Shift", "shift_right": "Shift",
    "caps_lock": "CapsLock", "capslock": "CapsLock",
    "meta": "Meta", "meta_left": "Meta", "meta_right": "Meta",
    "command": "Meta", "cmd": "Meta", "super": "Meta", "win": "Meta", "windows": "Meta",
    "num_lock": "NumLock", "numlock": "NumLock",
    "scroll_lock": "ScrollLock", "scrolllock": "ScrollLock",
    
    # Navigation
    "arrow_down": "ArrowDown", "arrow_up": "ArrowUp",
    "arrow_left": "ArrowLeft", "arrow_right": "ArrowRight",
    "down": "ArrowDown", "up": "ArrowUp", "left": "ArrowLeft", "right": "ArrowRight",
    "end": "End", "home": "Home",
    "page_down": "PageDown", "pagedown": "PageDown",
    "page_up": "PageUp", "pageup": "PageUp",
    
    # Function keys
    **{f"f{i}": f"F{i}" for i in range(1, 21)},
    
    # Symbols
    "backquote": "`", "grave": "`", "tilde": "`",
    "backslash": "\\", "bracket_left": "[", "bracketleft": "[",
    "bracket_right": "]", "bracketright": "]",
    "comma": ",", "double_quote": '"', "doublequote": '"',
    "equal": "=", "equals": "=", "minus": "-", "dash": "-",
    "period": ".", "dot": ".", "quote": "'", "apostrophe": "'",
    "semicolon": ";", "slash": "/", "forward_slash": "/", "forwardslash": "/",
    
    # Numpad
    **{f"numpad_{i}": f"Numpad{i}" for i in range(10)},
    **{f"numpad{i}": f"Numpad{i}" for i in range(10)},
    "numpad_add": "NumpadAdd", "numpadadd": "NumpadAdd",
    "numpad_subtract": "NumpadSubtract", "numpadsubtract": "NumpadSubtract",
    "numpad_multiply": "NumpadMultiply", "numpadmultiply": "NumpadMultiply",
    "numpad_divide": "NumpadDivide", "numpaddivide": "NumpadDivide",
    "numpad_decimal": "NumpadDecimal", "numpaddecimal": "NumpadDecimal",
    "numpad_enter": "NumpadEnter", "numpadenter": "NumpadEnter",
    
    # Media
    "audio_volume_mute": "AudioVolumeMute",
    "audio_volume_down": "AudioVolumeDown",
    "audio_volume_up": "AudioVolumeUp",
    "media_track_next": "MediaTrackNext",
    "media_track_previous": "MediaTrackPrevious",
    "media_stop": "MediaStop",
    "media_play_pause": "MediaPlayPause",
    
    # Other
    "print_screen": "PrintScreen", "printscreen": "PrintScreen",
    "pause": "Pause", "context_menu": "ContextMenu", "contextmenu": "ContextMenu",
    "help": "Help",
}

MODIFIER_KEYS = {
    "Alt", "Control", "Shift", "Meta",
    "alt", "alt_left", "alt_right",
    "control", "control_left", "control_right", "ctrl", "ctrl_left", "ctrl_right",
    "shift", "shift_left", "shift_right",
    "meta", "meta_left", "meta_right", "command", "cmd", "super", "win", "windows",
}


def map_key(key: str) -> str:
    """Map action spec key name to Playwright key name."""
    k = key.lower().strip()
    if k in PLAYWRIGHT_KEY_MAP:
        return PLAYWRIGHT_KEY_MAP[k]
    if k.startswith("key_") and len(k) == 5:
        return k[4].lower()
    if k.startswith("digit_") and len(k) == 7:
        return k[6]
    if len(key) == 1:
        return key
    return key


def is_modifier(key: str) -> bool:
    """Check if a key is a modifier key."""
    return key.lower().strip() in MODIFIER_KEYS or map_key(key) in {"Alt", "Control", "Shift", "Meta"}


# =============================================================================
# PlaywrightComputer - Browser control
# =============================================================================

class PlaywrightComputer:
    """Browser control via Playwright."""
    
    def __init__(self, screen_size: Tuple[int, int], initial_url: str,
                 headless: bool = True, highlight_mouse: bool = False):
        self._screen_size = screen_size
        self._initial_url = initial_url
        self._headless = headless
        self._highlight_mouse = highlight_mouse
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
    
    @property
    def width(self) -> int:
        return self._screen_size[0]
    
    @property
    def height(self) -> int:
        return self._screen_size[1]
    
    @property
    def current_url(self) -> str:
        return self._page.url if self._page else ""
    
    async def _handle_new_page(self, new_page: Page):
        """Handle new tab by redirecting to current page."""
        new_url = new_page.url
        await new_page.close()
        await self._page.goto(new_url)
    
    async def start(self):
        """Start the browser."""
        logger.info(f"Starting browser (headless={self._headless})...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                "--no-sandbox", "--disable-extensions", "--disable-file-system",
                "--disable-plugins", "--disable-dev-shm-usage",
                "--disable-background-networking", "--disable-default-apps",
                "--disable-sync",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": self._screen_size[0], "height": self._screen_size[1]}
        )
        self._page = await self._context.new_page()
        self._context.on("page", self._handle_new_page)
        await self._page.goto(self._initial_url)
        await self._page.wait_for_load_state()
        logger.info(f"Browser ready: {self._initial_url}")
    
    async def stop(self):
        """Stop the browser."""
        if self._context:
            await self._context.close()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser stopped")
    
    async def screenshot(self) -> bytes:
        """Take a screenshot."""
        await self._page.wait_for_load_state()
        await asyncio.sleep(0.5)
        return await self._page.screenshot(type="png", full_page=False)
    
    async def _highlight(self, x: int, y: int):
        """Highlight mouse position (for headful debugging)."""
        if not self._highlight_mouse:
            return
        await self._page.evaluate(f"""
            () => {{
                const div = document.createElement('div');
                div.style.cssText = 'position:fixed;width:20px;height:20px;border-radius:50%;border:4px solid red;pointer-events:none;z-index:9999;left:{x-10}px;top:{y-10}px;';
                document.body.appendChild(div);
                setTimeout(() => div.remove(), 2000);
            }}
        """)
        await asyncio.sleep(1)
    
    async def mouse_click(self, x: int, y: int, button: str = "left", repeats: int = 1) -> None:
        await self._highlight(x, y)
        for _ in range(repeats):
            await self._page.mouse.click(x, y, button=button)
        await self._page.wait_for_load_state()
    
    async def mouse_move(self, x: int, y: int) -> None:
        await self._highlight(x, y)
        await self._page.mouse.move(x, y)
        await self._page.wait_for_load_state()
    
    async def mouse_down(self, button: str = "left") -> None:
        await self._page.mouse.down(button=button)
    
    async def mouse_up(self, button: str = "left") -> None:
        await self._page.mouse.up(button=button)
        await self._page.wait_for_load_state()
    
    async def mouse_scroll(self, dx: int, dy: int) -> None:
        await self._page.mouse.wheel(dx, dy)
        await self._page.wait_for_load_state()
    
    async def mouse_drag(self, x_start: int, y_start: int, x_end: int, y_end: int, button: str = "left") -> None:
        await self._highlight(x_start, y_start)
        await self._page.mouse.move(x_start, y_start)
        await self._page.mouse.down(button=button)
        await self._highlight(x_end, y_end)
        await self._page.mouse.move(x_end, y_end)
        await self._page.mouse.up(button=button)
        await self._page.wait_for_load_state()
    
    async def type_text(self, text: str, press_enter: bool = False) -> None:
        await self._page.keyboard.type(text)
        await self._page.wait_for_load_state()
        if press_enter:
            await self._page.keyboard.press("Enter")
            await self._page.wait_for_load_state()
    
    async def key_combination(self, keys: List[str]) -> None:
        """Performs key combination with proper modifier handling."""
        if not keys:
            return
        
        modifiers = [map_key(k) for k in keys if is_modifier(k)]
        regular = [map_key(k) for k in keys if not is_modifier(k)]
        
        for mod in modifiers:
            await self._page.keyboard.down(mod)
        for key in regular:
            await self._page.keyboard.press(key)
        if not regular and modifiers:
            await asyncio.sleep(0.05)
        for mod in reversed(modifiers):
            await self._page.keyboard.up(mod)
        
        await self._page.wait_for_load_state()
    
    async def key_down(self, key: str) -> None:
        await self._page.keyboard.down(map_key(key))
    
    async def key_up(self, key: str) -> None:
        await self._page.keyboard.up(map_key(key))
        await self._page.wait_for_load_state()
    
    async def wait(self, seconds: int) -> None:
        await asyncio.sleep(seconds)


# =============================================================================
# Global state & FastMCP setup
# =============================================================================

computer: Optional[PlaywrightComputer] = None


@asynccontextmanager
async def lifespan(app):
    """Lifespan context manager for browser initialization."""
    global computer
    
    url = os.environ.get("FLEET_ENV_URL", "about:blank")
    width = int(os.environ.get("SCREEN_WIDTH", "1366"))
    height = int(os.environ.get("SCREEN_HEIGHT", "768"))
    headless = os.environ.get("HEADLESS", "true").lower() == "true"
    highlight = os.environ.get("HIGHLIGHT_MOUSE", "false").lower() == "true"
    
    logger.info(f"CUA Server starting")
    logger.info(f"  URL: {url}")
    logger.info(f"  Screen: {width}x{height}")
    logger.info(f"  Headless: {headless}")
    
    computer = PlaywrightComputer(
        screen_size=(width, height),
        initial_url=url,
        headless=headless,
        highlight_mouse=highlight or not headless,
    )
    
    try:
        await computer.start()
        logger.info("Browser ready")
        yield
    finally:
        logger.info("Shutting down browser...")
        await computer.stop()


# Get server configuration from environment
PORT = int(os.environ.get("PORT", "8765"))

# Create MCP server with lifespan for browser management
mcp = FastMCP(
    "cua-server",
    lifespan=lifespan,
    host="0.0.0.0",
    port=PORT,
)


# Health check endpoint for orchestrator
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "url": computer.current_url if computer else ""})


def denorm_x(x: int) -> int:
    """Convert normalized x (0-1000) to pixel coordinate."""
    pixel_x = int(x / 1000 * computer.width)
    logger.info(f"  denorm_x: {x}/1000 * {computer.width} = {pixel_x}")
    return pixel_x


def denorm_y(y: int) -> int:
    """Convert normalized y (0-1000) to pixel coordinate."""
    pixel_y = int(y / 1000 * computer.height)
    logger.info(f"  denorm_y: {y}/1000 * {computer.height} = {pixel_y}")
    return pixel_y


def make_screenshot_response(img: bytes) -> list:
    """Create MCP response with screenshot and URL (only for screenshot tool)."""
    return [
        {"type": "image", "data": base64.b64encode(img).decode(), "mimeType": "image/png"},
        {"type": "text", "text": f"URL: {computer.current_url}"}
    ]


# =============================================================================
# MCP Tools - Clean decorator-based definitions
# =============================================================================

KEY_SPEC = "Key specification: * Common: enter, tab, escape, space, backspace, delete * Modifiers: alt_left, control_left, control_right, shift_left, caps_lock, meta * Navigation: arrow_down, arrow_right, end, home, page_down * Function: f1 to f12 * Alphanumeric: key_a to key_z, digit_0 to digit_9 * Symbols: backquote, backslash, bracket_left, bracket_right, comma, double_quote, equal, minus, period, quote, semicolon, slash * Numpad: numpad_0 to numpad_9, numpad_add, numpad_divide, numpad_enter, numpad_multiply"


@mcp.tool()
async def computer_screenshot() -> list:
    """Takes a screenshot of the computer screen. Use this to see what's on screen."""
    logger.info("computer_screenshot()")
    img = await computer.screenshot()
    return make_screenshot_response(img)


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
    await computer.mouse_click(denorm_x(x), denorm_y(y), button, repeats)


@mcp.tool()
async def mouse_move(x: int, y: int) -> None:
    """Moves the mouse to a new position.

    Args:
        x: The normalized x coordinate within the [0, 1000] range of the image.
        y: The normalized y coordinate within the [0, 1000] range of the image.
    """
    logger.info(f"mouse_move({x}, {y})")
    await computer.mouse_move(denorm_x(x), denorm_y(y))


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
    await computer.mouse_drag(
        denorm_x(x_start), denorm_y(y_start),
        denorm_x(x_end), denorm_y(y_end), button
    )


@mcp.tool()
async def wait(seconds: int) -> None:
    """Waits for a given number of seconds. Use this if the computer screen is blank or website / app is just loading.

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
    logger.info(f"type_text({input_text[:50]}..., {press_enter})")
    await computer.type_text(input_text, press_enter)


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
# Main
# =============================================================================

if __name__ == "__main__":
    logger.info(f"Starting CUA Server on port {PORT}")
    mcp.run(transport="streamable-http")
