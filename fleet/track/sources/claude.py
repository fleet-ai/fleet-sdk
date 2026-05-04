"""ClaudeSource — `~/.claude/projects/**/*.jsonl`.

Serialization strategy
----------------------

`serialize()` has two modes, chosen per event:

  1. **Same-source** (`event.source == "claude"` and `event.raw` is non-empty):
     emit the original row from `event.raw`. Sub-events derived from the
     same row (id contains `#`) are skipped — the parent row already
     captured them. This gives a near-byte-identical round-trip
     (modulo JSON key order).

  2. **Cross-source** (event came from codex / cursor / opencode):
     synthesize a claude-shaped row from the kernel fields. Lossy by
     construction. We emit only the events claude can render
     (user/assistant messages, tool calls/results); other events
     become `system`-typed comment rows so they're not silently lost.

Format notes (cataloged from real session files):

  Top-level row types observed:
    - `user` / `assistant` / `system`              — conversation
    - `attachment`                                  — user attached files
    - `last-prompt`                                 — pre-call prompt snapshot
    - `permission-mode`                             — agent perm-mode change
    - `file-history-snapshot`                       — file edit snapshot
    - `ai-title`                                    — generated session title
    - `queue-operation`                             — internal queue events
    - `pr-link`                                     — emitted PR URLs

  Each row carries: uuid, parentUuid, sessionId, timestamp, cwd,
  gitBranch, version, userType, isSidechain, entrypoint, requestId.
  parent_uuid + uuid form a tree (multiple children of same parent =
  conversation branch).

  `assistant.message.content` is a list of blocks:
    - `text`        — visible response text
    - `tool_use`    — tool invocation { id, name, input }
    - `thinking`    — chain-of-thought; { thinking: text }

  `user.message.content` is either a string OR a list of blocks:
    - `tool_result` — { tool_use_id, content, is_error? }
    - `text`        — additional text after a tool result
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
    OpaqueEvent,
    Operator,
    SessionStart,
    ToolCall,
    ToolResult,
    UserMessage,
)
from .base import Source, _walk_glob, has_substantive_raw

log = logging.getLogger("fleet.track.sources.claude")


class ClaudeSource(Source):
    name = "claude"

    @property
    def root(self) -> Path:
        return self._home / ".claude" / "projects"

    def iter_files(self) -> Iterator[Path]:
        yield from _walk_glob(self.root, "**/*.jsonl", self.exclude_patterns)

    def read_for_upload(self, path: Path) -> bytes | None:
        """Trim partial trailing JSONL line so we never upload a half-written record."""
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
    # Serialize                                                            #
    # ------------------------------------------------------------------ #

    def serialize(self, events: Iterable[Event]) -> bytes:
        """Convert a stream of unified events to claude JSONL bytes.

        Self-format round-trip is exact (modulo JSON key order). Cross-format
        events are synthesized into claude-shaped rows; lossy.
        """
        out_lines: list[str] = []
        seen_row_ids: set[str] = set()  # de-dup parent rows when sub-events share raw

        for ev in events:
            line = _serialize_event_for_claude(ev, seen_row_ids)
            if line is not None:
                out_lines.append(line)

        return ("\n".join(out_lines) + ("\n" if out_lines else "")).encode("utf-8")

    # ------------------------------------------------------------------ #
    # Parse                                                                #
    # ------------------------------------------------------------------ #

    def parse(self, path: Path) -> Iterable[Event]:
        """Yield unified Events. Never raises on malformed input.

        We emit one event per *content block*, not per row, so an
        assistant row with [text, tool_use, thinking] becomes three
        Events sharing the same `parent_id` and a suffixed `id`.

        Rows without a `uuid` (e.g. permission-mode, last-prompt) get
        a synthesized id of `L{line_no}` so the (parent_id, id) chain
        and the serializer's row-dedup logic both work.
        """
        first = True
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        doc = json.loads(line)
                    except json.JSONDecodeError as e:
                        log.debug("claude.parse: skip malformed line %d in %s: %s", line_no, path, e)
                        continue

                    # Synthesize one SessionStart from the first row that
                    # carries the metadata.
                    if first and isinstance(doc, dict):
                        first = False
                        ss = _maybe_session_start(doc)
                        if ss is not None:
                            yield ss

                    if not isinstance(doc, dict):
                        continue
                    yield from _parse_row(doc, line_no=line_no)
        except OSError as e:
            log.warning("claude.parse: cannot read %s: %s", path, e)
            return


# ------------------------------------------------------------------ #
# Per-row dispatch                                                     #
# ------------------------------------------------------------------ #


def _maybe_session_start(doc: dict) -> Optional[SessionStart]:
    """Return a SessionStart if the row carries enough session metadata."""
    if not any(k in doc for k in ("cwd", "gitBranch", "version", "sessionId")):
        return None
    return SessionStart(
        source="claude",
        id=doc.get("sessionId"),
        timestamp=doc.get("timestamp"),
        cwd=doc.get("cwd"),
        agent_version=doc.get("version"),
        git_branch=doc.get("gitBranch"),
        raw={},  # the SessionStart synthesis is deliberately metadata-only.
        synthesized=True,  # don't re-emit on self-roundtrip
    )


def _parse_row(doc: dict, line_no: int = 0) -> Iterator[Event]:
    common = _common_fields(doc, line_no=line_no)
    rtype = doc.get("type", "")

    if rtype == "user":
        yield from _parse_user(doc, common)
    elif rtype == "assistant":
        yield from _parse_assistant(doc, common)
    elif rtype == "system":
        yield Lifecycle(name="system", **common)
    elif rtype == "attachment":
        yield from _parse_attachment_row(doc, common)
    elif rtype == "last-prompt":
        yield Lifecycle(name="last_prompt", **common)
    elif rtype == "permission-mode":
        # Claude's permission-mode rows record a user-driven mode change
        # (default / acceptEdits / bypassPermissions / plan / etc.).
        # That's a human-in-the-loop intervention → Operator.
        yield Operator(
            action="permission_mode",
            detail=str(doc.get("permissionMode", "")),
            metadata={k: v for k, v in doc.items() if k in ("permissionMode",)},
            **common,
        )
    elif rtype == "ai-title":
        yield Lifecycle(name="ai_title", **common)
    elif rtype == "custom-title":
        yield Lifecycle(name="custom_title", **common)
    elif rtype == "agent-name":
        yield Lifecycle(name="agent_name", **common)
    elif rtype == "queue-operation":
        yield Lifecycle(name="queue_operation", **common)
    elif rtype == "pr-link":
        yield Lifecycle(name="pr_link", **common)
    elif rtype == "progress":
        yield Lifecycle(name="progress", **common)
    elif rtype == "file-history-snapshot":
        yield from _parse_file_history(doc, common)
    else:
        yield OpaqueEvent(original_type=str(rtype), **common)


def _common_fields(doc: dict, line_no: int = 0) -> dict[str, Any]:
    # Prefer the row's uuid; fall back to a synthetic line id so events
    # from rows that don't carry a uuid (permission-mode, file-history,
    # etc.) still have a unique id for serializer dedup and tree-walking.
    row_id = doc.get("uuid") or (f"L{line_no}" if line_no else None)
    return {
        "source": "claude",
        "id": row_id,
        "parent_id": doc.get("parentUuid"),
        "timestamp": doc.get("timestamp"),
        "raw": doc,
    }


def _sub_id(common: dict, idx: int) -> dict:
    """Return a `common` with the id suffixed by `#idx` (0 → unchanged)."""
    if idx == 0:
        # First sub-event keeps the row's uuid for natural reference.
        # Subsequent rows in the same row chain link to this one.
        return common
    return {**common, "id": f"{common.get('id') or ''}#{idx}"}


# ------------------------------------------------------------------ #
# user rows                                                            #
# ------------------------------------------------------------------ #


def _parse_user(doc: dict, common: dict) -> Iterator[Event]:
    msg = doc.get("message") or {}
    content = msg.get("content")

    if isinstance(content, str):
        yield UserMessage(text=content, **common)
        return

    if not isinstance(content, list):
        # Unknown shape; preserve as opaque.
        yield OpaqueEvent(original_type="user_unknown_content_shape", **common)
        return

    for i, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        bt = block.get("type")
        sub_common = _sub_id(common, i)

        if bt == "text":
            yield UserMessage(text=block.get("text", ""), **sub_common)
        elif bt == "tool_result":
            output = _tool_result_to_text(block.get("content"))
            yield ToolResult(
                tool_call_id=block.get("tool_use_id", ""),
                output=output,
                is_error=bool(block.get("is_error", False)),
                **sub_common,
            )
        elif bt == "image":
            # User-attached image: model as Attachment with content (base64
            # in claude's `source.data` field) or ref preserved in raw.
            src = block.get("source") or {}
            data = src.get("data") if isinstance(src, dict) else None
            media = (src.get("media_type") if isinstance(src, dict) else None) or "image/png"
            yield Attachment(
                media_type=media,
                content=data if isinstance(data, str) else None,
                **sub_common,
            )
        else:
            yield OpaqueEvent(original_type=f"user_block.{bt or 'unknown'}", **sub_common)


def _tool_result_to_text(content: Any) -> str:
    """Flatten a claude tool_result.content (string OR block list) into a single string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(str(b.get("text", "")))
                elif b.get("type") == "image":
                    # Preserve a placeholder; the actual image bytes
                    # live in raw on the parent event.
                    parts.append("[image]")
                else:
                    parts.append(json.dumps(b, ensure_ascii=False))
            else:
                parts.append(str(b))
        return "\n".join(parts)
    return str(content)


# ------------------------------------------------------------------ #
# assistant rows                                                       #
# ------------------------------------------------------------------ #


def _parse_assistant(doc: dict, common: dict) -> Iterator[Event]:
    msg = doc.get("message") or {}
    content = msg.get("content") or []

    if not isinstance(content, list):
        yield OpaqueEvent(original_type="assistant_unknown_content_shape", **common)
        return

    for i, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        bt = block.get("type")
        sub_common = _sub_id(common, i)

        if bt == "text":
            yield AssistantMessage(
                text=block.get("text", ""),
                model=msg.get("model"),
                **sub_common,
            )
        elif bt == "thinking":
            yield AssistantReasoning(text=block.get("thinking", ""), **sub_common)
        elif bt == "tool_use":
            yield ToolCall(
                tool_call_id=block.get("id", ""),
                name=block.get("name", ""),
                input=block.get("input") or {},
                **sub_common,
            )
        else:
            yield OpaqueEvent(original_type=f"assistant_block.{bt or 'unknown'}", **sub_common)


# ------------------------------------------------------------------ #
# file-history-snapshot rows                                           #
# ------------------------------------------------------------------ #


def _serialize_event_for_claude(ev: Event, seen_row_ids: set[str]) -> Optional[str]:
    """Return one JSONL line for `ev`, or None to skip.

    Decision matrix:
      - source==claude, raw set      → emit raw (same-source roundtrip)
      - source==claude, raw empty    → skip (parser-synthesized event;
                                       no original row to reproduce)
      - source!=claude               → synthesize a claude row (lossy
                                       cross-format conversion)
    """
    if ev.source == "claude":
        if ev.synthesized:
            return None  # parser-synthesized view; no original row to emit
        if not has_substantive_raw(ev.raw):
            # Same-source bare event (e.g. seeded into a SessionStore
            # without raw context — raw is empty or only carries
            # `_synth` metadata). Synthesize a native row from kernel
            # fields so the data isn't lost.
            return _synthesize_claude_cross_source(ev)
        ev_id = str(ev.id or "")
        if "#" in ev_id:
            return None  # secondary block; row already emitted by primary
        if ev_id in seen_row_ids:
            return None  # defensive: same primary id seen twice
        if ev_id:
            seen_row_ids.add(ev_id)
        return json.dumps(dict(ev.raw), ensure_ascii=False, separators=(",", ":"))

    # Cross-source: synthesize a claude row. (Implemented in iteration 4
    # alongside the cross-format tests.) For now, we fall back to
    # emitting the event as a `system`-typed claude row carrying its
    # source and raw payload — preserves data without crashing the
    # claude reader.
    return _synthesize_claude_cross_source(ev)


def _synthesize_claude_cross_source(ev: Event) -> str:
    """Produce a claude row from a non-claude unified event.

    Field set is the union of what real claude sessions carry on
    user/assistant rows (audited from production session files):
    cwd, entrypoint, gitBranch, isSidechain, parentUuid, sessionId,
    timestamp, type, userType, uuid, version, message.

    `claude --resume <uuid>` expects a file at
    `~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl` where every
    row carries the matching `sessionId`. Cross-source-synthesized
    rows propagate `_session_id` and `_cwd` from a SessionStart-shaped
    Event when present (held in `raw["_synth"]`). Otherwise we fall
    back to placeholders that won't crash the claude reader.
    """
    synth_meta = (ev.raw or {}).get("_synth", {}) if isinstance(ev.raw, dict) else {}
    session_id = synth_meta.get("session_id") or ev.id or "00000000-0000-0000-0000-000000000000"
    cwd = synth_meta.get("cwd") or "/tmp"
    git_branch = synth_meta.get("git_branch") or ""
    version = synth_meta.get("version") or "0.0.0-converted"

    base = {
        "uuid": ev.id or session_id,
        "parentUuid": ev.parent_id,
        "timestamp": ev.timestamp or "",
        "sessionId": session_id,
        "cwd": cwd,
        "gitBranch": git_branch,
        "version": version,
        "entrypoint": "converted",
        "isSidechain": False,
        "userType": "external",
    }

    if ev.type == "user_message":
        return json.dumps({**base, "type": "user", "message": {
            "role": "user", "content": getattr(ev, "text", "")
        }}, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "assistant_message":
        text = getattr(ev, "text", "")
        return json.dumps({**base, "type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        }}, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "assistant_reasoning":
        text = getattr(ev, "text", None) or ""
        return json.dumps({**base, "type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": text}],
        }}, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "tool_call":
        return json.dumps({**base, "type": "assistant", "message": {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": getattr(ev, "tool_call_id", ""),
                "name": getattr(ev, "name", ""),
                "input": getattr(ev, "input", {}) or {},
            }],
        }}, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "tool_result":
        return json.dumps({**base, "type": "user", "message": {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": getattr(ev, "tool_call_id", ""),
                "content": getattr(ev, "output", "") or "",
                "is_error": getattr(ev, "is_error", False),
            }],
        }}, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "session_start":
        # No claude row type cleanly maps to "session start". Emit a
        # `system` row carrying the metadata so the data isn't lost.
        cwd = getattr(ev, "cwd", None)
        version = getattr(ev, "agent_version", None)
        return json.dumps({**base, "type": "system",
                           "content": f"[converted from {ev.source}] cwd={cwd} agent={version}"
                           }, ensure_ascii=False, separators=(",", ":"))

    if ev.type == "lifecycle":
        # Many lifecycle events map to claude top-level types. For
        # now, fall back to `system` with a description.
        name = getattr(ev, "name", "")
        return json.dumps({**base, "type": "system",
                           "content": f"[converted from {ev.source}] {name}"
                           }, ensure_ascii=False, separators=(",", ":"))

    # Everything else: a no-op `system` row so cross-format converted
    # files still parse on the claude side.
    return json.dumps({**base, "type": "system",
                       "content": f"[converted from {ev.source}] {ev.type}"
                       }, ensure_ascii=False, separators=(",", ":"))


def _parse_attachment_row(doc: dict, common: dict) -> Iterator[Event]:
    """Claude's `attachment` rows describe a file or image the user attached
    to the conversation. Shape varies; we extract media_type + name + ref
    where present and preserve everything else in raw."""
    att = doc.get("attachment") or {}
    if not isinstance(att, dict):
        # Attachment row without a structured payload: fall back to a
        # bare Attachment (raw still has the original).
        yield Attachment(media_type="application/octet-stream", **common)
        return

    media_type = (
        att.get("type")
        or att.get("media_type")
        or att.get("mimeType")
        or "application/octet-stream"
    )
    name = att.get("name") or att.get("path") or att.get("filename")
    ref = att.get("path") or att.get("url") or att.get("ref")
    content = att.get("data") if isinstance(att.get("data"), str) else None
    yield Attachment(
        media_type=str(media_type),
        name=str(name) if name else None,
        ref=str(ref) if ref else None,
        content=content,
        **common,
    )


def _parse_file_history(doc: dict, common: dict) -> Iterator[Event]:
    """Each row may snapshot one or many files. Emit one FileEdit per file."""
    snapshot = doc.get("snapshot")
    if isinstance(snapshot, dict):
        # Single-file shape.
        path = snapshot.get("path") or snapshot.get("filePath") or ""
        yield FileEdit(
            path=str(path),
            diff=snapshot.get("diff"),
            pre_content=snapshot.get("pre"),
            post_content=snapshot.get("post"),
            **common,
        )
        return

    if isinstance(snapshot, list):
        for i, item in enumerate(snapshot):
            if not isinstance(item, dict):
                continue
            sub_common = _sub_id(common, i)
            path = item.get("path") or item.get("filePath") or ""
            yield FileEdit(
                path=str(path),
                diff=item.get("diff"),
                pre_content=item.get("pre"),
                post_content=item.get("post"),
                **sub_common,
            )
        return

    # No snapshot field — emit Lifecycle as fallback so the row isn't lost.
    yield Lifecycle(name="file_history_snapshot", **common)
