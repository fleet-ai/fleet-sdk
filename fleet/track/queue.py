"""WAL-backed SQLite upload queue.

Survives daemon crashes. Items transition: pending → in_flight → done/failed.
Failed items are retried with exponential backoff.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .merkle import STATE_DB, TRACK_DIR

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
    def __init__(self) -> None:
        TRACK_DIR.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(STATE_DB, timeout=10, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("""
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
        self._conn.execute("CREATE INDEX IF NOT EXISTS queue_status ON queue(status, next_attempt_at)")
        self._conn.commit()

    def enqueue(self, path: str, sha256: str) -> None:
        """Add path to the queue. Idempotent: same (path, sha256) is a no-op."""
        now = int(time.time())
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

        paths = [r[0] for r in rows]
        self._conn.execute(
            f"UPDATE queue SET status = 'in_flight', updated_at = ? WHERE status = 'pending' AND path IN ({','.join('?' * len(paths))})",
            [now] + paths,
        )
        self._conn.commit()

        return [QueueItem(r[0], r[1], r[2], r[3]) for r in rows]

    def mark_done(self, path: str) -> None:
        now = int(time.time())
        self._conn.execute(
            "UPDATE queue SET status = 'done', updated_at = ? WHERE path = ?",
            (now, path),
        )
        self._conn.commit()

    def mark_failed(self, path: str, error: str) -> None:
        now = int(time.time())
        row = self._conn.execute(
            "SELECT attempts FROM queue WHERE path = ?", (path,)
        ).fetchone()
        attempts = (row[0] if row else 0) + 1
        status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
        next_attempt = now + int(_backoff(attempts))
        self._conn.execute(
            """
            UPDATE queue
            SET status = ?, attempts = ?, last_error = ?, next_attempt_at = ?, updated_at = ?
            WHERE path = ?
            """,
            (status, attempts, error[:500], next_attempt, now, path),
        )
        self._conn.commit()

    def reset_failed(self) -> int:
        """Re-queue permanently failed items (used by reconciliation loop)."""
        now = int(time.time())
        cur = self._conn.execute(
            "UPDATE queue SET status = 'pending', attempts = 0, next_attempt_at = 0, updated_at = ? WHERE status = 'failed'",
            (now,),
        )
        self._conn.commit()
        return cur.rowcount

    def remove_done(self) -> None:
        """Purge successfully uploaded items older than 24h."""
        cutoff = int(time.time()) - 86400
        self._conn.execute("DELETE FROM queue WHERE status = 'done' AND updated_at < ?", (cutoff,))
        self._conn.commit()

    def stats(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) FROM queue GROUP BY status"
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    def close(self) -> None:
        self._conn.close()
