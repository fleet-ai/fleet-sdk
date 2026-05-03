"""Unified event format for AI coding sessions.

Every format we ingest (claude, codex, cursor, opencode) parses into the
same `Event` discriminated union. Each event carries:

  - a small set of typed fields representing the **semantic kernel**
    shared across formats (user said X, assistant said Y, tool was
    called with args Z, etc.);
  - a `source` tag identifying which CLI produced it;
  - a `raw` blob containing the original row, so anything the kernel
    doesn't model survives round-trip via the source's `serialize()`.

Design constraints (re-stated for any reader of this file):

  1. **Best-effort, never crash.** Unknown event subtypes parse as
     `OpaqueEvent(original_type=...)` rather than raising. Malformed
     JSON in a session file is logged + skipped.

  2. **Lossy is OK.** claude → unified → codex deliberately drops
     claude-specific concepts that codex can't render
     (e.g. `parentUuid` branching). Round-trip *to the same source*
     should be near-faithful via `raw`; round-trip across sources is
     always lossy by construction.

  3. **Linear iteration.** The unified stream is linear (a list, not a
     tree). Tree-shaped sources (claude) flatten by walking the longest
     leaf path; `parent_id` is preserved on each event so consumers that
     care about branches can rebuild the tree.

  4. **Source-agnostic kernel.** Field names borrow from neither claude
     nor codex specifically. Where they diverge (e.g. claude uses
     `tool_use_id`, codex uses `call_id`) we pick a neutral term
     (`tool_call_id`).

The kernel will grow over time as use cases demand. Today's set is
"the events all four formats agreed on" — anything format-specific
lives in `raw` and is recovered on serialize.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Mapping, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ------------------------------------------------------------------ #
# Helpers (used by multiple events)                                    #
# ------------------------------------------------------------------ #


class ToolSpec(BaseModel):
    """A tool the agent had available at session start.

    Borrows attribute names from OpenTelemetry GenAI semantic conventions
    (`gen_ai.tool.call.*`) and OpenInference's tool span shape, so emitting
    OTel-compatible spans from this data later is a flat re-key.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    name: str
    description: Optional[str] = None
    input_schema: Optional[dict] = None  # JSON Schema

# ------------------------------------------------------------------ #
# Source tags                                                          #
# ------------------------------------------------------------------ #

Source = Literal["claude", "codex", "cursor", "opencode", "unknown"]


# ------------------------------------------------------------------ #
# Base                                                                 #
# ------------------------------------------------------------------ #


class _EventBase(BaseModel):
    """Common fields on every event.

    `model_config(extra="allow")` is intentional: a future format we
    haven't seen yet may carry fields we'll want to read without bumping
    the schema.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    source: Source
    # Stable id from the source if any. claude.uuid for top-level rows;
    # for events derived from one row's content blocks we suffix `#i`
    # so the (id, parent_id) chain stays unique.
    id: Optional[str] = None
    parent_id: Optional[str] = None
    # ISO-8601 string. Kept as string (not datetime) so we don't
    # silently re-format it on round-trip.
    timestamp: Optional[str] = None
    # Original source row (or sub-row) as a dict. Source serializers use
    # this to reconstruct format-specific fields the kernel doesn't model.
    raw: Mapping[str, Any] = Field(default_factory=dict)
    # True when the event was synthesized by a parser as a derived view
    # (e.g. claude.parse fabricates a SessionStart from the first row's
    # metadata; that synthesized event has no original row to round-trip
    # back to). Same-source serializers skip these to keep the output
    # byte-identical to the input. Cross-source serializers ignore the
    # flag and synthesize freely.
    synthesized: bool = False


# ------------------------------------------------------------------ #
# Lifecycle / metadata                                                 #
# ------------------------------------------------------------------ #


class SessionStart(_EventBase):
    type: Literal["session_start"] = "session_start"
    # Anything the format gives us about session-level context.
    cwd: Optional[str] = None
    model: Optional[str] = None
    agent_version: Optional[str] = None
    git_branch: Optional[str] = None
    # System / developer instructions configured at session start.
    user_instructions: Optional[str] = None
    # Tools the agent had access to. Populated where the source format
    # surfaces them (codex's tool catalog, claude system prompts that
    # enumerate); empty when the source doesn't expose them as data.
    tools_available: list[ToolSpec] = Field(default_factory=list)


class SessionEnd(_EventBase):
    type: Literal["session_end"] = "session_end"
    stop_reason: Optional[str] = None


class TurnStart(_EventBase):
    """One agent "turn": a user message → some number of assistant outputs.

    codex emits explicit task_started / task_complete events; claude
    treats turns implicitly (a `user` row begins one). On parse, we
    synthesize TurnStart / TurnEnd for sources that don't emit them so
    consumers can rely on turn boundaries existing.
    """

    type: Literal["turn_start"] = "turn_start"
    turn_id: Optional[str] = None
    cwd: Optional[str] = None
    model: Optional[str] = None


class TurnEnd(_EventBase):
    type: Literal["turn_end"] = "turn_end"
    turn_id: Optional[str] = None
    aborted: bool = False


# ------------------------------------------------------------------ #
# Conversation                                                         #
# ------------------------------------------------------------------ #


class UserMessage(_EventBase):
    type: Literal["user_message"] = "user_message"
    text: str
    # Format-specific extras (image refs, file paths, etc.) live in raw.


class AssistantMessage(_EventBase):
    type: Literal["assistant_message"] = "assistant_message"
    text: str
    # codex.event_msg.agent_message has phase ∈ {commentary, final, ...}
    # claude has no phase; we leave it None.
    phase: Optional[str] = None
    # Model that produced this message. Populated where parseable
    # (claude `assistant.message.model`, codex's tracked turn context).
    # None when the source doesn't say.
    model: Optional[str] = None


class AssistantReasoning(_EventBase):
    """Model thinking / chain-of-thought.

    claude exposes plaintext via `thinking` content blocks. codex stores
    encrypted reasoning blobs (`encrypted_content`); the plaintext
    streamed-event-msg variant (`agent_reasoning`) is also captured but
    on a separate event.
    """

    type: Literal["assistant_reasoning"] = "assistant_reasoning"
    text: Optional[str] = None
    encrypted: bool = False
    encrypted_content: Optional[str] = None


# ------------------------------------------------------------------ #
# Tool use                                                             #
# ------------------------------------------------------------------ #


class ToolCall(_EventBase):
    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str
    name: str
    # Parsed JSON; codex stores `arguments` as a JSON string at the wire
    # level. We parse on ingest so consumers get a dict.
    input: dict = Field(default_factory=dict)


class ToolResult(_EventBase):
    type: Literal["tool_result"] = "tool_result"
    # Empty string when the source row didn't carry one — codex
    # function_call_output and exec_command_end both use call_id, but
    # claude's tool_result references tool_use_id. Both map here.
    tool_call_id: str
    output: str = ""
    is_error: bool = False
    # Shell-tool extras when the source provides them.
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None


# ------------------------------------------------------------------ #
# Telemetry                                                            #
# ------------------------------------------------------------------ #


class TokenUsage(_EventBase):
    type: Literal["token_usage"] = "token_usage"
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_write_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    # OTel `gen_ai.provider.name` analog. "anthropic" / "openai" / etc.
    provider: Optional[str] = None
    # Wall-clock latency of the inference call producing these tokens,
    # if the source records it. claude doesn't expose this directly;
    # codex carries it in some event_msg variants.
    latency_ms: Optional[int] = None


# ------------------------------------------------------------------ #
# File operations                                                      #
# ------------------------------------------------------------------ #


class FileEdit(_EventBase):
    """A model-driven file edit, captured at edit-apply time.

    claude: `file-history-snapshot` rows.
    codex: `event_msg.patch_apply_end` rows.

    We standardize on a unified-diff representation when the source
    provides one; pre/post content is optional for sources that only
    snapshot end-state.
    """

    type: Literal["file_edit"] = "file_edit"
    path: str
    diff: Optional[str] = None
    pre_content: Optional[str] = None
    post_content: Optional[str] = None


# ------------------------------------------------------------------ #
# Lifecycle catch-all + opaque                                         #
# ------------------------------------------------------------------ #


class Operator(_EventBase):
    """Human-in-the-loop intervention.

    Borrowed from Inspect AI's `operator` event class. Examples we
    surface today: claude permission-mode toggles, future explicit
    permission grants/denials. Distinct from `Lifecycle` because
    operator events are user-driven; lifecycles are agent/runtime-driven.
    """

    type: Literal["operator"] = "operator"
    action: str         # e.g. "permission_mode", "permission_grant", "interrupt"
    detail: Optional[str] = None
    # Optional structured payload (e.g. the new mode value, the granted
    # tool name). Free-form so source-specific shapes survive round-trip.
    metadata: dict = Field(default_factory=dict)


class Attachment(_EventBase):
    """User-attached blob (image, file, snippet) provided as input.

    Distinct from `FileEdit` (which is a model-driven write to disk).
    Inspect AI separates messages from attachments by reference id;
    we follow the same pattern: `content` is inline payload (base64
    for images), `ref` points to an external blob the source carries
    out-of-band. At least one of `content` or `ref` is set, never both empty.
    """

    type: Literal["attachment"] = "attachment"
    media_type: str          # e.g. "image/png", "text/plain", "application/pdf"
    name: Optional[str] = None
    content: Optional[str] = None  # base64 (images) or text (small)
    ref: Optional[str] = None      # external reference (blob id, file path)


class Lifecycle(_EventBase):
    """Source-specific lifecycle events that don't map to a kernel concept
    but are worth tagging by name (rather than being fully opaque)."""

    type: Literal["lifecycle"] = "lifecycle"
    name: str
    """The original event name in the source format. Examples:
       claude: 'pr_link', 'ai_title', 'last_prompt', 'queue_operation'
       codex:  'thread_name_updated', 'error', 'context_compacted'
    Tests assert on these names; serializers use them to round-trip."""


class OpaqueEvent(_EventBase):
    """Last-resort wrapper for source events we don't recognize at all.
    Always preserves `raw` verbatim so the source serializer can
    round-trip without losing data."""

    type: Literal["opaque"] = "opaque"
    original_type: str = ""


# ------------------------------------------------------------------ #
# Discriminated union                                                  #
# ------------------------------------------------------------------ #


Event = Annotated[
    Union[
        SessionStart,
        SessionEnd,
        TurnStart,
        TurnEnd,
        UserMessage,
        AssistantMessage,
        AssistantReasoning,
        ToolCall,
        ToolResult,
        TokenUsage,
        FileEdit,
        Operator,
        Attachment,
        Lifecycle,
        OpaqueEvent,
    ],
    Field(discriminator="type"),
]


# Convenience for consumers that want to hold a list of mixed events
# without writing the union out every time.
EventList = list[
    Union[
        SessionStart,
        SessionEnd,
        TurnStart,
        TurnEnd,
        UserMessage,
        AssistantMessage,
        AssistantReasoning,
        ToolCall,
        ToolResult,
        TokenUsage,
        FileEdit,
        Operator,
        Attachment,
        Lifecycle,
        OpaqueEvent,
    ]
]
