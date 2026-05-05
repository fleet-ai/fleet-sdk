"""CursorSource — `~/.cursor/projects/**/agent-transcripts/**/*.{jsonl,txt}`."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .base import Source, _walk_glob


class CursorSource(Source):
    name = "cursor"

    @property
    def root(self) -> Path:
        return self._home / ".cursor" / "projects"

    def iter_files(self) -> Iterator[Path]:
        # Cursor sessions live in two extensions side-by-side. Earlier
        # implementations split this across two pseudo-sources ("cursor"
        # and "cursor_txt") so the flat list could express it; the class
        # form simply yields both in one stream.
        yield from _walk_glob(
            self.root, "**/agent-transcripts/**/*.jsonl", self.exclude_patterns
        )
        yield from _walk_glob(
            self.root, "**/agent-transcripts/**/*.txt", self.exclude_patterns
        )

    def read_for_upload(self, path: Path) -> bytes | None:
        try:
            data = path.read_bytes()
        except OSError:
            return None

        # JSONL trim only applies to .jsonl files; .txt is human-flat,
        # uploaded as-is.
        if path.suffix == ".jsonl" and data and not data.endswith(b"\n"):
            last_nl = data.rfind(b"\n")
            if last_nl > 0:
                data = data[: last_nl + 1]
        return data
