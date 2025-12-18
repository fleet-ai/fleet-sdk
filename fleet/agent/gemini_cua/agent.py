#!/usr/bin/env python3
"""
Gemini CUA Agent

Env vars:
    GEMINI_API_KEY: API key
    FLEET_MCP_URL: CUA server URL (http://localhost:PORT)
    FLEET_TASK_PROMPT: Task prompt
    FLEET_TASK_KEY: Task key
    FLEET_MODEL: Model (default: gemini-2.5-pro)
    FLEET_MAX_STEPS: Max steps (default: 50)
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
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from google import genai
from google.genai import types
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
    
    # Register endpoint for proxy whitelist
    _register_endpoint(custom_endpoint or "generativelanguage.googleapis.com")
    
    # Build http_options
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



class MCP:
    """MCP client using streamable-http transport."""
    
    def __init__(self, url: str, log_file: Optional[str] = None):
        # Ensure URL ends with /mcp/ for streamable-http
        self.url = url.rstrip("/") + "/mcp/"
        self._session: Optional[ClientSession] = None
        self._client = None
        self._tools: List[Dict] = []
        self._log_file = log_file or os.environ.get("FLEET_SESSION_LOG")
        self._log_handle = None
        if self._log_file:
            from pathlib import Path
            Path(self._log_file).parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = open(self._log_file, "a")
    
    async def __aenter__(self):
        # Connect using streamable-http transport
        self._client = streamable_http_client(self.url)
        read, write, _ = await self._client.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        
        # Fetch available tools from server
        result = await self._session.list_tools()
        self._tools = [
            {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema,
            }
            for tool in result.tools
        ]
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
            import json
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
        
        # Convert MCP result to dict format expected by agent
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
        
        # Log the call (just types, not data)
        self._log({
            "type": "mcp_call",
            "tool": name,
            "args": args or {},
            "duration_ms": duration_ms,
            "response_content_types": [c.get("type") for c in content],
            "is_error": result.isError if hasattr(result, "isError") else False,
        })
        return {"content": content, "isError": result.isError if hasattr(result, "isError") else False}
    
    def get_tools(self) -> List[Dict]:
        """Return the list of tools from the server."""
        return self._tools


def mcp_tools_to_gemini(mcp_tools: List[Dict]) -> List[types.FunctionDeclaration]:
    """Convert MCP tool definitions to Gemini FunctionDeclarations."""
    declarations = []
    for tool in mcp_tools:
        declarations.append(types.FunctionDeclaration(
            name=tool["name"],
            description=tool.get("description", ""),
            parameters=tool.get("inputSchema", {"type": "object", "properties": {}}),
        ))
    return declarations


def get_image_data(result: Dict) -> Optional[str]:
    """Extract base64 image from MCP result."""
    for content in result.get("content", []):
        if content.get("type") == "image":
            return content.get("data")
    return None


class GeminiAgent:
    """Gemini Computer Use Agent."""
    
    def __init__(self, mcp: MCP, model: str, session=None):
        self.mcp = mcp
        # Strip provider prefix if present
        self.model = model.split("/")[-1] if "/" in model else model
        self.client = get_gemini_client()
        self.transcript: List[Dict] = []
        self.session = session  # Fleet session for live logging
    
    async def _execute_tool(self, name: str, args: Dict) -> Dict:
        return await self.mcp.call(name, args)
    
    async def run(self, prompt: str, max_steps: int) -> Dict[str, Any]:
        """Run the agent on a task."""
        start_time = time.time()
        
        system_prompt = f"""You control a browser via tools.

STRICT RULES:
- Text output with no tool calls means task complete. Only output text when fully done.
- When finished: output only "DONE: [what you did]"
"""
        
        # Get tools from MCP server and convert to Gemini format
        mcp_tools = self.mcp.get_tools()
        gemini_tools = mcp_tools_to_gemini(mcp_tools)
        
        # Log system prompt and tools
        log_verbose("\n" + "="*60)
        log_verbose("SYSTEM PROMPT:")
        log_verbose("="*60)
        log_verbose(system_prompt)
        
        log_verbose("\n" + "="*60)
        log_verbose(f"TOOLS ({len(mcp_tools)} total):")
        log_verbose("="*60)
        for tool in mcp_tools:
            log_verbose(f"\n  {tool['name']}:")
            log_verbose(f"    Description: {tool.get('description', '')[:200]}")
            schema = tool.get('inputSchema', {})
            props = schema.get('properties', {})
            if props:
                log_verbose(f"    Parameters:")
                for pname, pinfo in props.items():
                    ptype = pinfo.get('type', 'any')
                    pdesc = pinfo.get('description', '')[:80]
                    log_verbose(f"      - {pname} ({ptype}): {pdesc}")
        
        config = types.GenerateContentConfig(
            max_output_tokens=4096,
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=gemini_tools)],
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        )
        
        # Set config on session for logging (if session exists)
        if self.session:
            self.session.config = config
        
        history: List[types.Content] = []
        
        user_prompt = f"""###User instruction: {prompt}"""
        history.append(types.Content(role="user", parts=[types.Part(text=user_prompt)]))
        self.transcript.append({"role": "user", "content": prompt})
        
        log_verbose("\n" + "="*60)
        log_verbose("USER PROMPT:")
        log_verbose("="*60)
        log_verbose(user_prompt)
        
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
            except Exception as e:
                print(f"API error: {e}")
                return self._result(False, str(e), step, start_time)
            
            if not response.candidates:
                print("[WARN] No candidates, retrying...")
                log_verbose(f"  Response: {response}")
                continue
            
            candidate = response.candidates[0]
            if not candidate.content or not candidate.content.parts:
                print("[WARN] Empty response, retrying...")
                log_verbose(f"  Candidate: {candidate}")
                continue
            
            # Log to Fleet session (live)
            if self.session:
                try:
                    await self.session.log(history, response)
                    if step == 1 and self.session.session_id:
                        print(f"Session: https://fleetai.com/dashboard/sessions/{self.session.session_id}")
                except Exception as e:
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
            text_parts = [p.text for p in candidate.content.parts if p.text]
            
            # Print model output
            if text_parts:
                for text in text_parts:
                    display = text[:200] + "..." if len(text) > 200 else text
                    print(f"Model: {display}")
            
            # Check for completion
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
                    # Text without DONE/FAILED - treat as completion
                    print(f"\n✓ Agent finished with response")
                    return self._result(True, None, step, start_time, final_text)
            
            if function_calls:
                # Add model's response to history
                history.append(candidate.content)
                
                log_verbose(f"\n  Executing {len(function_calls)} function call(s):")
                
                # Execute each function call in series with delays
                response_parts = []
                for i, fc in enumerate(function_calls):
                    name = fc.name
                    args = dict(fc.args) if fc.args else {}
                    print(f"  Tool {i+1}/{len(function_calls)}: {name}({json.dumps(args)})")
                    self.transcript.append({"role": "tool_call", "name": name, "args": args})
                    
                    try:
                        result = await self._execute_tool(name, args)
                        log_verbose(f"    Result: isError={result.get('isError', False)}, content_types={[c.get('type') for c in result.get('content', [])]}")
                    except Exception as e:
                        print(f"  Error: {e}")
                        log_verbose(f"    Exception: {type(e).__name__}: {e}")
                        result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
                    
                    # Build function response with image embedded (per reference format)
                    img_data = get_image_data(result)  # Base64 string
                    
                    if img_data:
                        log_verbose(f"    Response: image (base64 len={len(img_data)})")
                        # Function response with image in parts
                        fr_part = types.Part(
                            function_response=types.FunctionResponse(
                                name=name,
                                response={"status": "success" if not result.get("isError") else "error"},
                                parts=[
                                    types.FunctionResponsePart(
                                        inline_data=types.FunctionResponseBlob(
                                            mime_type="image/png",
                                            data=img_data,  # Base64 string
                                        )
                                    )
                                ],
                            )
                        )
                    else:
                        log_verbose(f"    Response: no image (status only)")
                        # Function response without image
                        fr_part = types.Part(
                            function_response=types.FunctionResponse(
                                name=name,
                                response={"status": "error" if result.get("isError") else "success"},
                            )
                        )
                    response_parts.append(fr_part)
                    
                    # Small delay between tool calls to let page settle
                    if i < len(function_calls) - 1:
                        await asyncio.sleep(0.1)
                
                # Add function responses with role="model" (per reference)
                history.append(types.Content(role="model", parts=response_parts))
                log_verbose(f"  Added {len(response_parts)} function response(s) to history")
        
        return self._result(False, "Max steps reached", max_steps, start_time)
    
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
        "model": os.environ.get("FLEET_MODEL", "gemini-2.5-pro"),
        "max_steps": int(os.environ.get("FLEET_MAX_STEPS", "100")),
    }
    
    print(f"Gemini CUA Agent")
    print(f"  Model: {config['model']}")
    print(f"  MCP: {config['url']}")
    print(f"  Verbose: {VERBOSE}")
    print(f"  Task: {config['prompt'][:80]}...")
    
    if not os.environ.get("GEMINI_API_KEY"):
        result = {"task_key": config["task_key"], "completed": False, "error": "No GEMINI_API_KEY"}
        print(json.dumps(result))
        return result
    
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
        # Include session_id in result so orchestrator can complete it after verification
        if session and session.session_id:
            result["session_id"] = session.session_id
        
        print(json.dumps(result))
        return result


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result.get("completed") else 1)
