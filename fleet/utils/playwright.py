"""Playwright browser control utilities.

Provides PlaywrightComputer class for browser automation with:
- Mouse actions (click, move, drag, scroll)
- Keyboard actions (type, key combinations)
- Screenshot capture
- Normalized coordinate support (0-1000 range)

Key mapping follows the action spec convention for cross-platform compatibility.
"""

import asyncio
import logging
from typing import List, Optional, Tuple

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

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

# Key specification for tool docstrings
KEY_SPEC = (
    "Key specification: * Common: enter, tab, escape, space, backspace, delete "
    "* Modifiers: alt_left, control_left, control_right, shift_left, caps_lock, meta "
    "* Navigation: arrow_down, arrow_right, end, home, page_down "
    "* Function: f1 to f12 "
    "* Alphanumeric: key_a to key_z, digit_0 to digit_9 "
    "* Symbols: backquote, backslash, bracket_left, bracket_right, comma, double_quote, "
    "equal, minus, period, quote, semicolon, slash "
    "* Numpad: numpad_0 to numpad_9, numpad_add, numpad_divide, numpad_enter, numpad_multiply"
)


def map_key(key: str) -> str:
    """Map action spec key name to Playwright key name.
    
    Args:
        key: Key name in action spec format (e.g., "key_a", "control_left")
        
    Returns:
        Playwright key name (e.g., "a", "Control")
    """
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
    """Check if a key is a modifier key.
    
    Args:
        key: Key name to check
        
    Returns:
        True if the key is a modifier (Alt, Control, Shift, Meta)
    """
    return key.lower().strip() in MODIFIER_KEYS or map_key(key) in {"Alt", "Control", "Shift", "Meta"}


# =============================================================================
# PlaywrightComputer - Browser control
# =============================================================================

class PlaywrightComputer:
    """Browser control via Playwright.
    
    Provides a high-level interface for browser automation:
    - Mouse actions with optional visual highlighting
    - Keyboard input with proper modifier handling
    - Screenshot capture
    - Automatic page load waiting
    
    Args:
        screen_size: Tuple of (width, height) for viewport
        initial_url: URL to navigate to on start
        headless: Run browser without visible window
        highlight_mouse: Show visual indicator for mouse actions (useful for debugging)
    
    Example:
        computer = PlaywrightComputer(
            screen_size=(1366, 768),
            initial_url="https://example.com",
            headless=False,
            highlight_mouse=True,
        )
        await computer.start()
        await computer.mouse_click(683, 384)  # Click center
        screenshot = await computer.screenshot()
        await computer.stop()
    """
    
    def __init__(
        self,
        screen_size: Tuple[int, int],
        initial_url: str,
        headless: bool = True,
        highlight_mouse: bool = False,
    ):
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
        """Viewport width in pixels."""
        return self._screen_size[0]
    
    @property
    def height(self) -> int:
        """Viewport height in pixels."""
        return self._screen_size[1]
    
    @property
    def current_url(self) -> str:
        """Current page URL."""
        return self._page.url if self._page else ""
    
    async def _handle_new_page(self, new_page: Page):
        """Handle new tab by redirecting to current page."""
        new_url = new_page.url
        await new_page.close()
        await self._page.goto(new_url)
    
    async def start(self):
        """Start the browser and navigate to initial URL."""
        logger.info(f"Starting browser (headless={self._headless})...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                "--no-sandbox",
                "--disable-extensions",
                "--disable-file-system",
                "--disable-plugins",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-default-apps",
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
        """Stop the browser and clean up resources."""
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
        """Take a screenshot of the current viewport.
        
        Returns:
            PNG image data as bytes
        """
        await self._page.wait_for_load_state()
        await asyncio.sleep(0.5)
        return await self._page.screenshot(type="png", full_page=False)
    
    async def _highlight(self, x: int, y: int):
        """Show visual highlight at mouse position (for debugging)."""
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
    
    # -------------------------------------------------------------------------
    # Mouse actions
    # -------------------------------------------------------------------------
    
    async def mouse_click(self, x: int, y: int, button: str = "left", repeats: int = 1) -> None:
        """Click at position.
        
        Args:
            x: X coordinate in pixels
            y: Y coordinate in pixels
            button: Mouse button ('left', 'middle', 'right')
            repeats: Number of clicks (2 for double-click)
        """
        await self._highlight(x, y)
        for _ in range(repeats):
            await self._page.mouse.click(x, y, button=button)
        await self._page.wait_for_load_state()
    
    async def mouse_move(self, x: int, y: int) -> None:
        """Move mouse to position.
        
        Args:
            x: X coordinate in pixels
            y: Y coordinate in pixels
        """
        await self._highlight(x, y)
        await self._page.mouse.move(x, y)
        await self._page.wait_for_load_state()
    
    async def mouse_down(self, button: str = "left") -> None:
        """Press mouse button down.
        
        Args:
            button: Mouse button ('left', 'middle', 'right')
        """
        await self._page.mouse.down(button=button)
    
    async def mouse_up(self, button: str = "left") -> None:
        """Release mouse button.
        
        Args:
            button: Mouse button ('left', 'middle', 'right')
        """
        await self._page.mouse.up(button=button)
        await self._page.wait_for_load_state()
    
    async def mouse_scroll(self, dx: int, dy: int) -> None:
        """Scroll the mouse wheel.
        
        Args:
            dx: Horizontal scroll amount in pixels
            dy: Vertical scroll amount in pixels
        """
        await self._page.mouse.wheel(dx, dy)
        await self._page.wait_for_load_state()
    
    async def mouse_drag(
        self,
        x_start: int,
        y_start: int,
        x_end: int,
        y_end: int,
        button: str = "left",
    ) -> None:
        """Drag from one position to another.
        
        Args:
            x_start: Starting X coordinate
            y_start: Starting Y coordinate
            x_end: Ending X coordinate
            y_end: Ending Y coordinate
            button: Mouse button to hold during drag
        """
        await self._highlight(x_start, y_start)
        await self._page.mouse.move(x_start, y_start)
        await self._page.mouse.down(button=button)
        await self._highlight(x_end, y_end)
        await self._page.mouse.move(x_end, y_end)
        await self._page.mouse.up(button=button)
        await self._page.wait_for_load_state()
    
    # -------------------------------------------------------------------------
    # Keyboard actions
    # -------------------------------------------------------------------------
    
    async def type_text(self, text: str, press_enter: bool = False) -> None:
        """Type text using the keyboard.
        
        Args:
            text: Text to type
            press_enter: Whether to press Enter after typing
        """
        await self._page.keyboard.type(text)
        await self._page.wait_for_load_state()
        if press_enter:
            await self._page.keyboard.press("Enter")
            await self._page.wait_for_load_state()
    
    async def key_combination(self, keys: List[str]) -> None:
        """Press a key combination (e.g., Ctrl+C).
        
        Handles modifiers properly - holds them down while pressing other keys.
        
        Args:
            keys: List of keys to press together
        """
        if not keys:
            return
        
        modifiers = [map_key(k) for k in keys if is_modifier(k)]
        regular = [map_key(k) for k in keys if not is_modifier(k)]
        
        # Press modifiers down
        for mod in modifiers:
            await self._page.keyboard.down(mod)
        
        # Press regular keys
        for key in regular:
            await self._page.keyboard.press(key)
        
        # If only modifiers, brief pause
        if not regular and modifiers:
            await asyncio.sleep(0.05)
        
        # Release modifiers
        for mod in reversed(modifiers):
            await self._page.keyboard.up(mod)
        
        await self._page.wait_for_load_state()
    
    async def key_down(self, key: str) -> None:
        """Press a key down (without releasing).
        
        Args:
            key: Key to press down
        """
        await self._page.keyboard.down(map_key(key))
    
    async def key_up(self, key: str) -> None:
        """Release a key.
        
        Args:
            key: Key to release
        """
        await self._page.keyboard.up(map_key(key))
        await self._page.wait_for_load_state()
    
    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------
    
    async def wait(self, seconds: int) -> None:
        """Wait for a number of seconds.
        
        Args:
            seconds: Number of seconds to wait
        """
        await asyncio.sleep(seconds)
    
    async def goto(self, url: str) -> None:
        """Navigate to a URL.
        
        Args:
            url: URL to navigate to
        """
        await self._page.goto(url)
        await self._page.wait_for_load_state()

