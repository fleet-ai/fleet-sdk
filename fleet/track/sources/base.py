"""Source ABC.

A `Source` represents one AI tool whose session files we sync. Today the
file-shape (jsonl + a few extensions) is all the daemon cares about. Soon
each source will also implement `parse(path)` → events and
`serialize(events)` → bytes for the unified-format pipeline; those
methods raise `NotImplementedError` here and ship in the format PR.

Each concrete source is constructed with a `home: Path` so tests can
point at a fixture directory instead of the real `$HOME`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Iterable, Iterator, Optional


# Files we never sync, regardless of which source surfaced them.
# This is the *client*-side guard. The server enforces a strictly larger
# blocklist (see orchestrator/public_api/track.py); the client list is
# best-effort to skip uploads that the server would reject anyway.
DEFAULT_EXCLUDE_PATTERNS: frozenset[str] = frozenset({
    "session-env",          # Claude Code env vars
    "auth.json",            # Codex credentials
    "config.toml",          # Codex config
    "shell_snapshots",      # Codex shell env
})


@dataclass(frozen=True)
class SourceSummary:
    """Reportable view of one source — for `flt track sources` and status.json."""

    name: str
    found: bool
    files: int = 0
    bytes: int = 0
    newest_mtime: Optional[float] = None


def relative_to_home(path: Path, home: Optional[Path] = None) -> str:
    """Return ``path`` relative to ``home`` as a POSIX string.

    ``home`` defaults to ``Path.home()`` for production callers; tests pass a
    ``tmp_path`` so the merkle/queue/uploader code can reason about files
    under a fixture root without fighting the real filesystem.
    """
    return str(path.relative_to(home if home is not None else Path.home()))


class Source(ABC):
    """One AI tool's session-file directory and how to read it.

    Subclasses set `name` (used as the agent label in summaries and S3
    paths) and override `root` and `iter_files`. The default
    `read_for_upload` is fine for most cases; override for format-specific
    quirks (e.g. JSONL trailing-line trim).
    """

    name: ClassVar[str] = ""

    def __init__(self, home: Optional[Path] = None) -> None:
        self._home = home or Path.home()

    # ------------------------------------------------------------------ #
    # Filesystem layout                                                    #
    # ------------------------------------------------------------------ #

    @property
    @abstractmethod
    def root(self) -> Path:
        """The directory we recursively scan for session files."""

    @property
    def watch_roots(self) -> list[Path]:
        """Directories the FS watcher should monitor for this source.

        Defaults to `[self.root]` but overridable: e.g. CodexSource watches
        `~/.codex` so newly-created `sessions/` and `archived_sessions/`
        subdirs are picked up without restarting the daemon.
        """
        return [self.root]

    @property
    def exclude_patterns(self) -> frozenset[str]:
        """Path-fragment substrings to skip on this source. Defaults to the
        global set; subclasses extend if they have format-specific exclusions."""
        return DEFAULT_EXCLUDE_PATTERNS

    # ------------------------------------------------------------------ #
    # Discovery                                                            #
    # ------------------------------------------------------------------ #

    def is_present(self) -> bool:
        return self.root.is_dir()

    @abstractmethod
    def iter_files(self) -> Iterator[Path]:
        """Yield every file this source wants to sync. Must skip
        `exclude_patterns` and non-files."""

    def summary(self) -> SourceSummary:
        if not self.is_present():
            return SourceSummary(name=self.name, found=False)

        files = list(self.iter_files())
        if not files:
            return SourceSummary(name=self.name, found=True)

        total_bytes = 0
        newest = 0.0
        for f in files:
            try:
                st = f.stat()
                total_bytes += st.st_size
                if st.st_mtime > newest:
                    newest = st.st_mtime
            except OSError:
                continue
        return SourceSummary(
            name=self.name,
            found=True,
            files=len(files),
            bytes=total_bytes,
            newest_mtime=newest if newest > 0 else None,
        )

    # ------------------------------------------------------------------ #
    # Read for upload                                                      #
    # ------------------------------------------------------------------ #

    def read_for_upload(self, path: Path) -> Optional[bytes]:
        """Read bytes ready for upload. Returns None on read failure.

        Default: whole file. Override for format-specific quirks.
        """
        try:
            return path.read_bytes()
        except OSError:
            return None

    # ------------------------------------------------------------------ #
    # Unified-format conversion (Phase 0 in the format PR)                 #
    # ------------------------------------------------------------------ #

    def parse(self, path: Path) -> Iterable[Any]:
        """Parse a session file into the unified `Event` stream.

        Stub raising `NotImplementedError`; concrete impls land alongside
        `fleet/track/unified.py` in the format PR. Once implemented:
        - never raises on malformed input (unknown types → OpaqueEvent)
        - yields events ordered as they appear in the file
        """
        raise NotImplementedError(f"{self.name}.parse() not implemented yet")

    def serialize(self, events: Iterable[Any]) -> bytes:
        """Serialize a stream of unified `Event`s back into this source's native format.

        Stub raising `NotImplementedError`. Once implemented, must be
        round-trip robust: `serialize(parse(file))` produces a valid file
        the source can re-parse.
        """
        raise NotImplementedError(f"{self.name}.serialize() not implemented yet")


# ------------------------------------------------------------------ #
# Helpers shared by subclasses                                         #
# ------------------------------------------------------------------ #


def _walk_glob(root: Path, glob: str, exclude: frozenset[str]) -> Iterator[Path]:
    """Walk a glob, skipping non-files and any path containing an excluded
    fragment."""
    if not root.is_dir():
        return
    for path in root.glob(glob):
        if not path.is_file():
            continue
        if any(excl in path.parts for excl in exclude):
            continue
        yield path
