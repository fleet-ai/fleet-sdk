"""Merkle tree for efficient sync state comparison.

The "tree" is a flat {relative_path: sha256} map.
Root hash = sha256(canonical JSON of sorted map).

Hash cache in SQLite avoids re-reading unchanged files.
Cache key: (path, mtime, size) — if both match, reuse cached sha256.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .sources import iter_source_files, relative_to_home

TRACK_DIR = Path.home() / ".fleet" / "track"
STATE_DB = TRACK_DIR / "state.db"


def _db() -> sqlite3.Connection:
    TRACK_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STATE_DB, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_hashes (
            path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            last_seen INTEGER NOT NULL
        )
    """)
    conn.commit()
    return conn


def _sha256_file(path: Path) -> Optional[str]:
    """SHA256 of file content. Reads only complete bytes — safe for active JSONL files."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class HashCache:
    """SQLite-backed cache mapping path → (mtime, size, sha256)."""

    def __init__(self) -> None:
        self._conn = _db()

    def get_or_compute(self, path: Path) -> Optional[str]:
        """Return sha256 for path, using cache if mtime+size match."""
        rel = relative_to_home(path)
        try:
            stat = path.stat()
        except OSError:
            return None

        mtime, size = stat.st_mtime, stat.st_size

        row = self._conn.execute(
            "SELECT mtime, size, sha256 FROM file_hashes WHERE path = ?", (rel,)
        ).fetchone()

        if row and abs(row[0] - mtime) < 0.001 and row[1] == size:
            # Cache hit — stat matches, no need to read file
            self._conn.execute(
                "UPDATE file_hashes SET last_seen = ? WHERE path = ?",
                (int(time.time()), rel),
            )
            self._conn.commit()
            return row[2]

        # Cache miss — read and hash the file
        digest = _sha256_file(path)
        if digest is None:
            return None

        self._conn.execute(
            """
            INSERT OR REPLACE INTO file_hashes (path, mtime, size, sha256, last_seen)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rel, mtime, size, digest, int(time.time())),
        )
        self._conn.commit()
        return digest

    def invalidate(self, path: Path) -> None:
        rel = relative_to_home(path)
        self._conn.execute("DELETE FROM file_hashes WHERE path = ?", (rel,))
        self._conn.commit()

    def get_stored_digest(self, rel_path: str) -> Optional[str]:
        """Return the cached sha256 for a relative path, or None if not cached."""
        row = self._conn.execute(
            "SELECT sha256 FROM file_hashes WHERE path = ?", (rel_path,)
        ).fetchone()
        return row[0] if row else None

    def all_hashes(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT path, sha256 FROM file_hashes").fetchall()
        return {row[0]: row[1] for row in rows}

    def close(self) -> None:
        self._conn.close()


class MerkleTree:
    """Builds a Merkle root from the local file set."""

    def __init__(self, cache: HashCache) -> None:
        self._cache = cache

    def build(self) -> tuple[dict[str, str], str]:
        """
        Walk all source files, compute hashes via cache.
        Returns (flat_map, root_hash).
        root_hash = sha256 of canonical JSON of sorted {path: sha256} map.
        """
        file_map: dict[str, str] = {}
        for path in iter_source_files():
            digest = self._cache.get_or_compute(path)
            if digest:
                file_map[relative_to_home(path)] = digest

        root = self._compute_root(file_map)
        return file_map, root

    def diff(
        self,
        local_map: dict[str, str],
        remote_map: dict[str, str],
    ) -> list[str]:
        """
        Return relative paths that differ between local and remote.
        Includes new files (in local, not remote) and changed files.
        """
        changed = []
        for path, local_hash in local_map.items():
            if remote_map.get(path) != local_hash:
                changed.append(path)
        return changed

    @staticmethod
    def _compute_root(file_map: dict[str, str]) -> str:
        canonical = json.dumps(dict(sorted(file_map.items())), separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def compute_root(file_map: dict[str, str]) -> str:
        return MerkleTree._compute_root(file_map)
