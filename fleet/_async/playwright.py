import base64
from typing import List, Dict, Any
from playwright.async_api import async_playwright, Browser, Page
from .client import AsyncEnv


# Key mapping for computer use actions
CUA_KEY_TO_PLAYWRIGHT_KEY = {
    "/": "Divide",
    "\\": "Backslash",
    "alt": "Alt",
    "arrowdown": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight",
    "arrowup": "ArrowUp",
    "backspace": "Backspace",
    "capslock": "CapsLock",
    "cmd": "Meta",
    "ctrl": "Control",
    "delete": "Delete",
    "end": "End",
    "enter": "Enter",
    "esc": "Escape",
    "home": "Home",
    "insert": "Insert",
    "option": "Alt",
    "pagedown": "PageDown",
    "pageup": "PageUp",
    "shift": "Shift",
    "space": " ",
    "super": "Meta",
    "tab": "Tab",
    "win": "Meta",
}


class AsyncFleetPlaywrightWrapper:
    """
    A wrapper that adds Playwright browser automation to Fleet environment instances.

    This class handles:
    - Browser connection via CDP
    - Computer actions (click, scroll, type, etc.)
    - Screenshot capture
    - Integration with OpenAI computer use API

    Usage:
        instance = await fleet.env.make(env_key="hubspot", version="v1.2.7")
        browser = AsyncFleetPlaywrightWrapper(instance)
        await browser.start()

        # Use browser methods
        screenshot = await browser.screenshot()
        tools = [browser.openai_cua_tool]

        # Clean up when done
        await browser.close()
    """

    def get_environment(self):
        return "browser"

    def get_dimensions(self):
        return (1920, 1080)

    def __init__(
        self,
        env: AsyncEnv,
        display_width: int = 1920,
        display_height: int = 1080,
    ):
        """
        Initialize the Fleet Playwright wrapper.

        Args:
            env: Fleet environment instance
            display_width: Browser viewport width
            display_height: Browser viewport height
        """
        self.env = env
        self.display_width = display_width
        self.display_height = display_height

        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._started = False

    async def start(self):
        """Start the browser and establish connection."""
        if self._started:
            return

        # Start Playwright
        self._playwright = await async_playwright().start()

        # Start browser on the Fleet instance
        print("Starting browser...")
        await self.env.browser().start()
        cdp = await self.env.browser().describe()

        # Connect to browser
        self._browser = await self._playwright.chromium.connect_over_cdp(
            cdp.cdp_browser_url
        )
        self._page = self._browser.contexts[0].pages[0]
        await self._page.set_viewport_size(
            {"width": self.display_width, "height": self.display_height}
        )

        self._started = True
        print(f"Track agent: {cdp.cdp_devtools_url}")

    async def close(self):
        """Close the browser connection."""
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
            self._browser = None
            self._page = None
            self._started = False

    def _ensure_started(self):
        """Ensure browser is started before operations."""
        if not self._started:
            raise RuntimeError("Browser not started. Call await browser.start() first.")

    @property
    def openai_cua_tool(self) -> Dict[str, Any]:
        """
        Tool definition for OpenAI computer use API.

        Returns:
            Tool definition dict for use with OpenAI responses API
        """
        return {
            "type": "computer_use_preview",
            "display_width": self.display_width,
            "display_height": self.display_height,
            "environment": "browser",
        }

    async def screenshot(self) -> str:
        """
        Take a screenshot and return base64 encoded string.

        Returns:
            Base64 encoded PNG screenshot
        """
        self._ensure_started()

        png_bytes = await self._page.screenshot(full_page=False)
        return base64.b64encode(png_bytes).decode("utf-8")

    def get_current_url(self) -> str:
        """Get the current page URL."""
        self._ensure_started()
        return self._page.url

    async def execute_computer_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a computer action and return the result for OpenAI API.

        Args:
            action: Computer action dict from OpenAI response

        Returns:
            Result dict for computer_call_output
        """
        self._ensure_started()

        action_type = action["type"]
        action_args = {k: v for k, v in action.items() if k != "type"}

        print(f"Executing: {action_type}({action_args})")

        # Execute the action
        if hasattr(self, f"_{action_type}"):
            method = getattr(self, f"_{action_type}")
            await method(**action_args)
        else:
            raise ValueError(f"Unsupported action type: {action_type}")

        # Take screenshot after action
        screenshot_base64 = await self.screenshot()

        return {
            "type": "input_image",
            "image_url": f"data:image/png;base64,{screenshot_base64}",
            "current_url": self.get_current_url(),
        }

    # Computer action implementations
    async def _click(self, x: int, y: int, button: str = "left") -> None:
        """Click at coordinates."""
        self._ensure_started()
        await self._page.mouse.click(x, y, button=button)

    async def _double_click(self, x: int, y: int) -> None:
        """Double-click at coordinates."""
        self._ensure_started()
        await self._page.mouse.dblclick(x, y)

    async def _scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> None:
        """Scroll from coordinates."""
        self._ensure_started()
        await self._page.mouse.move(x, y)
        await self._page.evaluate(f"window.scrollBy({scroll_x}, {scroll_y})")

    async def _type(self, text: str) -> None:
        """Type text."""
        self._ensure_started()
        await self._page.keyboard.type(text)

    async def _keypress(self, keys: List[str]) -> None:
        """Press key combination."""
        self._ensure_started()
        mapped_keys = [CUA_KEY_TO_PLAYWRIGHT_KEY.get(key.lower(), key) for key in keys]
        for key in mapped_keys:
            await self._page.keyboard.down(key)
        for key in reversed(mapped_keys):
            await self._page.keyboard.up(key)

    async def _move(self, x: int, y: int) -> None:
        """Move mouse to coordinates."""
        self._ensure_started()
        await self._page.mouse.move(x, y)

    async def _drag(self, path: List[Dict[str, int]]) -> None:
        """Drag mouse along path."""
        self._ensure_started()
        if not path:
            return
        await self._page.mouse.move(path[0]["x"], path[0]["y"])
        await self._page.mouse.down()
        for point in path[1:]:
            await self._page.mouse.move(point["x"], point["y"])
        await self._page.mouse.up()

    async def _wait(self, ms: int = 1000) -> None:
        """Wait for specified milliseconds."""
        import asyncio

        await asyncio.sleep(ms / 1000)

    # Browser-specific actions
    async def _goto(self, url: str) -> None:
        """Navigate to URL."""
        self._ensure_started()
        try:
            await self._page.goto(url)
        except Exception as e:
            print(f"Error navigating to {url}: {e}")

    async def _back(self) -> None:
        """Go back in browser history."""
        self._ensure_started()
        await self._page.go_back()

    async def _forward(self) -> None:
        """Go forward in browser history."""
        self._ensure_started()
        await self._page.go_forward()

    async def _refresh(self) -> None:
        """Refresh the page."""
        self._ensure_started()
        await self._page.reload()

    # ------------------------------------------------------------------
    # Public aliases (no leading underscore) expected by the Agent &
    # OpenAI computer-use API. They forward directly to the underscored
    # implementations above so the external interface matches the older
    # BasePlaywrightComputer class.
    # ------------------------------------------------------------------

    # Mouse / keyboard actions
    click = _click
    double_click = _double_click
    scroll = _scroll
    type = _type  # noqa: A003 – shadowing built-in for API compatibility
    keypress = _keypress
    move = _move
    drag = _drag
    wait = _wait

    # Browser navigation actions
    goto = _goto
    back = _back
    forward = _forward
    refresh = _refresh
