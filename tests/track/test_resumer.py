"""Resumer tests — checkout creation + GC.

Doesn't exec the actual claude/codex binaries; we test the
file-shape side-effects (which path the checkout lands at, what's
in the file, fork-lineage header) and call the GC logic directly.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from fleet.track.paths import TrackPaths
from fleet.track.resumer import (
    SUPPORTED_TOOLS,
    _checkout_path,
    _create_checkout,
    gc_checkouts,
)
from fleet.track.store import LocalSessionStore, Session
from fleet.track.unified import AssistantMessage, UserMessage


def _store(tmp_path: Path) -> LocalSessionStore:
    return LocalSessionStore(TrackPaths.under(tmp_path))


def _seed(store: LocalSessionStore, *, tool: str, id: str, n_events: int = 3,
          forked_from=None, fork_point=None, cwd="/private/tmp/r") -> Session:
    events = [UserMessage(source=tool, text=f"u{i}") for i in range(n_events)]
    s = Session(
        id=id, tool=tool, cwd=cwd,
        started_at="2026-04-30T00:00:00Z",
        last_active="2026-04-30T01:00:00Z",
        forked_from=forked_from,
        fork_point=fork_point,
    )
    return store.create(s, events)


# ------------------------------------------------------------------ #
# Checkout path layout                                                 #
# ------------------------------------------------------------------ #


def test_checkout_path_for_claude(tmp_path: Path):
    """Flat layout: claude requires checkouts directly under <encoded-cwd>/
    (its scanner doesn't recurse into subdirs)."""
    p = _checkout_path("claude", "/private/tmp/work", "abc-123", tmp_path)
    assert p == tmp_path / ".claude" / "projects" / "-private-tmp-work" / "abc-123.jsonl"


def test_checkout_path_for_codex(tmp_path: Path):
    """Codex's scanner is recursive; checkouts can sit alongside native rollouts."""
    p = _checkout_path("codex", "/private/tmp/work", "abc-123", tmp_path)
    parts = p.relative_to(tmp_path / ".codex" / "sessions").parts
    # YYYY/MM/DD/rollout-<ts>-abc-123.jsonl
    assert len(parts) == 4
    assert parts[3].startswith("rollout-")
    assert parts[3].endswith("-abc-123.jsonl")


def test_checkout_path_unknown_tool_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown target tool"):
        _checkout_path("opencode", "/x", "id", tmp_path)


# ------------------------------------------------------------------ #
# Checkout creation — claude target                                    #
# ------------------------------------------------------------------ #


def test_create_checkout_claude_writes_correct_path(tmp_path: Path):
    store = _store(tmp_path)
    s = _seed(store, tool="codex", id="src-1", cwd="/private/tmp/work")
    paths = TrackPaths.under(tmp_path)

    info = _create_checkout(store=store, session=s, target_tool="claude", paths=paths)

    assert info.target_tool == "claude"
    assert info.forked_from == "src-1"
    assert info.fork_point == 3
    assert info.path.exists()
    # Flat layout: directly in <encoded-cwd>/, not in a subdir.
    assert info.path.parent.name == "-private-tmp-work"
    assert info.path.parent.parent.name == "projects"


def test_create_checkout_claude_embeds_fleet_meta_header(tmp_path: Path):
    """First row of claude checkout should carry _fleet_meta so daemon
    knows it's a fork."""
    store = _store(tmp_path)
    s = _seed(store, tool="codex", id="src-meta", cwd="/private/tmp/work")
    paths = TrackPaths.under(tmp_path)

    info = _create_checkout(store=store, session=s, target_tool="claude", paths=paths)
    first_line = info.path.read_text().splitlines()[0]
    first = json.loads(first_line)

    assert "_fleet_meta" in first
    assert first["_fleet_meta"]["forked_from"] == "src-meta"
    assert first["_fleet_meta"]["target_tool"] == "claude"
    assert first["_fleet_meta"]["fork_point"] == 3


def test_create_checkout_claude_rows_carry_ephemeral_session_id(tmp_path: Path):
    """Every user/assistant row in the checkout must have sessionId
    matching the ephemeral id (so claude --resume <eph-id> finds them)."""
    store = _store(tmp_path)
    s = _seed(store, tool="codex", id="src-rows")
    paths = TrackPaths.under(tmp_path)

    info = _create_checkout(store=store, session=s, target_tool="claude", paths=paths)
    rows = [json.loads(l) for l in info.path.read_text().splitlines() if l.strip()]
    # Skip the header row (has _fleet_meta)
    body_rows = [r for r in rows if "_fleet_meta" not in r]
    msg_rows = [r for r in body_rows if r.get("type") in ("user", "assistant")]
    assert msg_rows, "expected at least one converted message row"
    for r in msg_rows:
        assert r.get("sessionId") == info.ephemeral_id


# ------------------------------------------------------------------ #
# Checkout creation — codex target                                     #
# ------------------------------------------------------------------ #


def test_create_checkout_codex_first_row_is_session_meta_with_meta(tmp_path: Path):
    """codex requires session_meta as the first row; we inject the
    fork meta INTO its payload (since we can't put a row above it)."""
    store = _store(tmp_path)
    s = _seed(store, tool="claude", id="src-cdx", cwd="/private/tmp/work")
    paths = TrackPaths.under(tmp_path)

    info = _create_checkout(store=store, session=s, target_tool="codex", paths=paths)
    first = json.loads(info.path.read_text().splitlines()[0])

    assert first["type"] == "session_meta"
    assert "_fleet_meta" in first["payload"]
    assert first["payload"]["_fleet_meta"]["forked_from"] == "src-cdx"
    assert first["payload"]["_fleet_meta"]["target_tool"] == "codex"


def test_create_checkout_codex_payload_has_required_fields(tmp_path: Path):
    """codex's deserializer rejects session_meta missing
    base_instructions={text:...} et al. Verify the required set."""
    store = _store(tmp_path)
    s = _seed(store, tool="claude", id="src-req", cwd="/private/tmp/work")
    paths = TrackPaths.under(tmp_path)

    info = _create_checkout(store=store, session=s, target_tool="codex", paths=paths)
    first = json.loads(info.path.read_text().splitlines()[0])
    payload = first["payload"]

    required = {"id", "timestamp", "cwd", "originator", "cli_version",
                "source", "model_provider", "base_instructions"}
    assert set(payload.keys()) >= required
    assert isinstance(payload["base_instructions"], dict)


# ------------------------------------------------------------------ #
# Branch / fork chain                                                  #
# ------------------------------------------------------------------ #


def test_checkout_includes_full_ancestor_chain(tmp_path: Path):
    """A checkout off a forked session should include events from the
    grandparent + parent + this session."""
    store = _store(tmp_path)
    _seed(store, tool="codex", id="A", n_events=5)
    _seed(store, tool="claude", id="B", n_events=2, forked_from="A", fork_point=3)
    paths = TrackPaths.under(tmp_path)

    s = store.get("B")
    assert s is not None
    info = _create_checkout(store=store, session=s, target_tool="codex", paths=paths)

    # Full chain: 3 from A + 2 from B = 5 input events.
    # In codex output: 1 session_meta + 5 message rows = 6 rows total.
    rows = [json.loads(l) for l in info.path.read_text().splitlines() if l.strip()]
    msg_rows = [r for r in rows if r.get("type") == "response_item"
                and r.get("payload", {}).get("type") == "message"]
    assert len(msg_rows) == 5
    # Texts come from A then B in chain order.
    texts = [r["payload"]["content"][0]["text"] for r in msg_rows]
    assert texts == ["u0", "u1", "u2", "u0", "u1"]


# ------------------------------------------------------------------ #
# CWD resolution                                                       #
# ------------------------------------------------------------------ #


def test_checkout_resolves_symlinked_cwd(tmp_path: Path):
    """If the session's cwd is `/tmp/x` on macOS, the checkout's path
    should reflect `/private/tmp/x` so claude finds it."""
    if not Path("/tmp").is_symlink():
        return  # Linux: nothing to verify
    store = _store(tmp_path)
    s = _seed(store, tool="codex", id="r1", cwd="/tmp/should-resolve")
    paths = TrackPaths.under(tmp_path)

    info = _create_checkout(store=store, session=s, target_tool="claude", paths=paths)
    assert "private" in str(info.path)


# ------------------------------------------------------------------ #
# GC                                                                   #
# ------------------------------------------------------------------ #


def _fleet_meta_row() -> str:
    return json.dumps({
        "_fleet_meta": {"forked_from": "x", "fork_point": 0,
                        "ephemeral_id": "e", "target_tool": "claude"},
        "type": "system",
        "content": "fleet-track checkout",
    })


def _native_row() -> str:
    return json.dumps({"type": "user", "uuid": "u1",
                       "message": {"role": "user", "content": "hi"}})


def test_gc_removes_old_marked_checkouts(tmp_path: Path):
    """Files with `_fleet_meta` older than the cutoff get removed."""
    cdir = tmp_path / ".claude" / "projects" / "-x"
    cdir.mkdir(parents=True)
    old = cdir / "old.jsonl"
    new = cdir / "new.jsonl"
    old.write_text(_fleet_meta_row() + "\n")
    new.write_text(_fleet_meta_row() + "\n")
    # Backdate `old`'s mtime by 30 hours.
    import os
    old_mtime = time.time() - 30 * 3600
    os.utime(old, (old_mtime, old_mtime))

    n = gc_checkouts(home=tmp_path, max_age_hours=24)
    assert n == 1
    assert not old.exists()
    assert new.exists()


def test_gc_no_op_when_no_checkouts(tmp_path: Path):
    assert gc_checkouts(home=tmp_path, max_age_hours=24) == 0


def test_gc_does_not_touch_native_sessions(tmp_path: Path):
    """A file without `_fleet_meta` is a native session and never deleted,
    even when older than the cutoff."""
    cdir = tmp_path / ".claude" / "projects" / "-x"
    cdir.mkdir(parents=True)
    native = cdir / "native.jsonl"
    native.write_text(_native_row() + "\n")
    import os
    old = time.time() - 100 * 3600  # 100 hours old
    os.utime(native, (old, old))

    n = gc_checkouts(home=tmp_path, max_age_hours=24)
    assert n == 0
    assert native.exists()  # untouched


def test_gc_recognizes_codex_session_meta_inner_marker(tmp_path: Path):
    """codex checkouts embed `_fleet_meta` inside session_meta.payload
    (since session_meta MUST be the first row); GC must find it there too."""
    cdir = tmp_path / ".codex" / "sessions" / "2026" / "05" / "01"
    cdir.mkdir(parents=True)
    f = cdir / "rollout-old-abc.jsonl"
    f.write_text(json.dumps({
        "timestamp": "x",
        "type": "session_meta",
        "payload": {
            "id": "abc",
            "_fleet_meta": {"forked_from": "src", "fork_point": 0,
                            "ephemeral_id": "abc", "target_tool": "codex"},
        },
    }) + "\n")
    import os
    old = time.time() - 30 * 3600
    os.utime(f, (old, old))

    n = gc_checkouts(home=tmp_path, max_age_hours=24)
    assert n == 1
    assert not f.exists()


# ------------------------------------------------------------------ #
# Tool registry                                                        #
# ------------------------------------------------------------------ #


def test_supported_tools_set():
    assert "claude" in SUPPORTED_TOOLS
    assert "codex" in SUPPORTED_TOOLS

