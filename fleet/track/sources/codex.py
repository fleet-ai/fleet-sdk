"""CodexSource — `~/.codex/{sessions,archived_sessions}/**/*.jsonl`.

Format notes (cataloged from real session files):

  Each row: {type, timestamp, payload}.

  Top-level types:
    - `session_meta`   — start of file (cwd, cli_version, etc.)
    - `turn_context`   — per-turn config (cwd, model, sandbox, system prompt)
    - `response_item`  — wire-level OpenAI Response API events
    - `event_msg`      — UX-level streamed events (overlap with response_item)

  response_item.payload.type values:
    - `message`              — role + content blocks
    - `function_call`        — tool call (name, arguments JSON, call_id)
    - `function_call_output` — tool result (call_id, output)
    - `reasoning`            — encrypted reasoning blob
    - `custom_tool_call`(_output) — user-defined tools
    - `web_search_call`(_end)     — web search

  event_msg.payload.type values:
    - `user_message`         — input text + images
    - `agent_message`        — visible assistant text (with phase)
    - `agent_reasoning`      — visible reasoning text
    - `task_started`/_complete/_aborted  — turn lifecycle
    - `token_count`          — usage + rate limits
    - `exec_command_end`     — shell tool result with exit_code, duration
    - `web_search_end`, `patch_apply_end`, `thread_name_updated`, `error`

  Note that response_item and event_msg often duplicate the same
  conceptual event (e.g. response_item.message vs event_msg.agent_message).
  We emit BOTH on parse — round-trip integrity requires it. Cross-format
  conversion to claude prefers the response_item layer.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from ..unified import (
    AssistantMessage,
    AssistantReasoning,
    Attachment,
    Event,
    FileEdit,
    Lifecycle,
    Operator,
    OpaqueEvent,
    SessionStart,
    TokenUsage,
    ToolCall,
    ToolResult,
    TurnEnd,
    TurnStart,
    UserMessage,
)
from .base import Source, _walk_glob, has_substantive_raw

log = logging.getLogger("fleet.track.sources.codex")


class CodexSource(Source):
    name = "codex"

    @property
    def root(self) -> Path:
        return self._home / ".codex"

    def iter_files(self) -> Iterator[Path]:
        sessions = self._home / ".codex" / "sessions"
        archived = self._home / ".codex" / "archived_sessions"
        yield from _walk_glob(sessions, "**/*.jsonl", self.exclude_patterns)
        yield from _walk_glob(archived, "**/*.jsonl", self.exclude_patterns)

    def is_present(self) -> bool:
        sessions = self._home / ".codex" / "sessions"
        archived = self._home / ".codex" / "archived_sessions"
        return sessions.is_dir() or archived.is_dir()

    def read_for_upload(self, path: Path) -> bytes | None:
        try:
            data = path.read_bytes()
        except OSError:
            return None

        if data and not data.endswith(b"\n"):
            last_nl = data.rfind(b"\n")
            if last_nl > 0:
                data = data[: last_nl + 1]
        return data

    # ------------------------------------------------------------------ #
    # Parse                                                                #
    # ------------------------------------------------------------------ #

    def parse(self, path: Path) -> Iterable[Event]:
        # Per-file state: codex's `model`, `approval_policy`, and
        # `sandbox_policy` are set in each `turn_context` row but apply
        # to subsequent rows until a new turn_context overrides them.
        # Tracking them lets us populate AssistantMessage.model and
        # emit Operator events when approval/sandbox change mid-session.
        state: dict[str, Any] = {
            "model": None,
            "approval_policy": None,
            "sandbox_policy": None,
            "provider": None,  # set from session_meta.model_provider
        }
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        doc = json.loads(line)
                    except json.JSONDecodeError as e:
                        log.debug("codex.parse: skip malformed line %d in %s: %s", line_no, path, e)
                        continue
                    if not isinstance(doc, dict):
                        continue
                    yield from _parse_row(doc, line_no=line_no, state=state)
        except OSError as e:
            log.warning("codex.parse: cannot read %s: %s", path, e)
            return

    # ------------------------------------------------------------------ #
    # Serialize                                                            #
    # ------------------------------------------------------------------ #

    def serialize(self, events: Iterable[Event]) -> bytes:
        """Convert unified events to codex JSONL bytes.

        Same-source: emit raw verbatim (deduped per row).
        Cross-source: synthesize codex-shaped rows. Lossy.
        """
        out_lines: list[str] = []
        seen: set[str] = set()
        for ev in events:
            line = _serialize_event_for_codex(ev, seen)
            if line is not None:
                out_lines.append(line)
        return ("\n".join(out_lines) + ("\n" if out_lines else "")).encode("utf-8")


# ------------------------------------------------------------------ #
# Per-row dispatch                                                     #
# ------------------------------------------------------------------ #


def _parse_row(doc: dict, line_no: int = 0, state: Optional[dict] = None) -> Iterator[Event]:
    rtype = doc.get("type")
    timestamp = doc.get("timestamp")
    payload = doc.get("payload") or {}
    common: dict[str, Any] = {
        "source": "codex",
        "timestamp": timestamp,
        "raw": doc,
    }
    line_id = f"L{line_no}" if line_no else None
    if state is None:
        state = {"model": None, "approval_policy": None,
                 "sandbox_policy": None, "provider": None}

    if rtype == "session_meta":
        # Pull the provider out of the meta so subsequent token_count
        # events can be tagged with it.
        state["provider"] = payload.get("model_provider") or state["provider"]
        yield SessionStart(
            id=line_id,
            cwd=payload.get("cwd"),
            agent_version=payload.get("cli_version"),
            user_instructions=_extract_text(payload.get("base_instructions")),
            **common,
        )
        return

    if rtype == "turn_context":
        # Update tracked state. Then emit TurnStart, plus an Operator
        # event if approval_policy or sandbox_policy actually changed
        # from the previous turn (i.e. the user toggled a permission).
        new_model = payload.get("model")
        new_approval = payload.get("approval_policy")
        new_sandbox = payload.get("sandbox_policy")

        prev_approval = state.get("approval_policy")
        prev_sandbox = state.get("sandbox_policy")

        if new_model is not None:
            state["model"] = new_model
        if new_approval is not None:
            state["approval_policy"] = new_approval
        if new_sandbox is not None:
            state["sandbox_policy"] = new_sandbox

        yield TurnStart(
            id=line_id,
            turn_id=payload.get("turn_id"),
            cwd=payload.get("cwd"),
            model=new_model,
            **common,
        )

        # Detect explicit policy changes mid-session. We only emit on
        # actual change (not the first turn_context, where prev is None).
        if prev_approval is not None and new_approval and new_approval != prev_approval:
            # Parser-derived (no native row to round-trip back to) →
            # `synthesized=True` so serialize skips on self-roundtrip.
            # Cross-format converters still see and re-emit the event.
            yield Operator(
                source="codex",
                id=f"{line_id}#approval" if line_id else None,
                timestamp=timestamp,
                raw={},
                synthesized=True,
                action="approval_policy",
                detail=str(new_approval),
                metadata={"previous": prev_approval, "current": new_approval},
            )
        if prev_sandbox is not None and new_sandbox and new_sandbox != prev_sandbox:
            yield Operator(
                source="codex",
                id=f"{line_id}#sandbox" if line_id else None,
                timestamp=timestamp,
                raw={},
                synthesized=True,
                action="sandbox_policy",
                detail=_sandbox_label(new_sandbox),
                metadata={"previous": prev_sandbox, "current": new_sandbox},
            )
        return

    if rtype == "response_item":
        yield from _parse_response_item(payload, common, line_id, state)
        return

    if rtype == "event_msg":
        yield from _parse_event_msg(payload, common, line_id, state)
        return

    if rtype == "compacted":
        # Top-level context-compaction event. Carries `replacement_history`
        # — a fresh conversation list that supersedes everything before it.
        # Surfacing as a single Lifecycle event (with raw preserving the
        # full history) is the honest representation; consumers that
        # want to "replay" can re-parse from raw["payload"]["replacement_history"].
        yield Lifecycle(name="context_compacted", id=line_id, **common)
        return

    yield OpaqueEvent(original_type=str(rtype) if rtype else "unknown", id=line_id, **common)


# ------------------------------------------------------------------ #
# response_item                                                        #
# ------------------------------------------------------------------ #


def _parse_response_item(
    payload: dict, common: dict, line_id: Optional[str], state: dict
) -> Iterator[Event]:
    ptype = payload.get("type")

    if ptype == "message":
        role = payload.get("role")
        text = _message_content_to_text(payload.get("content"))
        if role in ("user", "developer", "system"):
            yield UserMessage(id=line_id, text=text, **common)
        else:
            yield AssistantMessage(
                id=line_id, text=text, model=state.get("model"), **common,
            )
        return

    if ptype == "function_call":
        call_id = payload.get("call_id", "")
        args_str = payload.get("arguments") or "{}"
        yield ToolCall(
            id=line_id,  # row-unique; tool_call_id is semantic
            tool_call_id=call_id,
            name=payload.get("name", ""),
            input=_safe_json_object(args_str),
            **common,
        )
        return

    if ptype == "function_call_output":
        call_id = payload.get("call_id", "")
        yield ToolResult(
            # Both function_call and function_call_output carry the same
            # call_id but live on different rows. Disambiguate via the
            # row's line id — keep call_id as a tag, but make the event id
            # row-unique so the serializer doesn't dedup the pair into one.
            id=line_id,
            tool_call_id=call_id,
            output=str(payload.get("output", "")),
            **common,
        )
        return

    if ptype == "reasoning":
        yield AssistantReasoning(
            id=line_id,
            text=_summary_to_text(payload.get("summary")),
            encrypted=bool(payload.get("encrypted_content")),
            encrypted_content=payload.get("encrypted_content"),
            **common,
        )
        return

    if ptype in ("custom_tool_call", "web_search_call", "tool_search_call"):
        call_id = payload.get("id") or payload.get("call_id") or ""
        raw_input = (
            payload.get("input")
            or payload.get("action")
            or payload.get("arguments")
            or {}
        )
        if isinstance(raw_input, str):
            raw_input = _safe_json_object(raw_input)
        yield ToolCall(
            id=line_id,  # row-unique
            tool_call_id=call_id,
            name=str(payload.get("name", ptype)),
            input=raw_input if isinstance(raw_input, dict) else {"value": raw_input},
            **common,
        )
        return

    if ptype in ("custom_tool_call_output", "web_search_call_output", "tool_search_output"):
        call_id = payload.get("call_id") or payload.get("id") or ""
        out = (
            payload.get("output")
            or payload.get("result")
            or json.dumps(payload.get("tools", []), ensure_ascii=False)
        )
        yield ToolResult(
            id=line_id,  # row-unique; tool_call_id keeps the original
            tool_call_id=call_id,
            output=str(out),
            **common,
        )
        return

    if ptype == "compacted":
        yield Lifecycle(name="context_compacted", id=line_id, **common)
        return

    yield OpaqueEvent(
        original_type=f"response_item.{ptype or 'unknown'}",
        id=line_id,
        **common,
    )


def _message_content_to_text(content: Any) -> str:
    """Flatten a response_item.message.content list into plain text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        bt = block.get("type")
        if bt in ("input_text", "output_text", "text"):
            parts.append(str(block.get("text", "")))
        elif bt == "input_image":
            parts.append("[image]")
        else:
            parts.append(json.dumps(block, ensure_ascii=False))
    return "\n".join(parts)


def _summary_to_text(summary: Any) -> Optional[str]:
    """codex reasoning has summary: list of {type, text} blocks. None if empty."""
    if not summary:
        return None
    if isinstance(summary, str):
        return summary
    if isinstance(summary, list):
        parts = []
        for s in summary:
            if isinstance(s, dict) and "text" in s:
                parts.append(str(s["text"]))
            else:
                parts.append(str(s))
        return "\n".join(parts) if parts else None
    return str(summary)


def _sandbox_label(policy: Any) -> str:
    """codex sandbox_policy is `{type: "danger-full-access" | ...}` or similar.
    Pull a short string for the Operator detail field."""
    if isinstance(policy, dict):
        return str(policy.get("type") or "")
    return str(policy or "")


def _image_media_type(image: Any) -> str:
    """Best-effort media type for an inline image. codex emits base64
    strings without prefixes most of the time, so we fall back to png."""
    if isinstance(image, str) and image.startswith("data:"):
        sep = image.find(";")
        if sep > 5:
            return image[5:sep]
    return "image/png"


def _image_media_type_from_path(path: Any) -> str:
    if not isinstance(path, str):
        return "image/png"
    p = path.lower()
    if p.endswith(".png"):
        return "image/png"
    if p.endswith(".jpg") or p.endswith(".jpeg"):
        return "image/jpeg"
    if p.endswith(".gif"):
        return "image/gif"
    if p.endswith(".webp"):
        return "image/webp"
    return "image/png"


def _extract_text(value: Any) -> Optional[str]:
    """Extract a string from a value that's either str, None, or {'text': str}.

    codex `base_instructions` and a few other fields use the `{text: ...}`
    wrapper inconsistently. Tolerate both shapes."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        t = value.get("text")
        if isinstance(t, str):
            return t
    return None


def _safe_json_object(s: Any) -> dict:
    """Parse a JSON string as a dict; return {} on failure or non-dict."""
    if isinstance(s, dict):
        return s
    if not isinstance(s, str):
        return {}
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {"value": v}
    except json.JSONDecodeError:
        return {}


# ------------------------------------------------------------------ #
# event_msg                                                            #
# ------------------------------------------------------------------ #


def _parse_event_msg(
    payload: dict, common: dict, line_id: Optional[str], state: dict
) -> Iterator[Event]:
    ptype = payload.get("type")

    if ptype == "user_message":
        yield UserMessage(id=line_id, text=str(payload.get("message", "")), **common)
        # codex carries attached images alongside the message itself in
        # `images` (inline) and `local_image_paths` (refs). Surface each
        # as its own Attachment so consumers see them as first-class.
        # synthesized=True because the original codex row holds them
        # inline; we don't want self-roundtrip to emit duplicates.
        for i, image in enumerate(payload.get("images") or []):
            yield Attachment(
                source="codex",
                id=f"{line_id}#img{i}" if line_id else None,
                timestamp=common.get("timestamp"),
                raw={},
                synthesized=True,
                media_type=_image_media_type(image),
                content=image if isinstance(image, str) else None,
            )
        for i, path in enumerate(payload.get("local_image_paths") or []):
            yield Attachment(
                source="codex",
                id=f"{line_id}#imgref{i}" if line_id else None,
                timestamp=common.get("timestamp"),
                raw={},
                synthesized=True,
                media_type=_image_media_type_from_path(path),
                ref=str(path),
                name=str(path).split("/")[-1] if path else None,
            )
        return

    if ptype == "agent_message":
        yield AssistantMessage(
            id=line_id,
            text=str(payload.get("message", "")),
            phase=payload.get("phase"),
            model=state.get("model"),
            **common,
        )
        return

    if ptype == "agent_reasoning":
        yield AssistantReasoning(
            id=line_id,
            text=str(payload.get("text", "")),
            encrypted=False,
            **common,
        )
        return

    if ptype == "task_started":
        yield TurnStart(id=line_id, turn_id=payload.get("turn_id"), **common)
        return

    if ptype == "task_complete":
        yield TurnEnd(id=line_id, turn_id=payload.get("turn_id"), **common)
        return

    if ptype == "turn_aborted":
        yield TurnEnd(id=line_id, turn_id=payload.get("turn_id"), aborted=True, **common)
        return

    if ptype == "token_count":
        info = payload.get("info") or {}
        last_token_usage = info.get("last_token_usage") or {}
        total_token_usage = info.get("total_token_usage") or {}
        usage = last_token_usage or total_token_usage or {}
        yield TokenUsage(
            id=line_id,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cache_read_tokens=usage.get("cached_input_tokens"),
            total_tokens=usage.get("total_tokens"),
            provider=state.get("provider") or "openai",
            **common,
        )
        return

    if ptype == "exec_command_end":
        call_id = payload.get("call_id", "")
        yield ToolResult(
            id=line_id,
            tool_call_id=call_id,
            output=str(payload.get("formatted_output") or payload.get("output") or ""),
            exit_code=payload.get("exit_code"),
            duration_ms=_extract_duration_ms(payload),
            **common,
        )
        return

    if ptype == "patch_apply_end":
        yield Lifecycle(name="patch_apply_end", id=line_id, **common)
        return

    if ptype == "web_search_end":
        yield ToolResult(
            id=line_id,
            tool_call_id=payload.get("call_id", ""),
            output=str(payload.get("output") or ""),
            **common,
        )
        return

    if ptype == "thread_name_updated":
        yield Lifecycle(name="thread_name_updated", id=line_id, **common)
        return

    if ptype == "error":
        yield Lifecycle(name="error", id=line_id, **common)
        return

    if ptype == "context_compacted":
        yield Lifecycle(name="context_compacted", id=line_id, **common)
        return

    if ptype == "mcp_tool_call_end":
        call_id = payload.get("call_id", "")
        result = payload.get("result") or {}
        if isinstance(result, dict):
            ok = result.get("Ok") or result.get("ok") or {}
            err = result.get("Err") or result.get("err")
            content = ok.get("content") if isinstance(ok, dict) else None
            output_text = _mcp_content_to_text(content) if content else json.dumps(result, ensure_ascii=False)
            is_error = bool(err)
        else:
            output_text = str(result)
            is_error = False
        yield ToolResult(
            id=line_id,
            tool_call_id=call_id,
            output=output_text,
            is_error=is_error,
            duration_ms=_extract_duration_ms(payload),
            **common,
        )
        return

    if ptype == "collab_agent_spawn_end":
        call_id = payload.get("call_id", "")
        yield ToolCall(
            id=line_id,
            tool_call_id=call_id,
            name=f"collab_agent.{payload.get('new_agent_role', 'agent')}",
            input={
                "agent_nickname": payload.get("new_agent_nickname"),
                "agent_role": payload.get("new_agent_role"),
                "thread_id": payload.get("new_thread_id"),
                "prompt": payload.get("prompt"),
            },
            **common,
        )
        return

    if ptype == "collab_waiting_end":
        call_id = payload.get("call_id", "")
        statuses = payload.get("agent_statuses") or []
        yield ToolResult(
            id=line_id,
            tool_call_id=call_id,
            output=json.dumps(statuses, ensure_ascii=False),
            **common,
        )
        return

    if ptype == "collab_close_end":
        call_id = payload.get("call_id", "")
        status = payload.get("status") or {}
        if isinstance(status, dict):
            done_text = status.get("completed") or status.get("aborted") or json.dumps(status, ensure_ascii=False)
        else:
            done_text = str(status)
        yield ToolResult(
            id=line_id,
            tool_call_id=call_id,
            output=str(done_text),
            **common,
        )
        return

    yield OpaqueEvent(original_type=f"event_msg.{ptype or 'unknown'}", id=line_id, **common)


def _mcp_content_to_text(content: Any) -> str:
    """Flatten an MCP result.content list into a single string."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(str(b.get("text", "")))
        else:
            parts.append(json.dumps(b, ensure_ascii=False))
    return "\n".join(parts)


def _serialize_event_for_codex(ev: Event, seen: set[str]) -> Optional[str]:
    """Return one codex JSONL line for `ev`, or None to skip.

    Decision matrix matches claude's: same-source emits raw, same-source
    synthesized events skip, cross-source synthesizes.
    """
    if ev.source == "codex":
        if ev.synthesized:
            return None
        if not has_substantive_raw(ev.raw):
            # Same-source bare event (e.g. seeded into a SessionStore
            # without raw context, or raw carrying only `_synth`).
            return _synthesize_codex_cross_source(ev)
        ev_id = str(ev.id or "")
        if ev_id and ev_id in seen:
            return None
        if ev_id:
            seen.add(ev_id)
        return json.dumps(dict(ev.raw), ensure_ascii=False, separators=(",", ":"))

    return _synthesize_codex_cross_source(ev)


def _synthesize_codex_cross_source(ev: Event) -> Optional[str]:
    """Produce a codex row from a non-codex unified event.

    Codex's two-layer (response_item / event_msg) shape gives us choice;
    we project to the wire-level `response_item` layer because that's
    what codex actually replays from. Events that don't map to a codex
    response_item kind are emitted as `event_msg.error` lifecycle rows
    so the file still parses.
    """
    timestamp = ev.timestamp or ""

    if ev.type == "user_message":
        return json.dumps({
            "timestamp": timestamp,
            "type": "response_item",
            "payload": {"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": getattr(ev, "text", "")}]},
        }, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "assistant_message":
        return json.dumps({
            "timestamp": timestamp,
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": getattr(ev, "text", "")}]},
        }, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "assistant_reasoning":
        # Plaintext reasoning fits the response_item.reasoning shape via
        # `summary`; encrypted content is preserved in `encrypted_content`.
        text = getattr(ev, "text", None)
        encrypted = getattr(ev, "encrypted_content", None)
        return json.dumps({
            "timestamp": timestamp,
            "type": "response_item",
            "payload": {"type": "reasoning",
                        "summary": [{"type": "summary_text", "text": text}] if text else [],
                        "encrypted_content": encrypted,
                        },
        }, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "tool_call":
        import json as _j
        return json.dumps({
            "timestamp": timestamp,
            "type": "response_item",
            "payload": {"type": "function_call",
                        "call_id": getattr(ev, "tool_call_id", ""),
                        "name": getattr(ev, "name", ""),
                        "arguments": _j.dumps(getattr(ev, "input", {}) or {}, ensure_ascii=False),
                        },
        }, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "tool_result":
        return json.dumps({
            "timestamp": timestamp,
            "type": "response_item",
            "payload": {"type": "function_call_output",
                        "call_id": getattr(ev, "tool_call_id", ""),
                        "output": getattr(ev, "output", "") or "",
                        },
        }, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "session_start":
        synth = (ev.raw or {}).get("_synth", {}) if isinstance(ev.raw, dict) else {}
        # codex resume requires a UUID; if the source's id wasn't a UUID
        # the converter pre-injects one in synth.session_id.
        session_id = synth.get("session_id") or ev.id or ""
        cwd = synth.get("cwd") or getattr(ev, "cwd", None) or "/tmp"
        # codex's thread-store deserializes session_meta into a strict
        # struct and 400s on `does not start with session metadata` when
        # required keys are missing. The fields below are the ones real
        # codex sessions carry on session_meta.payload.
        return json.dumps({
            "timestamp": timestamp,
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": timestamp,  # nested duplicate is required
                "cwd": cwd,
                "originator": "codex_cli_rs",  # match a known originator
                "cli_version": getattr(ev, "agent_version", None) or synth.get("version") or "0.0.0",
                "source": "cli",  # the *kind* of run; "cli" is what real sessions emit
                "model_provider": "openai",
                # codex's deserializer requires {text: "..."}; a plain
                # string here trips "does not start with session metadata".
                "base_instructions": {"text": getattr(ev, "user_instructions", None)
                                              or "You are an assistant."},
            },
        }, ensure_ascii=False, separators=(",", ":"))

    if ev.type in ("turn_start",):
        return json.dumps({
            "timestamp": timestamp,
            "type": "turn_context",
            "payload": {"turn_id": getattr(ev, "turn_id", "") or ev.id or "",
                        "cwd": getattr(ev, "cwd", None),
                        "model": getattr(ev, "model", None),
                        },
        }, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "turn_end":
        ptype = "turn_aborted" if getattr(ev, "aborted", False) else "task_complete"
        return json.dumps({
            "timestamp": timestamp,
            "type": "event_msg",
            "payload": {"type": ptype,
                        "turn_id": getattr(ev, "turn_id", "") or ev.id or "",
                        },
        }, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "token_usage":
        return json.dumps({
            "timestamp": timestamp,
            "type": "event_msg",
            "payload": {"type": "token_count",
                        "info": {"last_token_usage": {
                            "input_tokens": getattr(ev, "input_tokens", None),
                            "output_tokens": getattr(ev, "output_tokens", None),
                            "cached_input_tokens": getattr(ev, "cache_read_tokens", None),
                            "total_tokens": getattr(ev, "total_tokens", None),
                        }},
                        },
        }, ensure_ascii=False, separators=(",", ":"))

    # Lifecycle / opaque / file_edit / session_end fall through to a
    # generic event_msg row carrying the cross-source name so a codex
    # reader can ignore it gracefully.
    name = getattr(ev, "name", None) or getattr(ev, "original_type", None) or ev.type
    return json.dumps({
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "thread_name_updated",
                    "thread_name": f"[converted from {ev.source}] {name}"},
    }, ensure_ascii=False, separators=(",", ":"))


def _extract_duration_ms(payload: dict) -> Optional[int]:
    """Try a couple of possible field shapes."""
    if "duration_ms" in payload:
        try:
            return int(payload["duration_ms"])
        except (ValueError, TypeError):
            return None
    duration = payload.get("duration")
    if isinstance(duration, (int, float)):
        return int(duration * 1000) if duration < 1e6 else int(duration)
    if isinstance(duration, dict):
        # Common shape: {"secs": int, "nanos": int}
        secs = duration.get("secs")
        nanos = duration.get("nanos", 0)
        if secs is not None:
            try:
                return int(secs) * 1000 + int(nanos) // 1_000_000
            except (ValueError, TypeError):
                return None
    return None
