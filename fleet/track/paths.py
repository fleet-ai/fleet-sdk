"""Filesystem layout for the track daemon.

All on-disk paths flow through a `TrackPaths` instance. Production code
calls `TrackPaths.default()`; tests pass `TrackPaths.under(tmp_path)` so
no test ever touches the real `~/.fleet/track`.

Why a dataclass instead of module globals: every module that reads
`Path.home()` at import time forces tests to monkeypatch before import,
which fights pytest's collection order and prevents parallel test runs
that would otherwise share the same `~/.fleet/track`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TrackPaths:
    """All on-disk locations the daemon reads or writes."""

    home: Path
    track_dir: Path
    state_db: Path
    status_file: Path
    pid_file: Path
    log_file: Path
    config_file: Path
    credentials_file: Path

    @classmethod
    def default(cls) -> "TrackPaths":
        """Production layout under the real `$HOME`."""
        return cls.under(Path.home())

    @classmethod
    def under(cls, home: Path) -> "TrackPaths":
        """Same layout rooted at an arbitrary directory.

        Used by tests with `pytest.tmp_path`. The directories are *not*
        created here — callers create them lazily, matching today's
        behavior where `TRACK_DIR.mkdir(...)` happens at write time.
        """
        track_dir = home / ".fleet" / "track"
        return cls(
            home=home,
            track_dir=track_dir,
            state_db=track_dir / "state.db",
            status_file=track_dir / "status.json",
            pid_file=track_dir / "daemon.pid",
            log_file=track_dir / "daemon.log",
            config_file=track_dir / "config.json",
            credentials_file=home / ".fleet" / "credentials.json",
        )

    def ensure_track_dir(self) -> None:
        """Create `track_dir` if it doesn't exist. Idempotent."""
        self.track_dir.mkdir(parents=True, exist_ok=True)
