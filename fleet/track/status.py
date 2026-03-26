"""PID file and status.json management.

status.json is the IPC primitive between the daemon, CLI, and menubar app.
Written atomically (write-to-tmp then rename) to avoid partial reads.
"""

from __future__ import annotations

import json
import os
import time
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

TRACK_DIR = Path.home() / ".fleet" / "track"
STATUS_FILE = TRACK_DIR / "status.json"
PID_FILE = TRACK_DIR / "daemon.pid"


@dataclass
class TrackStatus:
    pid: int = 0
    state: str = "idle"          # idle | syncing | error
    last_sync: Optional[str] = None
    queue_depth: int = 0
    files_total: int = 0
    files_synced: int = 0
    bytes_uploaded_session: int = 0
    errors: list[str] = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    updated_at: str = ""


def write_pid() -> None:
    TRACK_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def clear_pid() -> None:
    PID_FILE.unlink(missing_ok=True)


def is_running() -> bool:
    """Return True if a daemon process is alive."""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 = existence check
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def write_status(status: TrackStatus) -> None:
    TRACK_DIR.mkdir(parents=True, exist_ok=True)
    status.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data = json.dumps(asdict(status), indent=2)

    # Atomic write: tmp file → rename
    fd, tmp = tempfile.mkstemp(dir=TRACK_DIR, prefix=".status-", suffix=".json")
    try:
        os.write(fd, data.encode())
        os.close(fd)
        fd = -1  # mark closed so the except block doesn't double-close
        os.replace(tmp, STATUS_FILE)
    except Exception:
        if fd != -1:
            os.close(fd)
        os.unlink(tmp)
        raise


def read_status() -> Optional[TrackStatus]:
    if not STATUS_FILE.exists():
        return None
    try:
        data = json.loads(STATUS_FILE.read_text())
        return TrackStatus(**data)
    except Exception:
        return None
