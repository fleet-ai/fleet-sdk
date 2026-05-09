import ast
import asyncio
import base64
import json
import sys
from datetime import datetime
from typing import Any, List, Literal, Optional

import fleet
import playwright.async_api
import pydantic
from anthropic import AsyncAnthropic
from anthropic.types.beta import (
    BetaMessageParam,
    BetaTextBlockParam,
    BetaToolUnionParam,
    BetaToolResultBlockParam,
)
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()


client = AsyncAnthropic()


MODEL = "claude-opus-4-7"
DISPLAY_WIDTH = 1366
DISPLAY_HEIGHT = 768
COMPUTER_TOOL_TYPE = "computer_20251124"
BETA_HEADER = "computer-use-2025-11-24"
MAX_TURNS = 200
HEADLESS = True


def save_to_tmp(content: str, prefix: str = "output", extension: str = "txt") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{prefix}_{timestamp}.{extension}"
    filepath = f"/tmp/{filename}"

    with open(filepath, "w") as f:
        f.write(content)

    return filepath


def save_screenshot(screenshot_bytes: bytes, prefix: str = "screenshot") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filepath = f"/tmp/{prefix}_{timestamp}.png"
    with open(filepath, "wb") as f:
        f.write(screenshot_bytes)
    return filepath


def _block_field(block: Any, key: str) -> Any:
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


def verifier_accepts_conversation(verifier_func: Optional[str]) -> bool:
    """Return True if the verifier's top-level function declares a `conversation` param."""
    if not verifier_func:
        return False
    try:
        tree = ast.parse(verifier_func)
    except SyntaxError:
        return False

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            param_names = {a.arg for a in args.args} | {a.arg for a in args.kwonlyargs}
            return "conversation" in param_names
    return False


def to_openai_conversation(
    system: List[BetaTextBlockParam],
    messages: List[BetaMessageParam],
) -> List[dict]:
    """Convert Anthropic-format system+messages into OpenAI chat schema.

    Same shape as fleet_harness.py's helper. Computer-use tool_use blocks
    serialize their action dict into the `function.arguments` JSON string;
    image-bearing tool_result blocks collapse to a `[screenshot]` placeholder
    so the conversation stays text-only for verifiers.
    """
    out: List[dict] = []

    system_text = "\n\n".join(
        b["text"] for b in system if b.get("type") == "text" and b.get("text")
    )
    if system_text:
        out.append({"role": "system", "content": system_text})

    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        blocks = [content] if isinstance(content, str) else list(content)

        if role == "user":
            text_parts: List[str] = []
            tool_msgs: List[dict] = []
            for block in blocks:
                if isinstance(block, str):
                    text_parts.append(block)
                    continue
                btype = _block_field(block, "type")
                if btype == "text":
                    text_parts.append(_block_field(block, "text") or "")
                elif btype == "tool_result":
                    tool_content = _block_field(block, "content")
                    if isinstance(tool_content, list):
                        rendered: List[str] = []
                        for sub in tool_content:
                            sub_type = _block_field(sub, "type")
                            if sub_type == "text":
                                rendered.append(_block_field(sub, "text") or "")
                            elif sub_type == "image":
                                rendered.append("[screenshot]")
                        tool_content = "\n".join(rendered) if rendered else ""
                    elif not isinstance(tool_content, str):
                        tool_content = json.dumps(tool_content, default=str)
                    tool_msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": _block_field(block, "tool_use_id"),
                            "content": tool_content,
                        }
                    )

            if text_parts:
                out.append({"role": "user", "content": "\n".join(text_parts)})
            out.extend(tool_msgs)
            continue

        if role == "assistant":
            text_parts = []
            tool_calls: List[dict] = []
            for block in blocks:
                btype = _block_field(block, "type")
                if btype == "text":
                    text_parts.append(_block_field(block, "text") or "")
                elif btype == "tool_use":
                    tool_calls.append(
                        {
                            "id": _block_field(block, "id"),
                            "type": "function",
                            "function": {
                                "name": _block_field(block, "name"),
                                "arguments": json.dumps(
                                    _block_field(block, "input") or {}
                                ),
                            },
                        }
                    )

            entry: dict = {
                "role": "assistant",
                "content": "\n".join(text_parts) if text_parts else None,
            }
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)

    return out


# ---------------------------------------------------------------------------
# Playwright browser
# ---------------------------------------------------------------------------

# Map Anthropic / xdotool key names to Playwright key names.
# Anthropic's `key` action uses xdotool syntax: e.g. "Return", "ctrl+s",
# "Page_Down", "shift+Tab". We split on '+', map each token, and feed it back
# to Playwright. Unknown tokens (single chars like 'a') pass through.
PLAYWRIGHT_KEY_MAP = {
    "return": "Enter",
    "enter": "Enter",
    "kp_enter": "Enter",
    "tab": "Tab",
    "backspace": "Backspace",
    "delete": "Delete",
    "escape": "Escape",
    "esc": "Escape",
    "space": " ",
    "shift": "Shift",
    "shift_l": "Shift",
    "shift_r": "Shift",
    "ctrl": "Control",
    "control": "Control",
    "control_l": "Control",
    "control_r": "Control",
    "alt": "Alt",
    "alt_l": "Alt",
    "alt_r": "Alt",
    "meta": "Meta",
    "super": "Meta",
    "super_l": "Meta",
    "super_r": "Meta",
    "cmd": "Meta",
    "command": "Meta",
    "win": "Meta",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "page_up": "PageUp",
    "pageup": "PageUp",
    "page_down": "PageDown",
    "pagedown": "PageDown",
    "home": "Home",
    "end": "End",
    "insert": "Insert",
    "caps_lock": "CapsLock",
    "f1": "F1",
    "f2": "F2",
    "f3": "F3",
    "f4": "F4",
    "f5": "F5",
    "f6": "F6",
    "f7": "F7",
    "f8": "F8",
    "f9": "F9",
    "f10": "F10",
    "f11": "F11",
    "f12": "F12",
    "minus": "-",
    "plus": "+",
    "equal": "=",
    "underscore": "_",
    "slash": "/",
    "backslash": "\\",
    "semicolon": ";",
    "apostrophe": "'",
    "grave": "`",
    "comma": ",",
    "period": ".",
    "bracketleft": "[",
    "bracketright": "]",
}


def normalize_key(token: str) -> str:
    return PLAYWRIGHT_KEY_MAP.get(token.lower(), token)


def parse_key_combo(text: str) -> List[str]:
    """Parse an xdotool-style key string ('ctrl+shift+t') into Playwright keys."""
    return [normalize_key(t) for t in text.split("+") if t]


class EnvState(pydantic.BaseModel):
    screenshot: bytes
    url: str


class PlaywrightComputer:
    """Local Playwright browser exposed through Claude computer-use semantics.

    Coordinates here are *absolute pixels* (no 0-1000 normalization), matching
    Claude Opus 4.7's 1:1 pixel-to-coordinate behavior.
    """

    def __init__(
        self,
        screen_size: tuple[int, int],
        initial_url: str,
        headless: bool = True,
        highlight_mouse: bool = False,
    ):
        self._initial_url = initial_url
        self._screen_size = screen_size
        self._headless = headless
        self._highlight_mouse = highlight_mouse

    async def _handle_new_page(self, new_page: playwright.async_api.Page):
        """Computer use is single-tab; redirect new tabs into the main page."""
        new_url = new_page.url
        await new_page.close()
        if new_url and new_url != "about:blank":
            await self._page.goto(new_url)

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            args=[
                "--disable-extensions",
                "--disable-file-system",
                "--disable-plugins",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
            ],
            headless=self._headless,
        )
        self._context = await self._browser.new_context(
            viewport={
                "width": self._screen_size[0],
                "height": self._screen_size[1],
            }
        )
        self._page = await self._context.new_page()
        await self._page.goto(self._initial_url)
        self._context.on("page", self._handle_new_page)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            await self._context.close()
        try:
            await self._browser.close()
        except Exception as e:
            if "Browser.close: Connection closed while reading from the driver" in str(
                e
            ):
                pass
            else:
                raise
        await self._playwright.stop()

    async def _safe_wait_for_load(self, timeout_ms: int = 5000):
        try:
            await self._page.wait_for_load_state(timeout=timeout_ms)
        except playwright.async_api.TimeoutError:
            pass

    async def screenshot(self) -> EnvState:
        await self._safe_wait_for_load()
        await asyncio.sleep(0.4)
        png = await self._page.screenshot(type="png", full_page=False)
        return EnvState(screenshot=png, url=self._page.url)

    async def highlight_mouse(self, x: int, y: int):
        if not self._highlight_mouse:
            return
        await self._page.evaluate(
            """([x, y]) => {
                const div = document.createElement('div');
                div.style.pointerEvents = 'none';
                div.style.border = '4px solid red';
                div.style.borderRadius = '50%';
                div.style.width = '20px';
                div.style.height = '20px';
                div.style.position = 'fixed';
                div.style.zIndex = '999999';
                div.style.left = (x - 10) + 'px';
                div.style.top = (y - 10) + 'px';
                document.body.appendChild(div);
                setTimeout(() => div.remove(), 1500);
            }""",
            [x, y],
        )

    async def _click(
        self,
        x: int,
        y: int,
        button: Literal["left", "right", "middle"] = "left",
        click_count: int = 1,
        modifiers: Optional[List[str]] = None,
    ) -> EnvState:
        await self.highlight_mouse(x, y)
        await self._page.mouse.click(
            x, y, button=button, click_count=click_count, modifiers=modifiers or []
        )
        await self._safe_wait_for_load()
        return await self.screenshot()

    async def left_click(
        self, x: int, y: int, modifiers: Optional[List[str]] = None
    ) -> EnvState:
        return await self._click(x, y, "left", modifiers=modifiers)

    async def right_click(
        self, x: int, y: int, modifiers: Optional[List[str]] = None
    ) -> EnvState:
        return await self._click(x, y, "right", modifiers=modifiers)

    async def middle_click(
        self, x: int, y: int, modifiers: Optional[List[str]] = None
    ) -> EnvState:
        return await self._click(x, y, "middle", modifiers=modifiers)

    async def double_click(
        self, x: int, y: int, modifiers: Optional[List[str]] = None
    ) -> EnvState:
        return await self._click(x, y, "left", click_count=2, modifiers=modifiers)

    async def triple_click(
        self, x: int, y: int, modifiers: Optional[List[str]] = None
    ) -> EnvState:
        return await self._click(x, y, "left", click_count=3, modifiers=modifiers)

    async def mouse_move(self, x: int, y: int) -> EnvState:
        await self.highlight_mouse(x, y)
        await self._page.mouse.move(x, y)
        return await self.screenshot()

    async def left_mouse_down(self, x: Optional[int], y: Optional[int]) -> EnvState:
        if x is not None and y is not None:
            await self._page.mouse.move(x, y)
        await self._page.mouse.down(button="left")
        return await self.screenshot()

    async def left_mouse_up(self, x: Optional[int], y: Optional[int]) -> EnvState:
        if x is not None and y is not None:
            await self._page.mouse.move(x, y)
        await self._page.mouse.up(button="left")
        return await self.screenshot()

    async def left_click_drag(
        self, start: tuple[int, int], end: tuple[int, int]
    ) -> EnvState:
        await self.highlight_mouse(*start)
        await self._page.mouse.move(*start)
        await self._page.mouse.down()
        await self.highlight_mouse(*end)
        await self._page.mouse.move(*end, steps=20)
        await self._page.mouse.up()
        await self._safe_wait_for_load()
        return await self.screenshot()

    async def type_text(self, text: str) -> EnvState:
        await self._page.keyboard.type(text)
        await self._safe_wait_for_load()
        return await self.screenshot()

    async def key(self, text: str) -> EnvState:
        keys = parse_key_combo(text)
        if not keys:
            return await self.screenshot()
        for k in keys[:-1]:
            await self._page.keyboard.down(k)
        await self._page.keyboard.press(keys[-1])
        for k in reversed(keys[:-1]):
            await self._page.keyboard.up(k)
        await self._safe_wait_for_load()
        return await self.screenshot()

    async def hold_key(self, text: str, duration: float) -> EnvState:
        keys = parse_key_combo(text)
        for k in keys:
            await self._page.keyboard.down(k)
        await asyncio.sleep(min(duration, 10.0))
        for k in reversed(keys):
            await self._page.keyboard.up(k)
        return await self.screenshot()

    async def scroll(
        self,
        x: int,
        y: int,
        direction: Literal["up", "down", "left", "right"],
        amount: int,
        modifiers: Optional[List[str]] = None,
    ) -> EnvState:
        await self._page.mouse.move(x, y)
        # `scroll_amount` is in "clicks"; treat each as ~100px.
        step = 100 * max(int(amount), 1)
        dx, dy = 0, 0
        if direction == "up":
            dy = -step
        elif direction == "down":
            dy = step
        elif direction == "left":
            dx = -step
        elif direction == "right":
            dx = step
        modifiers = modifiers or []
        for k in modifiers:
            await self._page.keyboard.down(k)
        await self._page.mouse.wheel(dx, dy)
        for k in reversed(modifiers):
            await self._page.keyboard.up(k)
        await self._safe_wait_for_load()
        return await self.screenshot()

    async def wait(self, duration: float) -> EnvState:
        await asyncio.sleep(min(duration, 30.0))
        return await self.screenshot()

    async def cursor_position(self) -> EnvState:
        # Playwright doesn't expose mouse position; just return a screenshot.
        return await self.screenshot()


# ---------------------------------------------------------------------------
# Action dispatch
# ---------------------------------------------------------------------------


def _coord(value: Any) -> tuple[int, int]:
    if value is None:
        return 0, 0
    return int(value[0]), int(value[1])


def _modifiers_from_text(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return [normalize_key(t) for t in text.split("+") if t]


async def execute_computer_action(
    computer: PlaywrightComputer, tool_input: dict
) -> tuple[EnvState | None, str | None, bool]:
    """Run a computer-use tool call.

    Returns `(state, error_text, is_error)`. Exactly one of `state`/`error_text`
    is set. Caller turns `state` into an image tool_result block; `error_text`
    into a text tool_result with `is_error=True`.
    """
    action = tool_input.get("action")
    try:
        if action == "screenshot":
            return await computer.screenshot(), None, False

        if action == "left_click":
            x, y = _coord(tool_input.get("coordinate"))
            return (
                await computer.left_click(
                    x, y, _modifiers_from_text(tool_input.get("text"))
                ),
                None,
                False,
            )

        if action == "right_click":
            x, y = _coord(tool_input.get("coordinate"))
            return (
                await computer.right_click(
                    x, y, _modifiers_from_text(tool_input.get("text"))
                ),
                None,
                False,
            )

        if action == "middle_click":
            x, y = _coord(tool_input.get("coordinate"))
            return (
                await computer.middle_click(
                    x, y, _modifiers_from_text(tool_input.get("text"))
                ),
                None,
                False,
            )

        if action == "double_click":
            x, y = _coord(tool_input.get("coordinate"))
            return (
                await computer.double_click(
                    x, y, _modifiers_from_text(tool_input.get("text"))
                ),
                None,
                False,
            )

        if action == "triple_click":
            x, y = _coord(tool_input.get("coordinate"))
            return (
                await computer.triple_click(
                    x, y, _modifiers_from_text(tool_input.get("text"))
                ),
                None,
                False,
            )

        if action == "mouse_move":
            x, y = _coord(tool_input.get("coordinate"))
            return await computer.mouse_move(x, y), None, False

        if action == "left_mouse_down":
            coord = tool_input.get("coordinate")
            x, y = _coord(coord) if coord else (None, None)
            return await computer.left_mouse_down(x, y), None, False

        if action == "left_mouse_up":
            coord = tool_input.get("coordinate")
            x, y = _coord(coord) if coord else (None, None)
            return await computer.left_mouse_up(x, y), None, False

        if action == "left_click_drag":
            start = _coord(tool_input.get("start_coordinate"))
            end = _coord(tool_input.get("coordinate"))
            return await computer.left_click_drag(start, end), None, False

        if action == "type":
            text = tool_input.get("text") or ""
            return await computer.type_text(text), None, False

        if action == "key":
            text = tool_input.get("text") or ""
            return await computer.key(text), None, False

        if action == "hold_key":
            text = tool_input.get("text") or ""
            duration = float(tool_input.get("duration", 1))
            return await computer.hold_key(text, duration), None, False

        if action == "scroll":
            x, y = _coord(tool_input.get("coordinate"))
            direction = tool_input.get("scroll_direction", "down")
            amount = int(tool_input.get("scroll_amount", 3))
            return (
                await computer.scroll(
                    x,
                    y,
                    direction,
                    amount,
                    _modifiers_from_text(tool_input.get("text")),
                ),
                None,
                False,
            )

        if action == "wait":
            duration = float(tool_input.get("duration", 1))
            return await computer.wait(duration), None, False

        if action == "cursor_position":
            return await computer.cursor_position(), None, False

        return None, f"Unsupported action: {action!r}", True

    except Exception as e:
        return None, f"Action {action!r} failed: {type(e).__name__}: {e}", True


def screenshot_to_block(state: EnvState) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(state.screenshot).decode("utf-8"),
        },
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def main():
    tasks = await fleet.load_tasks_async(
        keys=["task_intlycg3my7r_n_1769564666070_elnq81y45"]
    )
    task = tasks[0]

    print("Task Key:", task.key)
    print("Task Prompt:", task.prompt)

    env = await fleet.env.make_async(
        env_key=task.env_key,
        data_key=task.data_key,
        env_variables=task.env_variables,
        ttl_seconds=3600,
    )
    print("Instance URL:", env.urls.root)

    app_url = env.urls.app[0] if env.urls.app else env.urls.root
    print(f"App URL: {app_url}")

    computer_tool: BetaToolUnionParam = {
        "type": COMPUTER_TOOL_TYPE,
        "name": "computer",
        "display_width_px": DISPLAY_WIDTH,
        "display_height_px": DISPLAY_HEIGHT,
        "display_number": 1,
    }
    tools: List[BetaToolUnionParam] = [computer_tool]

    system: List[BetaTextBlockParam] = [
        {
            "type": "text",
            "text": (
                f"You control a Chromium browser via the `computer` tool. "
                f"The viewport is {DISPLAY_WIDTH}x{DISPLAY_HEIGHT} pixels and "
                f"coordinates are absolute pixels (no normalization). "
                f"The browser is already pointed at the task app. Complete the task. "
                f"Take a screenshot whenever you need to see the current state. "
                f"The session ends when you stop calling tools and emit a final text "
                f"answer. Avoid unnecessary actions, as side effects may be graded as "
                f"task failure."
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages: List[BetaMessageParam] = [
        {
            "role": "user",
            "content": [{"type": "text", "text": task.prompt}],
        }
    ]

    response = None
    final_answer: str = ""

    async with PlaywrightComputer(
        screen_size=(DISPLAY_WIDTH, DISPLAY_HEIGHT),
        initial_url=app_url,
        headless=HEADLESS,
        highlight_mouse=not HEADLESS,
    ) as computer:
        initial = await computer.screenshot()
        save_screenshot(initial.screenshot, "initial")
        # Seed the model with an initial screenshot so it doesn't waste a turn
        # asking for one.
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Initial browser screenshot:"},
                    screenshot_to_block(initial),
                ],
            }
        )

        for turn in range(1, MAX_TURNS + 1):
            print(f"\n{'=' * 50}")
            print(f"Turn {turn} - sending {len(messages)} messages")

            messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}

            print("\nAssistant: ", end="", flush=True)
            async with client.beta.messages.stream(
                model=MODEL,
                max_tokens=8192,
                messages=messages,
                tools=tools,
                system=system,
                betas=[BETA_HEADER],
            ) as stream:
                async for text in stream.text_stream:
                    print(text, end="", flush=True)
                response = await stream.get_final_message()
            print()

            del messages[-1]["content"][-1]["cache_control"]

            usage = response.usage
            print(f"Stop reason: {response.stop_reason}")
            print(
                f"Tokens: input={usage.input_tokens} output={usage.output_tokens} "
                f"cache_read={getattr(usage, 'cache_read_input_tokens', 0)} "
                f"cache_create={getattr(usage, 'cache_creation_input_tokens', 0)}"
            )

            messages.append({"role": "assistant", "content": response.content})

            tool_results: List[BetaToolResultBlockParam] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                action = (
                    block.input.get("action") if isinstance(block.input, dict) else None
                )
                print(f"\nTool ({block.name}): action={action} input={block.input}")

                state, error_text, is_error = await execute_computer_action(
                    computer, dict(block.input) if isinstance(block.input, dict) else {}
                )

                if is_error or state is None:
                    print(f"  -> error: {error_text}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": error_text or "Unknown error",
                            "is_error": True,
                        }
                    )
                    continue

                screenshot_path = save_screenshot(
                    state.screenshot, f"turn{turn}_{action}"
                )
                print(f"  -> {state.url} | screenshot: {screenshot_path}")

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": [screenshot_to_block(state)],
                    }
                )

            if not tool_results:
                break

            messages.append({"role": "user", "content": tool_results})

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        transcript_filename = f"messages_cu_transcript_{timestamp}.json"
        transcript_path = f"/tmp/{transcript_filename}"

        # Strip image data from the transcript so the JSON stays readable.
        sanitized: List[dict] = []
        for msg in messages:
            content = msg["content"]
            if isinstance(content, str):
                sanitized.append({"role": msg["role"], "content": content})
                continue
            new_blocks = []
            for block in content:
                btype = _block_field(block, "type")
                if btype == "image":
                    new_blocks.append({"type": "image", "source": "[omitted]"})
                elif btype == "tool_result":
                    inner = _block_field(block, "content")
                    if isinstance(inner, list):
                        rendered = []
                        for sub in inner:
                            sub_type = _block_field(sub, "type")
                            if sub_type == "image":
                                rendered.append(
                                    {"type": "image", "source": "[omitted]"}
                                )
                            else:
                                rendered.append(
                                    sub if isinstance(sub, dict) else dict(sub.__dict__)
                                )
                        new_blocks.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": _block_field(block, "tool_use_id"),
                                "content": rendered,
                                "is_error": _block_field(block, "is_error") or False,
                            }
                        )
                    else:
                        new_blocks.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": _block_field(block, "tool_use_id"),
                                "content": inner,
                                "is_error": _block_field(block, "is_error") or False,
                            }
                        )
                else:
                    new_blocks.append(
                        block if isinstance(block, dict) else dict(block.__dict__)
                    )
            sanitized.append({"role": msg["role"], "content": new_blocks})

        with open(transcript_path, "w") as f:
            json.dump(sanitized, f, indent=2, default=str)
        print(f"\nFull transcript saved to: {transcript_path}")

    if response is not None:
        for block in reversed(response.content):
            if block.type == "text" and block.text:
                final_answer = block.text
                break

    print(f"\nFinal Answer: {final_answer}")

    verify_kwargs: dict = {"final_answer": final_answer}
    if verifier_accepts_conversation(task.verifier_func):
        verify_kwargs["conversation"] = json.dumps(
            to_openai_conversation(system, messages)
        )
        print("Verifier accepts `conversation` param; passing it as a JSON string.")
    else:
        print("Verifier does not accept `conversation` param; skipping.")

    result = await task.verify_detailed_async(env, **verify_kwargs)
    print("Verifier error:", result.error)
    print("Verifier stdout:", result.stdout)
    print("Reward score:", result.result)

    await env.close()


if __name__ == "__main__":
    asyncio.run(main())
