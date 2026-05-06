"""Tests for NativeFilesSessionStore + ChainedSessionStore.

Both stores are read-only views; we exercise list / get / events and
the chained-lookup behavior including cross-store fork resolution.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet.track.paths import TrackPaths
from fleet.track.store import (
    ChainedSessionStore,
    LocalSessionStore,
    NativeFilesSessionStore,
    Session,
)
from fleet.track.unified import UserMessage


# ------------------------------------------------------------------ #
# Fixture helpers                                                      #
# ------------------------------------------------------------------ #


def _seed_native_claude(home: Path, *, sid: str, encoded_cwd: str = "-tmp-x") -> Path:
    base = home / ".claude" / "projects" / encoded_cwd
    base.mkdir(parents=True, exist_ok=True)
    f = base / f"{sid}.jsonl"
    rows = [
        # First row carries claude metadata so the parser synthesizes SessionStart.
        {
            "type": "user",
            "uuid": "u1",
            "sessionId": sid,
            "cwd": "/tmp/x",
            "gitBranch": "main",
            "version": "0.5",
            "timestamp": "2026-04-30T00:00:00Z",
            "message": {"role": "user", "content": "hi"},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u1",
            "timestamp": "2026-04-30T00:00:01Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "yo"}],
            },
        },
    ]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return f


def _seed_native_codex(home: Path, *, sid: str, cwd: str = "/tmp/y") -> Path:
    base = home / ".codex" / "sessions" / "2026" / "05" / "01"
    base.mkdir(parents=True, exist_ok=True)
    f = base / f"rollout-2026-05-01T00-00-00-{sid}.jsonl"
    rows = [
        {
            "timestamp": "2026-05-01T00:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": sid,
                "cwd": cwd,
                "cli_version": "0.5",
                "base_instructions": {"text": "you are codex"},
            },
        },
        {
            "timestamp": "2026-05-01T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "first"}],
            },
        },
    ]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return f


# ------------------------------------------------------------------ #
# NativeFilesSessionStore                                              #
# ------------------------------------------------------------------ #


def test_native_store_lists_claude_session_by_filename(tmp_path: Path):
    sid = "11111111-2222-3333-4444-555555555555"
    _seed_native_claude(tmp_path, sid=sid)
    store = NativeFilesSessionStore(home=tmp_path)
    sessions = store.list()
    assert len(sessions) == 1
    s = sessions[0]
    assert s.id == sid
    assert s.tool == "claude"
    assert s.event_count == 2  # 2 lines


def test_native_store_lists_codex_session_by_uuid_in_filename(tmp_path: Path):
    sid = "abcdef01-2345-6789-abcd-ef0123456789"
    _seed_native_codex(tmp_path, sid=sid, cwd="/tmp/cdx")
    store = NativeFilesSessionStore(home=tmp_path)
    sessions = store.list()
    s = next(x for x in sessions if x.tool == "codex")
    assert s.id == sid
    assert s.cwd == "/tmp/cdx"


def test_native_store_filters_by_tool(tmp_path: Path):
    _seed_native_claude(tmp_path, sid="11111111-1111-1111-1111-111111111111")
    _seed_native_codex(tmp_path, sid="22222222-2222-2222-2222-222222222222")
    store = NativeFilesSessionStore(home=tmp_path)
    assert {s.tool for s in store.list(tool="claude")} == {"claude"}
    assert {s.tool for s in store.list(tool="codex")} == {"codex"}


def test_native_store_skips_fleet_checkouts(tmp_path: Path):
    """Files marked with `_fleet_meta` are checkouts, not native sessions —
    the picker should skip them."""
    base = tmp_path / ".claude" / "projects" / "-tmp-x"
    base.mkdir(parents=True)
    sid = "11111111-1111-1111-1111-111111111111"
    f = base / f"{sid}.jsonl"
    rows = [
        {
            "_fleet_meta": {
                "forked_from": "src",
                "fork_point": 0,
                "ephemeral_id": sid,
                "target_tool": "claude",
            },
            "type": "system",
            "content": "fleet checkout",
        },
        {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "hi"}},
    ]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    store = NativeFilesSessionStore(home=tmp_path)
    assert store.list() == []


def test_native_store_skips_non_uuid_filenames(tmp_path: Path):
    """Claude can have files like `agent-abc.jsonl` (sub-agent traces) which
    don't follow the canonical session-id naming. Skip them."""
    base = tmp_path / ".claude" / "projects" / "-tmp-x"
    base.mkdir(parents=True)
    f = base / "agent-not-a-uuid.jsonl"
    f.write_text(
        json.dumps(
            {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "hi"}}
        )
        + "\n"
    )
    store = NativeFilesSessionStore(home=tmp_path)
    assert store.list() == []


def test_native_store_get_by_prefix(tmp_path: Path):
    _seed_native_claude(tmp_path, sid="abcdef01-2345-6789-abcd-ef0123456789")
    store = NativeFilesSessionStore(home=tmp_path)
    s = store.get("abcdef01")
    assert s is not None
    assert s.id == "abcdef01-2345-6789-abcd-ef0123456789"


def test_native_store_get_and_events_scan_past_default_first_page(tmp_path: Path):
    import os
    import time

    paths: list[Path] = []
    for i in range(60):
        sid = f"00000000-0000-0000-0000-{i:012d}"
        paths.append(_seed_native_claude(tmp_path, sid=sid, encoded_cwd=f"-tmp-{i}"))

    now = time.time()
    for i, path in enumerate(paths):
        timestamp = now - i
        os.utime(path, (timestamp, timestamp))

    target = "00000000-0000-0000-0000-000000000059"
    store = NativeFilesSessionStore(home=tmp_path)

    assert target not in {session.id for session in store.list()}
    session = store.get(target)
    assert session is not None
    assert session.id == target
    assert any(event.type == "user_message" for event in store.events(target))


def test_native_store_get_missing_returns_none(tmp_path: Path):
    store = NativeFilesSessionStore(home=tmp_path)
    assert store.get("nope") is None


def test_native_store_events_re_parses_file(tmp_path: Path):
    sid = "11111111-2222-3333-4444-555555555555"
    _seed_native_claude(tmp_path, sid=sid)
    store = NativeFilesSessionStore(home=tmp_path)
    events = list(store.events(sid))
    # Synthesized SessionStart + UserMessage + AssistantMessage = 3
    assert len(events) >= 2
    assert any(e.type == "user_message" for e in events)
    assert any(e.type == "assistant_message" for e in events)


def test_native_store_is_read_only(tmp_path: Path):
    store = NativeFilesSessionStore(home=tmp_path)
    s = Session(id="s", tool="claude")
    with pytest.raises(NotImplementedError):
        store.create(s, [])
    with pytest.raises(NotImplementedError):
        store.append("s", [])
    with pytest.raises(NotImplementedError):
        store.delete("s")


def test_native_store_list_recency_sorted(tmp_path: Path):
    """Most-recent-first sort is what the picker shows."""
    import time

    a = _seed_native_claude(
        tmp_path, sid="11111111-1111-1111-1111-111111111111", encoded_cwd="-tmp-a"
    )
    b = _seed_native_claude(
        tmp_path, sid="22222222-2222-2222-2222-222222222222", encoded_cwd="-tmp-b"
    )
    # Bump b's mtime forward.
    import os

    fresh = time.time()
    os.utime(b, (fresh, fresh))
    os.utime(a, (fresh - 3600, fresh - 3600))
    store = NativeFilesSessionStore(home=tmp_path)
    ids = [s.id for s in store.list()]
    assert ids == [
        "22222222-2222-2222-2222-222222222222",
        "11111111-1111-1111-1111-111111111111",
    ]


# ------------------------------------------------------------------ #
# ChainedSessionStore                                                  #
# ------------------------------------------------------------------ #


def test_chained_lists_union_deduped_by_id(tmp_path: Path):
    """Sessions present in both stores show up once; first store wins."""
    paths = TrackPaths.under(tmp_path)
    local = LocalSessionStore(paths)
    sid_overlap = "11111111-1111-1111-1111-111111111111"
    sid_native_only = "22222222-2222-2222-2222-222222222222"

    # Native: two sessions
    _seed_native_claude(tmp_path, sid=sid_overlap)
    _seed_native_claude(tmp_path, sid=sid_native_only, encoded_cwd="-tmp-other")
    # Local: one of those (overlapping id; first-store-wins).
    # The store recomputes event_count from the events list, so just
    # use cwd as the discriminator.
    local.create(
        Session(id=sid_overlap, tool="claude", cwd="/from/local"),
        [UserMessage(source="claude", text="from local")],
    )

    chained = ChainedSessionStore(local, NativeFilesSessionStore(home=tmp_path))
    sessions = chained.list()
    ids = [s.id for s in sessions]
    assert ids.count(sid_overlap) == 1
    assert sid_native_only in ids
    # First-store-wins: the overlapping id should reflect the LOCAL row
    # (cwd /from/local), not the native one.
    overlap = next(s for s in sessions if s.id == sid_overlap)
    assert overlap.cwd == "/from/local"


def test_chained_get_finds_in_either_store(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    local = LocalSessionStore(paths)
    local.create(
        Session(id="local-only", tool="claude"),
        [UserMessage(source="claude", text="x")],
    )
    sid = "33333333-3333-3333-3333-333333333333"
    _seed_native_claude(tmp_path, sid=sid)
    chained = ChainedSessionStore(local, NativeFilesSessionStore(home=tmp_path))

    assert chained.get("local-only") is not None
    assert chained.get(sid) is not None
    assert chained.get("nope") is None


def test_chained_events_pulls_from_correct_store(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    local = LocalSessionStore(paths)
    local.create(
        Session(id="local-1", tool="claude"),
        [UserMessage(source="claude", text="local-event")],
    )
    sid = "44444444-4444-4444-4444-444444444444"
    _seed_native_claude(tmp_path, sid=sid)
    chained = ChainedSessionStore(local, NativeFilesSessionStore(home=tmp_path))

    local_events = list(chained.events("local-1"))
    assert any(getattr(e, "text", "") == "local-event" for e in local_events)

    native_events = list(chained.events(sid))
    assert any(e.type == "user_message" for e in native_events)


def test_chained_create_uses_first_writable_store(tmp_path: Path):
    """When the first store is read-only and the second is writable,
    create falls through to the writable one."""
    paths = TrackPaths.under(tmp_path)
    local = LocalSessionStore(paths)
    chained = ChainedSessionStore(NativeFilesSessionStore(home=tmp_path), local)

    s = chained.create(
        Session(id="written", tool="claude"),
        [UserMessage(source="claude", text="hi")],
    )
    assert s.id == "written"
    assert local.get("written") is not None


def test_chained_fork_chain_resolves_across_stores(tmp_path: Path):
    """Parent in native, child in local: events() walks the chain
    correctly across both stores."""
    paths = TrackPaths.under(tmp_path)
    local = LocalSessionStore(paths)
    parent_id = "55555555-5555-5555-5555-555555555555"
    _seed_native_claude(tmp_path, sid=parent_id)
    # Child stored in local, fork-pointing at parent in native.
    local.create(
        Session(
            id="child-of-native", tool="codex", forked_from=parent_id, fork_point=2
        ),
        [UserMessage(source="codex", text="child-1")],
    )
    chained = ChainedSessionStore(local, NativeFilesSessionStore(home=tmp_path))

    events = list(chained.events("child-of-native"))
    # Native parent contributes 2 events (its full history pre-fork);
    # child contributes 1.
    assert len(events) == 3


def test_chained_fork_chain_in_same_local_store_does_not_duplicate(tmp_path: Path):
    """Regression: when parent and child both live in the same
    LocalSessionStore, ChainedSessionStore.events() must not double-emit
    parent events. (Bugbot #5871e98c.)

    The chained store walks the fork chain itself; if it then asked the
    underlying store for the leaf via `events()` (which also walks the
    chain), parent events would be yielded twice.
    """
    paths = TrackPaths.under(tmp_path)
    local = LocalSessionStore(paths)
    local.create(
        Session(id="root", tool="claude"),
        [UserMessage(source="claude", text=f"r{i}") for i in range(4)],
    )
    local.create(
        Session(id="child", tool="claude", forked_from="root", fork_point=2),
        [
            UserMessage(source="claude", text="c0"),
            UserMessage(source="claude", text="c1"),
        ],
    )
    chained = ChainedSessionStore(local)

    events = list(chained.events("child"))
    # Expected: r0, r1 (parent up to fork_point=2), then c0, c1.
    assert [e.text for e in events] == ["r0", "r1", "c0", "c1"]


def test_chained_requires_at_least_one_store():
    with pytest.raises(ValueError):
        ChainedSessionStore()


def test_chained_remote_source_value_error():
    """`--source remote` should not silently accept; the CLI raises
    typer.BadParameter via _resolve_session_store. Here we just verify
    that ChainedSessionStore is constructible and other source modes
    work — the CLI test belongs in a different file."""
    paths_obj = TrackPaths.under(Path("/tmp"))  # only used for path construction
    chained = ChainedSessionStore(LocalSessionStore(paths_obj))
    # `list` returns empty for a fresh store.
    assert chained.list() == []
