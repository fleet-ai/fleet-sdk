import base64
from typing import List, Dict, Callable
from playwright.async_api import async_playwright, Browser, Page
import httpx
import json
import io
from io import BytesIO
from PIL import Image
import os
import asyncio


def sanitize_message(msg: dict) -> dict:
    """Return a copy of the message with image_url omitted for computer_call_output messages."""
    if msg.get("type") == "computer_call_output":
        output = msg.get("output", {})
        if isinstance(output, dict):
            sanitized = msg.copy()
            sanitized["output"] = {**output, "image_url": "[omitted]"}
            return sanitized
    return msg


async def create_response(**kwargs):
    url = "https://api.openai.com/v1/responses"
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
        "Content-Type": "application/json",
    }

    openai_org = os.getenv("OPENAI_ORG")
    if openai_org:
        headers["Openai-Organization"] = openai_org

    # Configure timeout: 30 seconds for connect, 60 seconds for read
    timeout = httpx.Timeout(connect=60.0, read=60.0, write=60.0, pool=60.0)
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers, json=kwargs)

        if response.status_code != 200:
            print(f"Error: {response.status_code} {response.text}")

        return response.json()


def pp(obj):
    print(json.dumps(obj, indent=4))


def show_image(base_64_image):
    image_data = base64.b64decode(base_64_image)
    image = Image.open(BytesIO(image_data))
    image.show()


def calculate_image_dimensions(base_64_image):
    image_data = base64.b64decode(base_64_image)
    image = Image.open(io.BytesIO(image_data))
    return image.size


# Optional: key mapping if your model uses "CUA" style keys
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


class BasePlaywrightComputer:
    """
    Abstract base for Playwright-based computers:

      - Subclasses override `_get_browser_and_page()` to do local or remote connection,
        returning (Browser, Page).
      - This base class handles context creation (`__enter__`/`__exit__`),
        plus standard "Computer" actions like click, scroll, etc.
      - We also have extra browser actions: `goto(url)` and `back()`.
    """

    def get_environment(self):
        return "browser"

    def get_dimensions(self):
        return (1920, 1080)

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def __aenter__(self):
        # Start Playwright and call the subclass hook for getting browser/page
        self._playwright = await async_playwright().start()
        self._browser, self._page = await self._get_browser_and_page()

        # Set up network interception to flag URLs matching domains in BLOCKED_DOMAINS
        async def handle_route(route, request):
            await route.continue_()

        await self._page.route("**/*", handle_route)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # if self._browser:
        #     await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    def get_current_url(self) -> str:
        return self._page.url

    # --- Common "Computer" actions ---
    async def screenshot(self) -> str:
        """Capture only the viewport (not full_page)."""
        png_bytes = await self._page.screenshot(full_page=False)
        return base64.b64encode(png_bytes).decode("utf-8")

    async def click(self, x: int, y: int, button: str = "left") -> None:
        if button == "back":
            await self.back()
        elif button == "forward":
            await self.forward()
        elif button == "wheel":
            await self._page.mouse.wheel(x, y)
        else:
            button_mapping = {"left": "left", "right": "right"}
            button_type = button_mapping.get(button, "left")
            await self._page.mouse.click(x, y, button=button_type)

    async def double_click(self, x: int, y: int) -> None:
        await self._page.mouse.dblclick(x, y)

    async def scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> None:
        await self._page.mouse.move(x, y)
        await self._page.evaluate(f"window.scrollBy({scroll_x}, {scroll_y})")

    async def type(self, text: str) -> None:
        await self._page.keyboard.type(text)

    async def wait(self, ms: int = 1000) -> None:
        await asyncio.sleep(ms / 1000)

    async def move(self, x: int, y: int) -> None:
        await self._page.mouse.move(x, y)

    async def keypress(self, keys: List[str]) -> None:
        mapped_keys = [CUA_KEY_TO_PLAYWRIGHT_KEY.get(key.lower(), key) for key in keys]
        for key in mapped_keys:
            await self._page.keyboard.down(key)
        for key in reversed(mapped_keys):
            await self._page.keyboard.up(key)

    async def drag(self, path: List[Dict[str, int]]) -> None:
        if not path:
            return
        await self._page.mouse.move(path[0]["x"], path[0]["y"])
        await self._page.mouse.down()
        for point in path[1:]:
            await self._page.mouse.move(point["x"], point["y"])
        await self._page.mouse.up()

    # --- Extra browser-oriented actions ---
    async def goto(self, url: str) -> None:
        try:
            return await self._page.goto(url)
        except Exception as e:
            print(f"Error navigating to {url}: {e}")

    async def back(self) -> None:
        return await self._page.go_back()

    async def forward(self) -> None:
        return await self._page.go_forward()

    # --- Subclass hook ---
    async def _get_browser_and_page(self) -> tuple[Browser, Page]:
        """Subclasses must implement, returning (Browser, Page)."""
        raise NotImplementedError


class LocalPlaywrightBrowser(BasePlaywrightComputer):
    """Launches a local Chromium instance using Playwright."""

    def __init__(self, headless: bool = False):
        super().__init__()
        self.headless = headless

    async def _get_browser_and_page(self) -> tuple[Browser, Page]:
        width, height = self.get_dimensions()
        browser = await self._playwright.chromium.connect_over_cdp("wss://fbd0dfae.fleetai.com/cdp/devtools/browser/841e3685-0e59-4d3e-a127-f06573741f62")

        context = browser.contexts[0]

        # Add event listeners for page creation and closure
        context.on("page", self._handle_new_page)

        page = context.pages[0]
        await page.set_viewport_size({"width": width, "height": height})
        page.on("close", self._handle_page_close)

        return browser, page

    def _handle_new_page(self, page: Page):
        """Handle the creation of a new page."""
        print("New page created")
        self._page = page
        page.on("close", self._handle_page_close)

    def _handle_page_close(self, page: Page):
        """Handle the closure of a page."""
        print("Page closed")
        if self._page == page:
            if self._browser.contexts[0].pages:
                self._page = self._browser.contexts[0].pages[-1]
            else:
                print("Warning: All pages have been closed.")
                self._page = None


class Agent:
    """
    A sample agent class that can be used to interact with a computer.

    (See simple_cua_loop.py for a simple example without an agent.)
    """

    def __init__(
        self,
        model="computer-use-preview",
        computer: LocalPlaywrightBrowser = None,
        tools: list[dict] = [],
        acknowledge_safety_check_callback: Callable = lambda: False,
    ):
        self.model = model
        self.computer = computer
        self.tools = tools
        self.print_steps = True
        self.debug = False
        self.show_images = False
        self.acknowledge_safety_check_callback = acknowledge_safety_check_callback

        if computer:
            dimensions = computer.get_dimensions()
            self.tools += [
                {
                    "type": "computer-preview",
                    "display_width": dimensions[0],
                    "display_height": dimensions[1],
                    "environment": computer.get_environment(),
                },
            ]

    def debug_print(self, *args):
        if self.debug:
            pp(*args)

    async def handle_item(self, item):
        """Handle each item; may cause a computer action + screenshot."""
        if item["type"] == "message":
            if self.print_steps:
                print(item["content"][0]["text"])

        if item["type"] == "function_call":
            name, args = item["name"], json.loads(item["arguments"])
            if self.print_steps:
                print(f"{name}({args})")

            if hasattr(self.computer, name):  # if function exists on computer, call it
                method = getattr(self.computer, name)
                await method(**args)
            return [
                {
                    "type": "function_call_output",
                    "call_id": item["call_id"],
                    "output": "success",  # hard-coded output for demo
                }
            ]

        if item["type"] == "computer_call":
            action = item["action"]
            action_type = action["type"]
            action_args = {k: v for k, v in action.items() if k != "type"}
            if self.print_steps:
                print(f"{action_type}({action_args})")

            method = getattr(self.computer, action_type)
            await method(**action_args)

            screenshot_base64 = await self.computer.screenshot()
            if self.show_images:
                show_image(screenshot_base64)

            # if user doesn't ack all safety checks exit with error
            pending_checks = item.get("pending_safety_checks", [])
            for check in pending_checks:
                message = check["message"]
                if not self.acknowledge_safety_check_callback(message):
                    raise ValueError(
                        f"Safety check failed: {message}. Cannot continue with unacknowledged safety checks."
                    )

            call_output = {
                "type": "computer_call_output",
                "call_id": item["call_id"],
                "acknowledged_safety_checks": pending_checks,
                "output": {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{screenshot_base64}",
                },
            }

            # additional URL safety checks for browser environments
            if self.computer.get_environment() == "browser":
                current_url = self.computer.get_current_url()
                call_output["output"]["current_url"] = current_url

            return [call_output]
        return []

    async def run_full_turn(
        self, input_items, print_steps=True, debug=False, show_images=False
    ):
        self.print_steps = print_steps
        self.debug = debug
        self.show_images = show_images
        new_items = []

        # keep looping until we get a final response
        while new_items[-1].get("role") != "assistant" if new_items else True:
            self.debug_print([sanitize_message(msg) for msg in input_items + new_items])

            response = await create_response(
                model=self.model,
                input=input_items + new_items,
                tools=self.tools,
                truncation="auto",
            )
            self.debug_print(response)

            if "output" not in response and self.debug:
                print(response)
                raise ValueError("No output from model")
            else:
                new_items += response["output"]
                for item in response["output"]:
                    new_items += await self.handle_item(item)

        return new_items


tools = []


async def ainput(prompt: str = "") -> str:
    """Async version of input()"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, input, prompt)


async def main():
    async with LocalPlaywrightBrowser() as computer:
        agent = Agent(computer=computer, tools=tools)
        items = [
            {
                "role": "developer",
                "content": "You have access to a clone of Hubspot. You can use the computer to navigate the browser and perform actions.",
            }
        ]
        while True:
            user_input = await ainput("> ")
            items.append({"role": "user", "content": user_input})
            output_items = await agent.run_full_turn(items, show_images=False)
            items += output_items


if __name__ == "__main__":
    asyncio.run(main())
