"""ClaudeDesktopSource — Claude Desktop local-agent transcript files.

Claude Desktop/Cowork local-agent sessions live under macOS app data, with a
per-session working directory that contains an embedded Claude Code transcript:

  ~/Library/Application Support/Claude/local-agent-mode-sessions/
    .../local_<uuid>/.claude/projects/**/*.jsonl

Those nested JSONL files use the same shape as normal Claude Code transcripts,
so parsing/serialization can reuse `ClaudeSource`; this source only changes
where discovery looks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .base import _walk_glob
from .claude import ClaudeSource


class ClaudeDesktopSource(ClaudeSource):
    """Claude Desktop local-agent transcripts embedded in app support data."""

    name = "claude-desktop"

    @property
    def root(self) -> Path:
        for root in self.roots:
            if root.is_dir():
                return root
        return self.roots[0]

    @property
    def roots(self) -> list[Path]:
        """Known Claude Desktop local-agent roots.

        `Claude-3p` is used by Anthropic's 3P distribution. Most machines only
        have the normal `Claude` root, but scanning both keeps discovery aligned
        with Anthropic's documented layouts.
        """
        app_support = self._home / "Library" / "Application Support"
        return [
            app_support / "Claude" / "local-agent-mode-sessions",
            app_support / "Claude-3p" / "local-agent-mode-sessions",
        ]

    @property
    def watch_roots(self) -> list[Path]:
        return self.roots

    def is_present(self) -> bool:
        return any(root.is_dir() for root in self.roots)

    def iter_files(self) -> Iterator[Path]:
        for root in self.roots:
            yield from _walk_glob(
                root,
                "**/local_*/.claude/projects/**/*.jsonl",
                self.exclude_patterns,
            )
