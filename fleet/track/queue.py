"""WAL-backed SQLite upload queue.

Survives daemon crashes. Items transition: pending → in_flight → done/failed.
Failed items are retried with exponential backoff.

All paths flow through `TrackPaths` so tests can target a tmp dir.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .paths import TrackPaths

log = logging.getLogger("fleet.track.queue")

MAX_ATTEMPTS = 10
BASE_BACKOFF_SECS = 0.5
MAX_BACKOFF_SECS = 1800  # 30 min


def _backoff(attempts: int) -> float:
    return min(BASE_BACKOFF_SECS * (2 ** attempts), MAX_BACKOFF_SECS)


@dataclass
class QueueItem:
    path: str        # relative to $HOME
    sha256: str
    attempts: int
    last_error: Optional[str]


class UploadQueue:
    def __init__(self, paths: Optional[TrackPaths] = None) -> None:
        self._paths = paths or TrackPaths.default()
        self._paths.ensure_track_dir()
        self._lock = threading.Lock()
        self._conn = self._open_conn()

    def _open_conn(self, _retry: bool = False) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self._paths.state_db, timeout=10, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queue (
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    last_error TEXT,
                    next_attempt_at INTEGER NOT NULL DEFAULT 0,
                    enqueued_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(path, sha256)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS queue_status ON queue(status, next_attempt_at)")
            conn.commit()

            result = conn.execute("PRAGMA integrity_check").fetchone()
            if result[0] != "ok":
                raise sqlite3.DatabaseError(f"integrity_check returned: {result[0]}")
            return conn
        except sqlite3.DatabaseError:
            # Either the file isn't a sqlite db, the schema is damaged, or
            # integrity_check failed. One retry after wiping; re-raise on the
            # second attempt so we don't loop forever on a parent-dir issue.
            if _retry:
                raise
            try:
                conn.close()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            self._wipe_and_reinit()
            return self._open_conn(_retry=True)

    def _wipe_and_reinit(self) -> None:
        """Delete corrupt database files and start fresh. Queue items are lost but
        the next reconcile will re-enqueue anything not yet on S3."""
        log.warning("queue database is corrupt — wiping and reinitialising (next reconcile will re-upload missing files)")
        for suffix in ("", "-shm", "-wal"):
            p = Path(str(self._paths.state_db) + suffix)
            if p.exists():
                p.unlink(missing_ok=True)

    def enqueue(self, path: str, sha256: str) -> None:
        """Add path to the queue. Idempotent: same (path, sha256) is a no-op."""
        now = int(time.time())
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO queue (path, sha256, status, next_attempt_at, enqueued_at, updated_at)
                VALUES (?, ?, 'pending', 0, ?, ?)
                """,
                (path, sha256, now, now),
            )
            self._conn.commit()

    def enqueue_batch(self, items: list[tuple[str, str]]) -> None:
        now = int(time.time())
        with self._lock:
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO queue (path, sha256, status, next_attempt_at, enqueued_at, updated_at)
                VALUES (?, ?, 'pending', 0, ?, ?)
                """,
                [(path, sha256, now, now) for path, sha256 in items],
            )
            self._conn.commit()

    def claim_batch(self, n: int = 16) -> list[QueueItem]:
        """Atomically claim up to n pending items for upload."""
        now = int(time.time())
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT path, sha256, attempts, last_error FROM queue
                WHERE status = 'pending' AND next_attempt_at <= ?
                ORDER BY enqueued_at ASC
                LIMIT ?
                """,
                (now, n),
            ).fetchall()

            if not rows:
                return []

            # Match on (path, sha256) — the natural key — so we never transition a
            # row that wasn't in the SELECT result. Two rows can share a path with
            # different sha256 values; path-only matching would orphan the extra row
            # (set to in_flight with no upload attempted and no callback to resolve it).
            placeholders = ",".join("(?,?)" for _ in rows)
            pairs = [v for r in rows for v in (r[0], r[1])]
            self._conn.execute(
                f"UPDATE queue SET status = 'in_flight', updated_at = ? WHERE status = 'pending' AND (path, sha256) IN ({placeholders})",
                [now] + pairs,
            )
            self._conn.commit()

        return [QueueItem(r[0], r[1], r[2], r[3]) for r in rows]

    def mark_done(self, path: str, sha256: str) -> None:
        now = int(time.time())
        with self._lock:
            self._conn.execute(
                "UPDATE queue SET status = 'done', updated_at = ? WHERE path = ? AND sha256 = ?",
                (now, path, sha256),
            )
            # Prune rows for the same path that were enqueued *strictly before*
            # this one — they are older versions superseded by this upload.
            # Strict `<` matters: enqueued_at is second-resolution, so two
            # versions enqueued the same second would otherwise prune each
            # other. When timestamps tie we err toward keeping data; the next
            # upload pass will resolve the duplicate.
            self._conn.execute(
                """
                DELETE FROM queue
                WHERE path = ? AND sha256 != ? AND status IN ('failed', 'pending')
                  AND enqueued_at < (
                      SELECT enqueued_at FROM queue WHERE path = ? AND sha256 = ?
                  )
                """,
                (path, sha256, path, sha256),
            )
            self._conn.commit()

    def mark_failed(self, path: str, sha256: str, error: str) -> None:
        now = int(time.time())
        with self._lock:
            row = self._conn.execute(
                "SELECT attempts FROM queue WHERE path = ? AND sha256 = ?", (path, sha256)
            ).fetchone()
            attempts = (row[0] if row else 0) + 1
            status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
            next_attempt = now + int(_backoff(attempts))
            self._conn.execute(
                """
                UPDATE queue
                SET status = ?, attempts = ?, last_error = ?, next_attempt_at = ?, updated_at = ?
                WHERE path = ? AND sha256 = ?
                """,
                (status, attempts, error[:500], next_attempt, now, path, sha256),
            )
            self._conn.commit()

    def reset_failed(self) -> int:
        """Re-queue permanently failed items (used by reconciliation loop)."""
        now = int(time.time())
        with self._lock:
            cur = self._conn.execute(
                "UPDATE queue SET status = 'pending', attempts = 0, next_attempt_at = 0, updated_at = ? WHERE status = 'failed'",
                (now,),
            )
            self._conn.commit()
        return cur.rowcount

    def remove_done(self) -> None:
        """Purge successfully uploaded items older than 24h."""
        cutoff = int(time.time()) - 86400
        with self._lock:
            self._conn.execute("DELETE FROM queue WHERE status = 'done' AND updated_at < ?", (cutoff,))
            self._conn.commit()

    def stats(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM queue GROUP BY status"
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    def oldest_pending_age(self) -> Optional[int]:
        """Return seconds since the oldest pending/in-flight item was enqueued, or None if empty.

        Used by `flt track doctor` to detect a wedged uploader.
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT MIN(enqueued_at) FROM queue
                WHERE status IN ('pending', 'in_flight')
                """
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(time.time()) - int(row[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()
