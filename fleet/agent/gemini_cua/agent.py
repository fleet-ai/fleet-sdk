#!/usr/bin/env python3
"""
Gemini CUA Agent (Standalone)

Env vars:
    GEMINI_API_KEY: API key
    FLEET_MCP_URL: CUA server URL (http://localhost:PORT)
    FLEET_TASK_PROMPT: Task prompt
    FLEET_TASK_KEY: Task key
    FLEET_MODEL: Model (default: gemini-3-pro-preview)
    FLEET_MAX_STEPS: Max steps (default: 200)
    FLEET_VERBOSE: Enable verbose logging (default: false)
    USE_OAUTH: Use gcloud OAuth instead of API key (default: false)
    GOOG_PROJECT: Google Cloud project for OAuth (default: gemini-agents-area)
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from google.genai.types import Content, Part
from google import genai
from google.genai import types
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import fleet
from fleet.utils.logging import log_verbose, VERBOSE

# Whitelist hooks for auto-detecting model endpoints (optional)
_register_endpoint = lambda url: None
if os.environ.get("FLEET_PROXY_ENABLED"):
    from fleet.proxy.whitelist import install_hooks, register_endpoint as _register_endpoint
    install_hooks()

# OAuth configuration
GOOG_PROJECT = os.environ.get("GOOG_PROJECT", "gemini-agents-area")
USE_OAUTH = os.environ.get("USE_OAUTH", "false").lower() in ("true", "1", "yes")

# Screen dimensions for coordinate denormalization (matches MCP browser)
SCREEN_WIDTH = 1366
SCREEN_HEIGHT = 768

# Gemini 3 tool definitions (0-1000 normalized coordinates)
GEMINI_3_TOOL_DEFINITIONS = [
    {
        "name": "click_at",
        "description": "Click at the specified screen coordinates. Coordinates are normalized 0-1000.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "X coordinate (0-1000, where 0 is left edge, 1000 is right edge)",
                },
                "y": {
                    "type": "integer",
                    "description": "Y coordinate (0-1000, where 0 is top edge, 1000 is bottom edge)",
                },
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "type_text",
        "description": "Type text at the current cursor position. Use click_at first to focus the input field.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to type",
                },
                "press_enter": {
                    "type": "boolean",
                    "description": "Whether to press Enter after typing (default: false)",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "key_press",
        "description": "Press a key or key combination (e.g., 'Enter', 'Tab', 'Meta+A', 'Ctrl+C', 'Backspace').",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "string",
                    "description": "Key or key combination to press",
                },
            },
            "required": ["keys"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll the page up or down.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "description": "Direction to scroll: 'up' or 'down'",
                    "enum": ["up", "down"],
                },
            },
            "required": ["direction"],
        },
    },
    {
        "name": "wait",
        "description": "Wait for a few seconds to allow page to load.",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "description": "Number of seconds to wait (1-10)",
                },
            },
            "required": ["seconds"],
        },
    },
]

# Key name normalization for xdotool/X11 keysym compatibility
_KEY_NAME_MAP_LOWER = {
    "backspace": "BackSpace",
    "arrowleft": "Left", "arrowright": "Right", "arrowup": "Up", "arrowdown": "Down",
    "left": "Left", "right": "Right", "up": "Up", "down": "Down",
    "esc": "Escape", "escape": "Escape",
    "del": "Delete", "delete": "Delete",
    "pgup": "Page_Up", "pageup": "Page_Up",
    "pgdown": "Page_Down", "pgdn": "Page_Down", "pagedown": "Page_Down",
    "enter": "Return", "return": "Return",
    "tab": "Tab", "space": "space",
    "meta": "super", "command": "super", "cmd": "super", "super": "super",
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "shift": "shift",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5", "f6": "F6",
    "f7": "F7", "f8": "F8", "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
    "home": "Home", "end": "End", "insert": "Insert",
}


def normalize_key_name(key: str) -> str:
    """Normalize key names to xdotool/X11 keysym format."""
    if not key:
        return key
    if "+" in key:
        parts = key.split("+")
        normalized_parts = [_KEY_NAME_MAP_LOWER.get(p.lower(), p) for p in parts]
        return "+".join(normalized_parts)
    return _KEY_NAME_MAP_LOWER.get(key.lower(), key)


def get_oauth_token() -> str:
    """Get OAuth token from gcloud."""
    ret = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True,
        check=True,
    )
    return ret.stdout.decode().strip()


def get_gemini_client() -> genai.Client:
    """Create Gemini client with appropriate auth."""
    api_key = os.environ.get("GEMINI_API_KEY")
    custom_endpoint = os.environ.get("FLEET_MODEL_ENDPOINT")

    _register_endpoint(custom_endpoint or "generativelanguage.googleapis.com")

    http_opts = None
    if USE_OAUTH or custom_endpoint:
        opts = {}
        if custom_endpoint:
            opts["base_url"] = custom_endpoint
            log_verbose(f"Using custom endpoint: {custom_endpoint}")
        if USE_OAUTH:
            opts["headers"] = {
                "Authorization": f"Bearer {get_oauth_token()}",
                "X-Goog-User-Project": GOOG_PROJECT,
            }
            opts["api_version"] = "v1alpha"
            log_verbose(f"Using OAuth (project: {GOOG_PROJECT})")
        http_opts = types.HttpOptions(**opts)

    return genai.Client(api_key=api_key, http_options=http_opts)


def convert_gemini_3_to_mcp(function_name: str, args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert Gemini 3 custom function calls to MCP computer tool format.

    Coordinates are normalized 0-1000, denormalized to screen dimensions.
    Returns a list of MCP actions since some functions expand to multiple steps.
    """
    def denormalize_x(x: int) -> int:
        return int(x / 1000 * SCREEN_WIDTH)

    def denormalize_y(y: int) -> int:
        return int(y / 1000 * SCREEN_HEIGHT)

    mcp_actions = []

    if function_name == "click_at":
        x = denormalize_x(args.get("x", 500))
        y = denormalize_y(args.get("y", 500))
        mcp_actions.append({"action": "left_click", "coordinate": [x, y]})

    elif function_name == "type_text":
        text = args.get("text", "")
        press_enter = args.get("press_enter", False)
        mcp_actions.append({"action": "type", "text": text})
        if press_enter:
            mcp_actions.append({"action": "key", "text": "Return"})

    elif function_name == "key_press":
        keys = args.get("keys", "Return")
        mcp_actions.append({"action": "key", "text": normalize_key_name(keys)})

    elif function_name == "scroll":
        direction = args.get("direction", "down")
        mcp_actions.append({
            "action": "scroll",
            "coordinate": [SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2],
            "scroll_direction": direction,
            "scroll_amount": 5,
        })

    elif function_name == "wait":
        seconds = min(args.get("seconds", 3), 10)
        mcp_actions.append({"action": "wait", "duration": seconds})

    else:
        # Unknown function, fallback to screenshot
        mcp_actions.append({"action": "screenshot"})

    return mcp_actions


class MCP:
    """MCP client using streamable-http transport."""

    def __init__(self, url: str, log_file: Optional[str] = None):
        self.url = url.rstrip("/") + "/mcp/"
        self._session: Optional[ClientSession] = None
        self._client = None
        self._log_file = log_file or os.environ.get("FLEET_SESSION_LOG")
        self._log_handle = None
        if self._log_file:
            from pathlib import Path
            Path(self._log_file).parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = open(self._log_file, "a")

    async def __aenter__(self):
        print(f"MCP: Connecting to {self.url}...")
        try:
            self._client = streamable_http_client(self.url)
            read, write, _ = await self._client.__aenter__()
            self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()
            print(f"MCP: Connected successfully")
        except Exception as e:
            print(f"MCP: Connection failed: {type(e).__name__}: {e}")
            raise
        
        # Fetch available tools from server
        try:
            result = await self._session.list_tools()
            self._tools = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema,
                }
                for tool in result.tools
            ]
            print(f"MCP: Loaded {len(self._tools)} tools")
        except Exception as e:
            print(f"MCP: Failed to list tools: {type(e).__name__}: {e}")
            raise
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.__aexit__(*args)
        if self._client:
            await self._client.__aexit__(*args)
        if self._log_handle:
            self._log_handle.close()

    def _log(self, entry: dict):
        """Log an entry to the traffic file."""
        if self._log_handle:
            from datetime import datetime
            entry["timestamp"] = datetime.now().isoformat()
            entry["url"] = self.url
            self._log_handle.write(json.dumps(entry) + "\n")
            self._log_handle.flush()

    async def call(self, name: str, args: Dict = None) -> Dict:
        """Call a tool and return the result."""
        start_time = time.time()
        result = await self._session.call_tool(name, args or {})
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Debug: log raw MCP result structure
        log_verbose(f"    MCP result.content ({len(result.content)} items):")
        for i, item in enumerate(result.content):
            log_verbose(f"      [{i}] type={type(item).__name__}, attrs={dir(item)[:10]}...")
            if hasattr(item, "type"):
                log_verbose(f"          .type = {repr(item.type)}")
            if hasattr(item, "data"):
                data_preview = str(item.data)[:50] if item.data else "None"
                log_verbose(f"          .data = {data_preview}...")
        
        # Helper to get attribute or dict key
        def _get(item, key, default=None):
            if isinstance(item, dict):
                return item.get(key, default)
            return getattr(item, key, default)

        content = []
        for item in result.content:
            item_type = _get(item, "type")
            if item_type == "image":
                content.append({
                    "type": "image",
                    "data": _get(item, "data", ""),
                    "mimeType": _get(item, "mimeType", "image/png"),
                })
            elif item_type == "text":
                content.append({"type": "text", "text": _get(item, "text", "")})

        self._log({
            "type": "mcp_call",
            "tool": name,
            "args": args or {},
            "duration_ms": duration_ms,
            "response_content_types": [c.get("type") for c in content],
            "is_error": result.isError if hasattr(result, "isError") else False,
        })
        return {"content": content, "isError": result.isError if hasattr(result, "isError") else False}


def get_gemini_3_tools() -> List[types.FunctionDeclaration]:
    """Return Gemini 3 custom tools as FunctionDeclarations."""
    return [
        types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=tool["parameters"],
        )
        for tool in GEMINI_3_TOOL_DEFINITIONS
    ]


def get_image_data(result: Dict) -> Optional[str]:
    """Extract base64 image from MCP result."""
    for content in result.get("content", []):
        if content.get("type") == "image":
            return content.get("data")
    return None


def extract_reasoning_from_candidate(candidate) -> Optional[str]:
    """Extract reasoning trace from Gemini candidate response."""
    reasoning_parts = []

    if not candidate or not candidate.content or not candidate.content.parts:
        return None

    has_function_calls = any(
        hasattr(p, "function_call") and p.function_call for p in candidate.content.parts
    )

    for part in candidate.content.parts:
        if hasattr(part, "thought") and part.thought:
            if isinstance(part.thought, str):
                reasoning_parts.append(part.thought)
            elif part.thought is True and hasattr(part, "text") and part.text:
                reasoning_parts.append(part.text)
        elif hasattr(part, "text") and part.text and has_function_calls:
            reasoning_parts.append(part.text)

    if not reasoning_parts:
        return None
    return "\n\n".join(reasoning_parts)


class GeminiAgent:
    """Gemini Computer Use Agent."""

    def __init__(self, mcp: MCP, model: str, session=None):
        self.mcp = mcp
        self.model = model.split("/")[-1] if "/" in model else model
        self.client = get_gemini_client()
        self.transcript: List[Dict] = []
        self.session = session
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5

    async def _take_screenshot(self) -> Optional[str]:
        """Take a screenshot and return base64 data."""
        try:
            result = await self.mcp.call("computer", {"action": "screenshot"})
            return get_image_data(result)
        except Exception as e:
            print(f"Screenshot failed: {e}")
            return None

    async def _execute_gemini_function(self, name: str, args: Dict) -> Dict:
        """Execute a Gemini function by converting to MCP actions."""
        mcp_actions = convert_gemini_3_to_mcp(name, args)
        log_verbose(f"  Converting {name} -> {len(mcp_actions)} MCP action(s)")

        last_result = None
        for i, action in enumerate(mcp_actions):
            log_verbose(f"    Action {i+1}: {action}")
            last_result = await self.mcp.call("computer", action)
            if last_result.get("isError"):
                return last_result

        # After executing actions, take a screenshot
        screenshot_result = await self.mcp.call("computer", {"action": "screenshot"})
        return screenshot_result

    async def run(self, prompt: str, max_steps: int) -> Dict[str, Any]:
        """Run the agent on a task."""
        start_time = time.time()

        system_prompt = """You are a helpful agent. Complete the task by interacting with the browser.

Use the available tools to click, type, scroll, and interact with the page.
Coordinates are normalized 0-1000 (0,0 is top-left, 1000,1000 is bottom-right).

When done, stop calling tools and provide your final response."""

        # Get Gemini 3 tools
        gemini_tools = get_gemini_3_tools()

        log_verbose("\n" + "="*60)
        log_verbose("SYSTEM PROMPT:")
        log_verbose("="*60)
        log_verbose(system_prompt)

        log_verbose(f"\nTOOLS ({len(gemini_tools)} total):")
        for tool in GEMINI_3_TOOL_DEFINITIONS:
            log_verbose(f"  {tool['name']}: {tool['description'][:80]}...")

        # Configure Gemini with thinking enabled
        config = types.GenerateContentConfig(
            max_output_tokens=65536,
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=gemini_tools)],
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        )

        # Set config on session for logging (if session exists)
        if self.session:
            self.session.config = config
        
        # Take initial screenshot
        print("Taking initial screenshot...")
        initial_screenshot = await self._take_screenshot()

        # Build initial user message with task + screenshot
        user_parts = [Part(text=f"Task: {prompt}")]
        if initial_screenshot:
            user_parts.append(Part(inline_data={
                "mime_type": "image/png",
                "data": initial_screenshot,
            }))
            print("✓ Initial screenshot captured")
        else:
            print("⚠ Could not capture initial screenshot")

        history: List[Content] = [Content(role="user", parts=user_parts)]
        self.transcript.append({"role": "user", "content": prompt})

        log_verbose("\n" + "="*60)
        log_verbose("USER PROMPT:")
        log_verbose("="*60)
        log_verbose(prompt)

        for step in range(1, max_steps + 1):
            print(f"\n{'='*50}")
            print(f"Step {step}/{max_steps}")
            
            # Log history size
            log_verbose(f"  History: {len(history)} messages")
            
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=history,
                    config=config,
                )
                self._consecutive_errors = 0
            except Exception as e:
                self._consecutive_errors += 1
                error_type = type(e).__name__
                print(f"API error ({error_type}): {e}")
                print(f"  Consecutive errors: {self._consecutive_errors}/{self._max_consecutive_errors}")

                if self._consecutive_errors >= self._max_consecutive_errors:
                    return self._result(False, f"Too many consecutive API errors: {error_type}: {e}", step, start_time)
                
                # Check for retryable errors
                if "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower():
                    print("  Rate limited, waiting 10s...")
                    await asyncio.sleep(10)
                    continue
                elif "503" in str(e) or "500" in str(e) or "overloaded" in str(e).lower():
                    print("  Server error, waiting 5s...")
                    await asyncio.sleep(5)
                    continue
                else:
                    return self._result(False, f"{error_type}: {e}", step, start_time)

            if not response.candidates:
                print("[WARN] No candidates, retrying...")
                log_verbose(f"  Response: {response}")
                continue

            candidate = response.candidates[0]
            if not candidate.content or not candidate.content.parts:
                print("[WARN] Empty response, retrying...")
                continue

            # Extract reasoning trace
            reasoning = extract_reasoning_from_candidate(candidate)
            if reasoning:
                preview = reasoning[:100] + "..." if len(reasoning) > 100 else reasoning
                print(f"🧠 Thinking: {preview}")

            # Log to Fleet session if available
            if self.session:
                try:
                    await self.session.log(history, response)
                    if step == 1 and self.session.session_id:
                        print(f"Session: https://fleetai.com/dashboard/sessions/{self.session.session_id}")
                except Exception as e:
                    print(f"  [WARN] Session log failed: {type(e).__name__}: {e}")
                    log_verbose(f"  [WARN] Session log failed: {e}")
            
            # Log all parts for debugging
            log_verbose(f"\n  Response parts ({len(candidate.content.parts)}):")
            for i, part in enumerate(candidate.content.parts):
                if part.text:
                    log_verbose(f"    [{i}] TEXT: {part.text[:300]}{'...' if len(part.text) > 300 else ''}")
                elif part.function_call:
                    fc = part.function_call
                    args_str = json.dumps(dict(fc.args) if fc.args else {})
                    log_verbose(f"    [{i}] FUNCTION_CALL: {fc.name}({args_str})")
                elif hasattr(part, 'thought') and part.thought:
                    log_verbose(f"    [{i}] THOUGHT: {part.thought[:300]}{'...' if len(part.thought) > 300 else ''}")
                else:
                    log_verbose(f"    [{i}] OTHER: {type(part).__name__}")
            
            # Extract function calls and text
            function_calls = [p.function_call for p in candidate.content.parts if p.function_call]
            text_parts = [p.text for p in candidate.content.parts if p.text and not getattr(p, "thought", False)]

            # Print model output
            if text_parts:
                for text in text_parts:
                    display = text[:200] + "..." if len(text) > 200 else text
                    print(f"Model: {display}")

            # Check for completion (no function calls)
            if text_parts and not function_calls:
                final_text = " ".join(text_parts)
                self.transcript.append({"role": "assistant", "content": final_text})

                if final_text.strip().upper().startswith("DONE:"):
                    answer = final_text.strip()[5:].strip()
                    print(f"\n✓ Agent completed: {answer[:100]}")
                    return self._result(True, None, step, start_time, answer)
                elif final_text.strip().upper().startswith("FAILED:"):
                    error = final_text.strip()[7:].strip()
                    print(f"\n✗ Agent failed: {error[:100]}")
                    return self._result(False, error, step, start_time)
                else:
                    print(f"\n✓ Agent finished with response")
                    return self._result(True, None, step, start_time, final_text)

            # Check for thinking-only response (no function calls, no text)
            if not function_calls and not text_parts:
                print("🧠 Thinking-only response, continuing...")
                # Add thinking to history so model has context
                history.append(candidate.content)
                continue

            if function_calls:
                # Add model's response to history
                history.append(candidate.content)

                log_verbose(f"\n  Executing {len(function_calls)} function call(s):")

                # Execute each function call
                response_parts = []
                for i, fc in enumerate(function_calls):
                    name = fc.name
                    args = dict(fc.args) if fc.args else {}
                    print(f"  Tool {i+1}/{len(function_calls)}: {name}({json.dumps(args)})")
                    self.transcript.append({"role": "tool_call", "name": name, "args": args})

                    try:
                        result = await self._execute_gemini_function(name, args)

                        if result.get("isError"):
                            self._consecutive_errors += 1
                            error_text = ""
                            for c in result.get("content", []):
                                if c.get("type") == "text":
                                    error_text = c.get("text", "")[:200]
                            print(f"    Tool error: {error_text}")

                            # Return error to model
                            response_parts.append(Part(
                                function_response={
                                    "name": name,
                                    "response": {"status": "error", "error": error_text},
                                }
                            ))
                        else:
                            self._consecutive_errors = 0
                            img_data = get_image_data(result)

                            if img_data:
                                # Function response with screenshot
                                response_parts.append(Part(
                                    function_response={
                                        "name": name,
                                        "response": {"status": "success"},
                                    }
                                ))
                                # Add screenshot as inline_data
                                response_parts.append(Part(
                                    inline_data={
                                        "mime_type": "image/png",
                                        "data": img_data,
                                    }
                                ))
                                log_verbose("    Response: screenshot captured")
                            else:
                                response_parts.append(Part(
                                    function_response={
                                        "name": name,
                                        "response": {"status": "success"},
                                    }
                                ))
                                log_verbose("    Response: no screenshot")

                    except Exception as e:
                        self._consecutive_errors += 1
                        error_type = type(e).__name__
                        print(f"  Tool exception ({error_type}): {e}")

                        if "connection" in str(e).lower() or "closed" in str(e).lower():
                            print("  MCP connection lost, failing task")
                            return self._result(False, f"MCP connection error: {e}", step, start_time)

                        response_parts.append(Part(
                            function_response={
                                "name": name,
                                "response": {"status": "error", "error": str(e)},
                            }
                        ))

                    # Small delay between tool calls
                    if i < len(function_calls) - 1:
                        await asyncio.sleep(0.1)

                # Add function responses to history as user role
                # (Gemini expects function_response in user messages)
                history.append(Content(role="user", parts=response_parts))
                log_verbose(f"  Added {len(response_parts)} response part(s) to history")

        # Max steps reached
        print(f"\n⚠ Max steps ({max_steps}) reached")
        return self._result(True, "Max steps reached", max_steps, start_time, "Max steps reached - task may be complete")

    def _result(self, completed: bool, error: Optional[str], steps: int, start_time: float, answer: str = None) -> Dict:
        """Build result dict."""
        return {
            "completed": completed,
            "error": error,
            "final_answer": answer,
            "steps_taken": steps,
            "execution_time_ms": int((time.time() - start_time) * 1000),
            "transcript": self.transcript,
        }


async def main():
    """Main entry point."""
    config = {
        "url": os.environ.get("FLEET_MCP_URL", "http://localhost:8765"),
        "prompt": os.environ.get("FLEET_TASK_PROMPT", ""),
        "task_key": os.environ.get("FLEET_TASK_KEY", ""),
        "job_id": os.environ.get("FLEET_JOB_ID"),
        "instance_id": os.environ.get("FLEET_INSTANCE_ID"),
        "model": os.environ.get("FLEET_MODEL", "gemini-3-pro-preview"),
        "max_steps": int(os.environ.get("FLEET_MAX_STEPS", "200")),
    }

    print("Gemini CUA Agent")
    print(f"  Model: {config['model']}")
    print(f"  MCP: {config['url']}")
    print(f"  Verbose: {VERBOSE}")
    print(f"  Task: {config['prompt'][:80]}...")

    if not os.environ.get("GEMINI_API_KEY"):
        result = {"task_key": config["task_key"], "completed": False, "error": "No GEMINI_API_KEY"}
        print(json.dumps(result))
        return result

    try:
        # Create Fleet session for live logging
        session = None
        if os.environ.get("FLEET_API_KEY"):
            session = fleet.session_async(
                job_id=config["job_id"],
                model=config["model"],
                task_key=config["task_key"],
                instance_id=config["instance_id"],
            )

        async with MCP(config["url"]) as mcp:
            agent = GeminiAgent(mcp, config["model"], session=session)
            result = await agent.run(config["prompt"], config["max_steps"])
            result["task_key"] = config["task_key"]
            if session and session.session_id:
                result["session_id"] = session.session_id

            print(json.dumps(result))
            return result
    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {e}"
        print(f"Agent exception: {error_msg}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        result = {"task_key": config["task_key"], "completed": False, "error": error_msg}
        print(json.dumps(result))
        return result


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result.get("completed") else 1)
