"""PID file and status.json management.

status.json is the IPC primitive between the daemon, CLI, and menubar.
Written atomically (write-to-tmp then rename) to avoid partial reads.

All paths flow through `TrackPaths` so tests can target a tmp dir.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from .paths import TrackPaths

STATUS_SCHEMA_VERSION = 1


@dataclass
class TrackStatus:
    pid: int = 0
    state: str = "idle"  # idle | syncing | error
    last_sync: Optional[str] = None
    queue_depth: int = 0
    files_total: int = 0
    files_synced: int = 0
    bytes_uploaded_session: int = 0
    errors: list[str] = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    updated_at: str = ""
    schema_version: int = STATUS_SCHEMA_VERSION


def write_pid(paths: TrackPaths) -> None:
    paths.ensure_track_dir()
    paths.pid_file.write_text(str(os.getpid()))


def clear_pid(paths: TrackPaths) -> None:
    try:
        pid = int(paths.pid_file.read_text().strip())
    except FileNotFoundError:
        return
    except ValueError:
        return
    if pid == os.getpid():
        paths.pid_file.unlink(missing_ok=True)


def is_running(paths: TrackPaths) -> bool:
    """Return True if a daemon process is alive."""
    if not paths.pid_file.exists():
        return False
    try:
        pid = int(paths.pid_file.read_text().strip())
        os.kill(pid, 0)  # signal 0 = existence check
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def write_status(paths: TrackPaths, status: TrackStatus) -> None:
    paths.ensure_track_dir()
    status.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data = json.dumps(asdict(status), indent=2)

    # Atomic write: tmp file in same dir → rename.
    fd, tmp = tempfile.mkstemp(dir=paths.track_dir, prefix=".status-", suffix=".json")
    try:
        os.write(fd, data.encode())
        os.close(fd)
        fd = -1  # mark closed so the except block doesn't double-close
        os.replace(tmp, paths.status_file)
    except Exception:
        if fd != -1:
            os.close(fd)
        os.unlink(tmp)
        raise


def read_status(paths: TrackPaths) -> Optional[TrackStatus]:
    if not paths.status_file.exists():
        return None
    try:
        data = json.loads(paths.status_file.read_text())
        # Ignore unknown fields so a daemon written by a newer schema
        # version doesn't crash an older CLI.
        known = {f.name for f in TrackStatus.__dataclass_fields__.values()}
        return TrackStatus(**{k: v for k, v in data.items() if k in known})
    except Exception:
        return None
