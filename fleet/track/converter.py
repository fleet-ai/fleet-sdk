"""Cross-format conversion glue.

The Source classes' `parse()` and `serialize()` are pure per-event
operations. Cross-format conversion needs *session-level* context
(session id, cwd, model) to be threaded through every synthesized row
so the target CLI's resume flow can find the file. This module owns
that threading.

Typical usage:

    from fleet.track.sources import ClaudeSource, CodexSource
    from fleet.track.converter import convert

    out_bytes, meta = convert(
        from_source=CodexSource(),
        to_source=ClaudeSource(),
        in_path=Path("~/.codex/sessions/.../rollout-...jsonl").expanduser(),
    )
    # `meta` carries the new-side session id + the suggested file path
    # `claude --resume` can pick up.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .sources.base import Source
from .unified import Event, SessionStart

log = logging.getLogger("fleet.track.converter")


@dataclass(frozen=True)
class ConversionResult:
    """Output of a cross-format conversion.

    `bytes` is the serialized session file.
    `session_id` is the id baked into the synthesized rows — the
        source-side resume command uses this UUID/string to locate
        the session.
    `suggested_path` is the on-disk location the *target* CLI scans
        for resumeable sessions. Caller writes `bytes` to this path
        to make the converted session resumeable.
    """

    bytes: bytes
    session_id: str
    suggested_path: Path


def convert(
    *,
    from_source: Source,
    to_source: Source,
    in_path: Path,
    home: Optional[Path] = None,
    new_session_id: Optional[str] = None,
    target_cwd: Optional[str] = None,
) -> ConversionResult:
    """Convert a session file from one CLI's format into another's.

    `home` defaults to `Path.home()`. `target_cwd` defaults to the
    cwd recorded on the source session's first SessionStart event.
    `new_session_id` defaults to a fresh UUID4 — supply explicitly if
    you want determinism.
    """
    home = home or Path.home()
    new_session_id = new_session_id or str(uuid.uuid4())

    events = list(from_source.parse(in_path))
    cwd = target_cwd or _first_cwd(events) or "/tmp"
    # Resolve symlinks: macOS `/tmp` → `/private/tmp`. Both claude and
    # codex index sessions by the resolved path, so a converter that
    # leaves `/tmp` in the rows produces files claude/codex can't find.
    try:
        cwd = str(Path(cwd).resolve(strict=False))
    except (OSError, RuntimeError):
        pass
    version = _first_version(events) or "0.0.0-converted"
    git_branch = _first_git_branch(events) or ""

    # Annotate each event's raw with a `_synth` meta block so the
    # target serializer's cross-source synthesizer can read coherent
    # session-wide values out of every row.
    annotated = [_with_synth_meta(e, session_id=new_session_id,
                                  cwd=cwd, version=version,
                                  git_branch=git_branch)
                 for e in events]

    out_bytes = to_source.serialize(annotated)
    suggested = _suggested_path_for(to_source, home, new_session_id, cwd)
    return ConversionResult(
        bytes=out_bytes,
        session_id=new_session_id,
        suggested_path=suggested,
    )


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #


def _first_cwd(events: Iterable[Event]) -> Optional[str]:
    for e in events:
        if isinstance(e, SessionStart) and e.cwd:
            return e.cwd
        cwd = (e.raw or {}).get("cwd") if hasattr(e, "raw") else None
        if cwd:
            return str(cwd)
    return None


def _first_version(events: Iterable[Event]) -> Optional[str]:
    for e in events:
        v = getattr(e, "agent_version", None)
        if v:
            return str(v)
        v = (e.raw or {}).get("version") if hasattr(e, "raw") else None
        if v:
            return str(v)
    return None


def _first_git_branch(events: Iterable[Event]) -> Optional[str]:
    for e in events:
        v = getattr(e, "git_branch", None)
        if v:
            return str(v)
        v = (e.raw or {}).get("gitBranch") if hasattr(e, "raw") else None
        if v:
            return str(v)
    return None


def _with_synth_meta(ev: Event, **synth) -> Event:
    """Return a new event with `_synth` metadata embedded in `raw`.

    Pydantic frozen events are immutable; we use model_copy with a
    deep-merged raw dict.
    """
    raw = dict(ev.raw) if ev.raw else {}
    raw["_synth"] = dict(synth)
    return ev.model_copy(update={"raw": raw})


def _encode_claude_cwd(cwd: str) -> str:
    """Convert `/Users/foo/.config` → `-Users-foo--config`.

    Replace any character that isn't alphanumeric, `-`, or `_` with `-`.
    Audited from production claude project directories.
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "-", cwd)


def _suggested_path_for(to_source: Source, home: Path, session_id: str, cwd: str) -> Path:
    """Where the converted file should live so the target CLI's resume command finds it."""
    name = to_source.name
    if name == "claude":
        return home / ".claude" / "projects" / _encode_claude_cwd(cwd) / f"{session_id}.jsonl"
    if name == "codex":
        # codex layout: ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl
        now = _dt.datetime.now(_dt.timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H-%M-%S")
        date_path = now.strftime("%Y/%m/%d")
        return home / ".codex" / "sessions" / date_path / f"rollout-{ts}-{session_id}.jsonl"
    raise ValueError(f"Unknown target source: {name}")
