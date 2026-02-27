"""Fleet Judge — portable LLM-based evaluation infrastructure.

``Judge`` is an abstract base class that provides:
- Anthropic LLM calling (single-shot and agentic MCP tool-use loop)
- Anthropic Files API support (PDF/CSV upload via beta header)
- JSON extraction from LLM responses (fenced + bare + trailing-comma repair)
- Response normalization (score clamping, criterion aggregation)
- Model name resolution (short names → full API identifiers)
- Base64 image resolution
- MCP (Model Context Protocol) client for tool-use

Subclasses MUST implement ``build_prompt()`` to define the evaluation
strategy (rubric interpretation, prompt construction, etc.).

Subclasses MAY override:
- ``parse_response()`` — custom output parsing (default: JSON extraction)
- ``build_response()`` — custom response normalization

This module has **zero** orchestrator / infrastructure dependencies.
It ships as part of ``fleet-python[judge]``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from abc import ABC, abstractmethod
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)

from .models import (
    Base64ImageSource,
    CriterionResult,
    ImageSource,
    JudgeGradeRequest,
    JudgeGradeResponse,
    S3ImageSource,
    StructuredRubric,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress callback protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ProgressCallback(Protocol):
    """Callable that receives progress messages during evaluation."""

    def __call__(self, message: str) -> None: ...


def _noop(_msg: str) -> None:
    """Default no-op progress callback."""


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------

ANTHROPIC_MODEL_MAPPING: Dict[str, str] = {
    "claude-opus-4.6": "claude-opus-4-6",
    "claude-sonnet-4.5": "claude-sonnet-4-5-20250929",
    "claude-sonnet-4": "claude-sonnet-4-20250514",
    "claude-haiku-3.5": "claude-3-5-haiku-20241022",
    "claude-sonnet-3.5": "claude-3-5-sonnet-20241022",
    # Full IDs pass through
    "claude-opus-4-6": "claude-opus-4-6",
    "claude-sonnet-4-5-20250929": "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-20250514": "claude-sonnet-4-20250514",
    "claude-3-5-haiku-20241022": "claude-3-5-haiku-20241022",
    "claude-3-5-sonnet-20241022": "claude-3-5-sonnet-20241022",
}

DEFAULT_MODEL = "claude-opus-4-6"


def resolve_model(name: str) -> str:
    """Map short model names to full Anthropic identifiers.

    Unknown names pass through unchanged so callers can use custom model IDs.
    """
    return ANTHROPIC_MODEL_MAPPING.get(name, name)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def extract_json_from_response(text: str) -> Dict[str, Any]:
    """Extract JSON from an LLM response.

    Tries (in order):
    1. Fenced ``json`` code blocks
    2. Bare ``{...}`` objects (last match wins — reasoning may contain braces)
    3. Trailing-comma repair and retry

    Raises ``ValueError`` if no valid JSON can be extracted.
    """
    # 1. Fenced JSON blocks
    for match in _FENCED_JSON_RE.finditer(text):
        try:
            return json.loads(match.group(1))  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            continue

    # 2. Bare JSON objects (take last match — earlier ones are often reasoning)
    bare_matches = list(_BARE_JSON_RE.finditer(text))
    for match in reversed(bare_matches):
        candidate = match.group(0)
        try:
            return json.loads(candidate)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            # 3. Trailing-comma repair
            repaired = re.sub(r",\s*}", "}", candidate)
            repaired = re.sub(r",\s*]", "]", repaired)
            try:
                return json.loads(repaired)  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Could not extract JSON from response: {text[:200]}...")


# ---------------------------------------------------------------------------
# Base64 image resolution (portable — no S3)
# ---------------------------------------------------------------------------


def resolve_base64_images(
    images: List[ImageSource],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Resolve a list of image sources to Anthropic content blocks.

    Only handles ``Base64ImageSource`` natively.  ``S3ImageSource`` and
    ``CollectImageSource`` are skipped with an error — callers (e.g. the
    orchestrator) must resolve those *before* calling ``Judge.evaluate()``.

    Returns ``(content_blocks, errors)``.
    """
    blocks: List[Dict[str, Any]] = []
    errors: List[str] = []

    for img in images:
        if isinstance(img, Base64ImageSource):
            if img.label:
                blocks.append({"type": "text", "text": f"[Image: {img.label}]"})
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.media_type,
                        "data": img.data,
                    },
                }
            )
        elif isinstance(img, S3ImageSource):
            errors.append(
                f"S3 image source not supported in portable Judge — "
                f"resolve before calling evaluate(): {img.url}"
            )
        else:
            # CollectImageSource — must be resolved by caller
            errors.append(
                f"Collect image source not supported in portable Judge — "
                f"resolve before calling evaluate(): {img!r}"
            )

    return blocks, errors


# ---------------------------------------------------------------------------
# Response building
# ---------------------------------------------------------------------------


def build_grade_response(
    *,
    parsed: Dict[str, Any],
    raw_text: str,
    model_used: str,
    request: JudgeGradeRequest,
    errors: List[str],
    elapsed_ms: float,
    agent_steps: Optional[List[Dict[str, Any]]] = None,
) -> JudgeGradeResponse:
    """Construct a ``JudgeGradeResponse`` from parsed LLM output.

    Handles both string and structured rubric shapes.  Clamps
    ``normalized_score`` to [0, 1].
    """
    total_score = float(parsed.get("total_score", parsed.get("score", 0)))
    max_score = float(parsed.get("max_score", 1))
    feedback = parsed.get("feedback", "")

    criteria: Optional[List[CriterionResult]] = None
    if isinstance(request.rubric, StructuredRubric) and "criteria" in parsed:
        criteria = [
            CriterionResult(
                name=c.get("name", ""),
                score=float(c.get("score", 0)),
                max_score=float(c.get("max_score", 0)),
                reasoning=c.get("reasoning", ""),
            )
            for c in parsed["criteria"]
        ]

    normalized = min(total_score / max_score, 1.0) if max_score > 0 else 0.0

    accumulators: Dict[str, Any] = {"elapsed_ms": elapsed_ms}
    if errors:
        accumulators["errors"] = errors
    if agent_steps:
        accumulators["agent_steps"] = agent_steps

    return JudgeGradeResponse(
        execution_id=str(uuid.uuid4()),
        normalized_score=normalized,
        total_score=total_score,
        max_score=max_score,
        criteria=criteria,
        feedback=feedback,
        model_used=model_used,
        provider_used="anthropic",
        accumulators=accumulators,
        raw_judge_response=raw_text,
    )


# ---------------------------------------------------------------------------
# MCP client (streamable-HTTP, JSON-RPC 2.0)
# ---------------------------------------------------------------------------


class McpClient:
    """Minimal MCP client for tool-use during agentic evaluation.

    Implements just enough of the streamable-HTTP transport to:
    1. ``initialize`` — open a session
    2. ``tools/list`` — discover available tools
    3. ``tools/call`` — invoke a tool

    All I/O uses ``httpx`` (already a fleet-python dependency).
    """

    def __init__(self, url: str, *, timeout: float = 30.0) -> None:
        self.url = url
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self._req_counter = 0

    def _next_req_id(self) -> int:
        self._req_counter += 1
        return self._req_counter

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _make_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": self._next_req_id(),
            "method": method,
            **({"params": params} if params else {}),
        }

    async def _post(self, body: Dict[str, Any]) -> Dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.url, json=body, headers=self._headers())
            resp.raise_for_status()

            # Capture session ID from response header
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session_id = sid

            # Handle SSE responses
            ct = resp.headers.get("content-type", "")
            if "text/event-stream" in ct:
                return self._parse_sse(resp.text)

            return resp.json()  # type: ignore[no-any-return]

    @staticmethod
    def _parse_sse(text: str) -> Dict[str, Any]:
        """Extract the last ``data:`` line from an SSE stream."""
        last_data: Optional[str] = None
        for line in text.splitlines():
            if line.startswith("data:"):
                last_data = line[5:].strip()
        if last_data:
            return json.loads(last_data)  # type: ignore[no-any-return]
        raise ValueError("No data lines in SSE response")

    async def initialize(self) -> Dict[str, Any]:
        body = self._make_request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "fleet-judge", "version": "1.0.0"},
        })
        return await self._post(body)

    async def list_tools(self) -> List[Dict[str, Any]]:
        body = self._make_request("tools/list")
        resp = await self._post(body)
        return resp.get("result", {}).get("tools", [])  # type: ignore[no-any-return]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        body = self._make_request("tools/call", {"name": name, "arguments": arguments})
        resp = await self._post(body)
        return resp.get("result")


# ---------------------------------------------------------------------------
# Judge ABC
# ---------------------------------------------------------------------------


class Judge(ABC):
    """Abstract base class for LLM-based evaluation.

    Provides infrastructure for:
    - Calling the Anthropic API (single-shot and agentic MCP loop)
    - Uploading files via the Anthropic Files API
    - Parsing / normalizing responses

    Subclasses MUST implement ``build_prompt()`` to define the evaluation
    strategy.  Subclasses MAY override ``parse_response()`` and
    ``build_response()`` for custom behavior.

    Parameters
    ----------
    api_key : str, optional
        Anthropic API key.  Falls back to ``ANTHROPIC_API_KEY`` env var.
    model : str, optional
        Model name (short or full).  Default: ``claude-opus-4-6``.
    on_progress : callable, optional
        Called with progress messages during evaluation.
    max_turns : int, optional
        Maximum agentic tool-use turns.  Default: 10.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        on_progress: Optional[Callable[[str], None]] = None,
        max_turns: int = 10,
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = resolve_model(model)
        self.on_progress: Callable[[str], None] = on_progress or _noop
        self.max_turns = max_turns

    # ------------------------------------------------------------------
    # Abstract / overridable methods
    # ------------------------------------------------------------------

    @abstractmethod
    def build_prompt(
        self,
        request: JudgeGradeRequest,
        image_blocks: List[Dict[str, Any]],
        file_blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Build the (system, user_content_blocks) for the LLM call.

        Subclasses implement all rubric / evaluation-strategy logic here.

        Parameters
        ----------
        request : JudgeGradeRequest
            The grading request (submission, rubric, context, etc.).
        image_blocks : list
            Pre-resolved image content blocks (Anthropic format).
        file_blocks : list, optional
            Pre-resolved file content blocks.

        Returns
        -------
        tuple[str, list[dict]]
            ``(system_prompt, user_content_blocks)``
        """
        ...

    def parse_response(self, raw_text: str) -> Dict[str, Any]:
        """Parse LLM output into a structured dict.

        Default implementation extracts JSON.  Override for custom parsing.
        """
        return extract_json_from_response(raw_text)

    def build_response(
        self,
        *,
        parsed: Dict[str, Any],
        raw_text: str,
        model_used: str,
        request: JudgeGradeRequest,
        errors: List[str],
        elapsed_ms: float,
        agent_steps: Optional[List[Dict[str, Any]]] = None,
    ) -> JudgeGradeResponse:
        """Build the final response from parsed output.

        Default implementation delegates to ``build_grade_response()``.
        Override for custom normalization.
        """
        return build_grade_response(
            parsed=parsed,
            raw_text=raw_text,
            model_used=model_used,
            request=request,
            errors=errors,
            elapsed_ms=elapsed_ms,
            agent_steps=agent_steps,
        )

    # ------------------------------------------------------------------
    # Evaluation pipeline
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        request: JudgeGradeRequest,
        *,
        image_blocks: Optional[List[Dict[str, Any]]] = None,
        file_blocks: Optional[List[Dict[str, Any]]] = None,
        file_ids: Optional[List[str]] = None,
        mcp_url: Optional[str] = None,
        resolve_errors: Optional[List[str]] = None,
    ) -> JudgeGradeResponse:
        """Run the full evaluation pipeline.

        Steps:
        1. Resolve images (base64 only — S3/collect must be pre-resolved)
        2. ``build_prompt()`` → subclass constructs system + user blocks
        3. Call LLM (single-shot or agentic MCP loop)
        4. ``parse_response()`` → extract structured data
        5. ``build_response()`` → normalize into ``JudgeGradeResponse``

        Parameters
        ----------
        request : JudgeGradeRequest
            The grading request.
        image_blocks : list, optional
            Pre-resolved image blocks.  If ``None``, resolves from
            ``request.images`` (base64 only).
        file_blocks : list, optional
            Pre-resolved file content blocks.
        file_ids : list, optional
            Anthropic Files API file IDs (already uploaded).
        mcp_url : str, optional
            MCP server URL for agentic evaluation.
        resolve_errors : list, optional
            Errors from upstream resolution (S3, collect, etc.).
        """
        t0 = time.monotonic()
        errors: List[str] = list(resolve_errors or [])

        # Model override from request
        model = resolve_model(request.model) if request.model else self.model

        # Resolve images if not pre-resolved
        if image_blocks is None:
            image_blocks = []
            if request.images:
                img_blocks, img_errors = resolve_base64_images(request.images)
                image_blocks = img_blocks
                errors.extend(img_errors)

        # Build prompt via subclass
        self.on_progress("Building evaluation prompt...")
        system_prompt, user_blocks = self.build_prompt(
            request, image_blocks, file_blocks
        )

        # Call LLM
        if request.agentic and mcp_url:
            self.on_progress("Starting agentic evaluation loop...")
            raw_text, agent_steps = await self._run_agentic_loop(
                system_prompt=system_prompt,
                user_blocks=user_blocks,
                model=model,
                mcp_url=mcp_url,
                file_ids=file_ids,
            )
        else:
            self.on_progress("Calling LLM for evaluation...")
            raw_text = await self._call_llm(
                system_prompt=system_prompt,
                user_blocks=user_blocks,
                model=model,
                file_ids=file_ids,
            )
            agent_steps = None

        # Parse
        self.on_progress("Parsing response...")
        try:
            parsed = self.parse_response(raw_text)
        except ValueError as exc:
            logger.warning("JSON extraction failed: %s", exc)
            errors.append(f"JSON extraction failed: {exc}")
            parsed = {"score": 0, "max_score": 1, "feedback": raw_text}

        # Build response
        elapsed_ms = (time.monotonic() - t0) * 1000
        return self.build_response(
            parsed=parsed,
            raw_text=raw_text,
            model_used=model,
            request=request,
            errors=errors,
            elapsed_ms=elapsed_ms,
            agent_steps=agent_steps,
        )

    # ------------------------------------------------------------------
    # LLM calling
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        *,
        system_prompt: str,
        user_blocks: List[Dict[str, Any]],
        model: str,
        file_ids: Optional[List[str]] = None,
    ) -> str:
        """Single-shot Anthropic API call."""
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "anthropic package required for Judge. "
                "Install with: pip install fleet-python[judge]"
            ) from exc

        betas: List[str] = []
        if file_ids:
            betas.append("files-api-2025-04-14")

        # Prepend file references to user blocks
        content = list(user_blocks)
        for fid in file_ids or []:
            content.insert(0, {
                "type": "document",
                "source": {"type": "file", "file_id": fid},
            })

        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        try:
            kwargs: Dict[str, Any] = {
                "model": model,
                "max_tokens": 16384,
                "system": system_prompt,
                "messages": [{"role": "user", "content": content}],
            }
            if betas:
                kwargs["betas"] = betas

            response = await client.messages.create(**kwargs)

            # Extract text from response
            text_parts = []
            for block in response.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
            return "\n".join(text_parts)
        finally:
            await client.close()

    async def _run_agentic_loop(
        self,
        *,
        system_prompt: str,
        user_blocks: List[Dict[str, Any]],
        model: str,
        mcp_url: str,
        file_ids: Optional[List[str]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Agentic MCP tool-use loop.

        1. Initialize MCP session and list tools
        2. Call LLM with tools
        3. If LLM requests tool use, call MCP and loop
        4. Repeat until LLM stops requesting tools or max_turns

        Returns ``(final_text, agent_steps)``.
        """
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "anthropic package required for Judge. "
                "Install with: pip install fleet-python[judge]"
            ) from exc

        betas: List[str] = []
        if file_ids:
            betas.append("files-api-2025-04-14")

        # Initialize MCP
        mcp = McpClient(mcp_url)
        await mcp.initialize()
        mcp_tools = await mcp.list_tools()

        # Convert MCP tools to Anthropic tool format
        anthropic_tools = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("inputSchema", {"type": "object", "properties": {}}),
            }
            for t in mcp_tools
        ]

        # Build initial messages
        content = list(user_blocks)
        for fid in file_ids or []:
            content.insert(0, {
                "type": "document",
                "source": {"type": "file", "file_id": fid},
            })

        messages: List[Dict[str, Any]] = [{"role": "user", "content": content}]
        agent_steps: List[Dict[str, Any]] = []

        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        try:
            for turn in range(self.max_turns):
                self.on_progress(f"Agentic turn {turn + 1}/{self.max_turns}...")

                kwargs: Dict[str, Any] = {
                    "model": model,
                    "max_tokens": 16384,
                    "system": system_prompt,
                    "messages": messages,
                    "tools": anthropic_tools,
                }
                if betas:
                    kwargs["betas"] = betas

                response = await client.messages.create(**kwargs)

                # Process response blocks
                assistant_content: List[Dict[str, Any]] = []
                tool_uses: List[Dict[str, Any]] = []
                final_text_parts: List[str] = []

                for block in response.content:
                    if hasattr(block, "text"):
                        final_text_parts.append(block.text)
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        tool_uses.append({
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })

                messages.append({"role": "assistant", "content": assistant_content})

                # If no tool calls, we're done
                if not tool_uses:
                    return "\n".join(final_text_parts), agent_steps

                # Execute tool calls via MCP
                tool_results: List[Dict[str, Any]] = []
                for tool_use in tool_uses:
                    self.on_progress(f"Calling tool: {tool_use['name']}...")
                    try:
                        result = await mcp.call_tool(
                            tool_use["name"], tool_use["input"]
                        )
                        result_text = json.dumps(result) if not isinstance(result, str) else result
                        is_error = False
                    except Exception as exc:
                        result_text = f"Tool error: {exc}"
                        is_error = True

                    agent_steps.append({
                        "turn": turn + 1,
                        "tool": tool_use["name"],
                        "input": tool_use["input"],
                        "output": result_text[:2000],
                        "is_error": is_error,
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use["id"],
                        "content": result_text,
                        **({"is_error": True} if is_error else {}),
                    })

                messages.append({"role": "user", "content": tool_results})

            # Max turns reached — extract whatever text we have
            self.on_progress("Max turns reached, extracting final response...")
            all_text = []
            for msg in messages:
                if msg["role"] == "assistant":
                    for block in msg.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            all_text.append(block["text"])
            return "\n".join(all_text), agent_steps
        finally:
            await client.close()
