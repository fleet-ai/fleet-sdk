"""Sources package.

Public surface:
    Source                 — abstract base class
    SourceSummary          — reportable view of one source
    ClaudeSource, CursorSource, CodexSource — concrete impls
    default_sources(home)  — list of standard sources for a given home
    relative_to_home       — shared util

Backward-compat (will be removed once consumers migrate):
    iter_source_files()    — flat iterator over default_sources()
    source_summary()       — dict view across default_sources()
    detect_sources()       — list of Source instances
    EXCLUDE_PATTERNS, WATCH_ROOTS
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Optional

from .base import (
    DEFAULT_EXCLUDE_PATTERNS,
    Source,
    SourceSummary,
    relative_to_home,
)
from .claude import ClaudeSource
from .codex import CodexSource
from .cursor import CursorSource

__all__ = [
    "Source",
    "SourceSummary",
    "ClaudeSource",
    "CursorSource",
    "CodexSource",
    "default_sources",
    "relative_to_home",
    # Backward-compat:
    "iter_source_files",
    "source_summary",
    "detect_sources",
    "EXCLUDE_PATTERNS",
    "WATCH_ROOTS",
]


def default_sources(home: Optional[Path] = None) -> list[Source]:
    """The standard set of sources we sync from. Tests pass a tmp home."""
    # CursorSource remains importable, but it is not in the default sync set
    # until we have stable metadata extraction and event parsing for resume.
    return [
        ClaudeSource(home=home),
        CodexSource(home=home),
    ]


# ------------------------------------------------------------------ #
# Backward-compat module-level shims                                   #
# ------------------------------------------------------------------ #

EXCLUDE_PATTERNS = DEFAULT_EXCLUDE_PATTERNS

# Computed lazily via a function so tests don't anchor on import-time
# Path.home(); but exposed as a module attribute for legacy callers.
WATCH_ROOTS = [
    Path.home() / ".claude" / "projects",
    Path.home() / ".codex",
]


def iter_source_files() -> Iterator[Path]:
    """Yield every file every default source wants to sync."""
    for source in default_sources():
        yield from source.iter_files()


def source_summary() -> dict[str, dict]:
    """Return per-agent summary as the legacy dict shape used by status.json."""
    out: dict[str, dict] = {}
    for source in default_sources():
        s = source.summary()
        out[s.name] = {"found": s.found, "files": s.files}
    return out


def detect_sources() -> list[Source]:
    """Return the default source list. Callers can ask `is_present()`."""
    return default_sources()
