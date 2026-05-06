"""Local FleetTrack upload blocklist.

Users may keep local sessions that should never be submitted to Fleet. The
blocklist is stored in `~/.fleet/track/config.json` alongside the device id so
it applies before upload URL requests, metadata indexing, or manifest writes.
"""

from __future__ import annotations

import fnmatch
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import TrackPaths

log = logging.getLogger("fleet.track.blocklist")

BLOCKED_SESSION_IDS_KEY = "blocked_session_ids"
BLOCKED_PATHS_KEY = "blocked_paths"
BLOCKED_PATH_GLOBS_KEY = "blocked_path_globs"


@dataclass(frozen=True)
class TrackBlocklist:
    """In-memory view of locally blocked session ids and paths."""

    session_ids: frozenset[str] = frozenset()
    paths: frozenset[str] = frozenset()
    path_globs: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> "TrackBlocklist":
        return cls()

    @classmethod
    def from_paths(cls, paths: TrackPaths) -> "TrackBlocklist":
        return cls.from_config(read_track_config(paths))

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "TrackBlocklist":
        return cls(
            session_ids=frozenset(_clean_strs(config.get(BLOCKED_SESSION_IDS_KEY))),
            paths=frozenset(
                _normalize_rel_path(p)
                for p in _clean_strs(config.get(BLOCKED_PATHS_KEY))
            ),
            path_globs=tuple(_clean_strs(config.get(BLOCKED_PATH_GLOBS_KEY))),
        )

    def is_empty(self) -> bool:
        return not self.session_ids and not self.paths and not self.path_globs

    def is_blocked_path(self, rel_path: str) -> bool:
        rel_path = _normalize_rel_path(rel_path)
        if rel_path in self.paths:
            return True
        if any(fnmatch.fnmatch(rel_path, pattern) for pattern in self.path_globs):
            return True
        if not self.session_ids:
            return False
        stem = Path(rel_path).stem
        for session_id in self.session_ids:
            if stem == session_id or stem.endswith(session_id):
                return True
            if f"/{session_id}.jsonl" in rel_path or f"/{session_id}.txt" in rel_path:
                return True
        return False


def read_track_config(paths: TrackPaths) -> dict[str, Any]:
    try:
        raw = paths.config_file.read_text()
    except FileNotFoundError:
        return {}
    except OSError as e:
        log.warning("failed to read track config %s: %s", paths.config_file, e)
        return {}
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("failed to parse track config %s: %s", paths.config_file, e)
        return {}
    return config if isinstance(config, dict) else {}


def write_track_config(paths: TrackPaths, config: dict[str, Any]) -> None:
    paths.ensure_track_dir()
    paths.config_file.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")


def add_blocked_session_ids(paths: TrackPaths, session_ids: Iterable[str]) -> list[str]:
    config = read_track_config(paths)
    existing = set(_clean_strs(config.get(BLOCKED_SESSION_IDS_KEY)))
    added: list[str] = []
    for session_id in _clean_strs(session_ids):
        if session_id not in existing:
            existing.add(session_id)
            added.append(session_id)
    config[BLOCKED_SESSION_IDS_KEY] = sorted(existing)
    write_track_config(paths, config)
    return added


def remove_blocked_session_ids(
    paths: TrackPaths, session_ids: Iterable[str]
) -> list[str]:
    config = read_track_config(paths)
    existing = set(_clean_strs(config.get(BLOCKED_SESSION_IDS_KEY)))
    removed: list[str] = []
    for session_id in _clean_strs(session_ids):
        if session_id in existing:
            existing.remove(session_id)
            removed.append(session_id)
    if existing:
        config[BLOCKED_SESSION_IDS_KEY] = sorted(existing)
    else:
        config.pop(BLOCKED_SESSION_IDS_KEY, None)
    write_track_config(paths, config)
    return removed


def _clean_strs(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Iterable):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if item:
            out.append(item)
    return out


def _normalize_rel_path(path: str) -> str:
    return path.strip().lstrip("/").replace("\\", "/")
