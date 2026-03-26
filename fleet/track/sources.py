"""Discover AI coding session source directories."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass
class Source:
    name: str
    root: Path
    glob: str  # relative glob pattern for files to sync
    found: bool


SOURCES = [
    Source("claude", Path.home() / ".claude" / "projects", "**/*.jsonl", False),
    Source("cursor", Path.home() / ".cursor" / "projects", "**/agent-transcripts/**/*.jsonl", False),
    Source("cursor_txt", Path.home() / ".cursor" / "projects", "**/agent-transcripts/**/*.txt", False),
    Source("codex", Path.home() / ".codex" / "sessions", "**/*.jsonl", False),
    Source("codex_archived", Path.home() / ".codex" / "archived_sessions", "**/*.jsonl", False),
]

# Directories to watch (for FSEvents/inotify)
WATCH_ROOTS = [
    Path.home() / ".claude" / "projects",
    Path.home() / ".cursor" / "projects",
    Path.home() / ".codex",
]

# Files/dirs to never sync
EXCLUDE_PATTERNS = {
    "session-env",          # Claude Code env vars
    "auth.json",            # Codex credentials
    "config.toml",          # Codex config
    "shell_snapshots",      # Codex shell env
}


def detect_sources() -> list[Source]:
    """Return which sources exist on this machine."""
    results = []
    seen_names: set[str] = set()
    for source in SOURCES:
        exists = source.root.is_dir()
        # Collapse cursor + cursor_txt into one "cursor" entry for display
        display_name = "cursor" if source.name.startswith("cursor") else source.name
        if display_name not in seen_names and exists:
            seen_names.add(display_name)
        results.append(Source(source.name, source.root, source.glob, exists))
    return results


def iter_source_files() -> Iterator[Path]:
    """Yield all files that should be synced across all sources."""
    for source in SOURCES:
        if not source.root.is_dir():
            continue
        for path in source.root.glob(source.glob):
            if not path.is_file():
                continue
            if any(excl in path.parts for excl in EXCLUDE_PATTERNS):
                continue
            yield path


def relative_to_home(path: Path) -> str:
    """Return path relative to $HOME as a POSIX string."""
    return str(path.relative_to(Path.home()))


def source_summary() -> dict[str, dict]:
    """Return per-agent discovery summary for status reporting."""
    counts: dict[str, int] = {}
    for path in iter_source_files():
        for source in SOURCES:
            if source.root.is_dir() and path.is_relative_to(source.root):
                agent = "cursor" if source.name.startswith("cursor") else source.name
                counts[agent] = counts.get(agent, 0) + 1
                break

    summary = {}
    displayed: set[str] = set()
    for source in SOURCES:
        agent = "cursor" if source.name.startswith("cursor") else source.name
        if agent not in displayed:
            displayed.add(agent)
            summary[agent] = {
                "found": source.root.is_dir(),
                "files": counts.get(agent, 0),
            }
    return summary
