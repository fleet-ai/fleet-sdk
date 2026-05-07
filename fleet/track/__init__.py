"""Fleet track — passive AI session sidecar.

This package handles three things:

  1. **Sync** local AI session files (claude, codex)
     to a backing store (LocalSessionStore locally; RemoteSessionStore
     against orchestrator).
  2. **Convert** between session formats via a unified Event model so
     a session written by one CLI can be resumed in another.
  3. **Resume** sessions — same-tool native when the file exists locally,
     or via a Fleet checkout when conversion/materialization is needed.

The public surface below is what consumers should import. Internals
(parsers, daemon plumbing, CLI commands) live in submodules and aren't
re-exported here.
"""

from __future__ import annotations

from .api import TrackSessionSearchRequest, TrackTextMatch

# --- Unified event model + format conversion --- #
from .compactor import (
    Compactor,
    KNOWN_MODELS,
    TokenBudget,
    TruncationCompactor,
    TruncationConfig,
    budget_for,
    estimate_event_tokens,
    estimate_tokens,
)
from .converter import ConversionResult, convert
from .paths import TrackPaths
from .resumer import (
    SUPPORTED_TOOLS,
    CheckoutInfo,
    gc_checkouts,
    resume_session,
)

# --- Session store + chained view --- #
from .sources import (
    ClaudeDesktopSource,
    ClaudeSource,
    CodexSource,
    CursorSource,
    Source,
    SourceSummary,
    default_sources,
)
from .store import (
    ChainedSessionStore,
    LocalSessionStore,
    NativeFilesSessionStore,
    RemoteSessionStore,
    Session,
    SessionStore,
)
from .unified import (
    AssistantMessage,
    AssistantReasoning,
    Attachment,
    Event,
    FileEdit,
    Lifecycle,
    OpaqueEvent,
    Operator,
    SessionEnd,
    SessionStart,
    TokenUsage,
    ToolCall,
    ToolResult,
    ToolSpec,
    TurnEnd,
    TurnStart,
    UserMessage,
)

__all__ = [
    # Paths
    "TrackPaths",
    "TrackSessionSearchRequest",
    "TrackTextMatch",
    # Unified format
    "Event",
    "SessionStart",
    "SessionEnd",
    "TurnStart",
    "TurnEnd",
    "UserMessage",
    "AssistantMessage",
    "AssistantReasoning",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "TokenUsage",
    "FileEdit",
    "Operator",
    "Attachment",
    "Lifecycle",
    "OpaqueEvent",
    # Sources
    "Source",
    "SourceSummary",
    "ClaudeSource",
    "ClaudeDesktopSource",
    "CodexSource",
    "CursorSource",
    "default_sources",
    # Sessions
    "Session",
    "SessionStore",
    "LocalSessionStore",
    "NativeFilesSessionStore",
    "RemoteSessionStore",
    "ChainedSessionStore",
    # Compaction
    "Compactor",
    "TruncationCompactor",
    "TruncationConfig",
    "TokenBudget",
    "KNOWN_MODELS",
    "budget_for",
    "estimate_tokens",
    "estimate_event_tokens",
    # Resume + conversion
    "resume_session",
    "CheckoutInfo",
    "SUPPORTED_TOOLS",
    "convert",
    "ConversionResult",
    "gc_checkouts",
]
