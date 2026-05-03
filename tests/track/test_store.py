"""LocalSessionStore tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.track.paths import TrackPaths
from fleet.track.store import LocalSessionStore, Session
from fleet.track.unified import (
    AssistantMessage,
    SessionStart,
    ToolCall,
    UserMessage,
)


def _store(tmp_path: Path) -> LocalSessionStore:
    return LocalSessionStore(TrackPaths.under(tmp_path))


def _session(**kw) -> Session:
    return Session(
        id=kw.pop("id", "test-1"),
        tool=kw.pop("tool", "claude"),
        cwd=kw.pop("cwd", "/tmp/x"),
        started_at=kw.pop("started_at", "2026-04-30T00:00:00Z"),
        last_active=kw.pop("last_active", "2026-04-30T00:00:01Z"),
        **kw,
    )


def _msg(text: str, **kw) -> UserMessage:
    return UserMessage(source="claude", text=text, **kw)


# ------------------------------------------------------------------ #
# create + get                                                         #
# ------------------------------------------------------------------ #


def test_create_then_get(tmp_path: Path):
    store = _store(tmp_path)
    s = _session(id="s1")
    store.create(s, [_msg("hi"), _msg("there")])

    fetched = store.get("s1")
    assert fetched is not None
    assert fetched.id == "s1"
    assert fetched.event_count == 2


def test_get_missing_returns_none(tmp_path: Path):
    store = _store(tmp_path)
    assert store.get("nope") is None


def test_get_by_unique_prefix(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="abc1234"), [_msg("a")])
    store.create(_session(id="def5678"), [_msg("b")])
    s = store.get("abc")
    assert s is not None
    assert s.id == "abc1234"


def test_get_by_ambiguous_prefix_raises(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="abc111"), [_msg("a")])
    store.create(_session(id="abc222"), [_msg("b")])
    with pytest.raises(KeyError, match="Ambiguous"):
        store.get("abc")


def test_create_requires_id(tmp_path: Path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="id"):
        store.create(Session(id="", tool="claude"), [])


# ------------------------------------------------------------------ #
# events                                                               #
# ------------------------------------------------------------------ #


def test_events_returns_what_was_stored(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="s1"), [
        _msg("first"),
        AssistantMessage(source="claude", text="answer"),
    ])
    events = list(store.events("s1"))
    assert len(events) == 2
    assert events[0].text == "first"
    assert events[1].text == "answer"


def test_events_for_missing_session_raises(tmp_path: Path):
    store = _store(tmp_path)
    with pytest.raises(KeyError):
        list(store.events("nope"))


def test_events_skips_corrupt_lines(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="s1"), [_msg("ok")])
    # Append garbage to the events file.
    f = TrackPaths.under(tmp_path).track_dir / "local-store" / "sessions" / "s1.jsonl"
    with open(f, "a") as fp:
        fp.write("not json{{\n")
        fp.write('{"missing": "type"}\n')
    # Should still yield the valid event without raising.
    events = list(store.events("s1"))
    assert len(events) == 1


# ------------------------------------------------------------------ #
# Branches / forks                                                     #
# ------------------------------------------------------------------ #


def test_fork_walks_ancestor_chain(tmp_path: Path):
    store = _store(tmp_path)
    # Root session: 5 user messages
    store.create(
        _session(id="root", tool="codex"),
        [_msg(f"root-{i}") for i in range(5)],
    )
    # Fork at event 3, claude added 2 events
    store.create(
        _session(id="fork1", tool="claude", forked_from="root", fork_point=3),
        [_msg("claude-a"), _msg("claude-b")],
    )

    events = list(store.events("fork1"))
    # Expected: first 3 from root, then 2 from fork1 = 5 total.
    assert len(events) == 5
    assert [e.text for e in events] == [
        "root-0", "root-1", "root-2", "claude-a", "claude-b",
    ]


def test_fork_chain_three_levels(tmp_path: Path):
    """codex(0..10) → claude(0..3) → codex(0..2)."""
    store = _store(tmp_path)
    store.create(_session(id="A", tool="codex"),
                 [_msg(f"A-{i}") for i in range(10)])
    store.create(
        _session(id="B", tool="claude", forked_from="A", fork_point=4),
        [_msg(f"B-{i}") for i in range(3)],
    )
    store.create(
        _session(id="C", tool="codex", forked_from="B", fork_point=2),
        [_msg(f"C-{i}") for i in range(2)],
    )

    events = list(store.events("C"))
    # A 0..4, B 0..2, C 0..2
    expected = ["A-0", "A-1", "A-2", "A-3", "B-0", "B-1", "C-0", "C-1"]
    assert [e.text for e in events] == expected


def test_fork_chain_with_dangling_parent_does_not_crash(tmp_path: Path):
    """If parent is deleted, chain walk gracefully truncates."""
    store = _store(tmp_path)
    store.create(_session(id="A"), [_msg("A1"), _msg("A2"), _msg("A3")])
    store.create(
        _session(id="B", forked_from="A", fork_point=2),
        [_msg("B1")],
    )
    # Delete the parent.
    store.delete("A")
    # Chain walk on B finds only B's own events; doesn't raise.
    events = list(store.events("B"))
    assert [e.text for e in events] == ["B1"]


def test_fork_cycle_truncates(tmp_path: Path):
    """Defensive: a synthetic cycle in forked_from doesn't infinite-loop."""
    store = _store(tmp_path)
    store.create(_session(id="X", forked_from="Y", fork_point=1), [_msg("X1")])
    store.create(_session(id="Y", forked_from="X", fork_point=1), [_msg("Y1")])
    # Whichever direction we walk, it stops.
    list(store.events("X"))  # must not hang
    list(store.events("Y"))


# ------------------------------------------------------------------ #
# list                                                                 #
# ------------------------------------------------------------------ #


def test_list_returns_all(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="a"), [_msg("a")])
    store.create(_session(id="b"), [_msg("b")])
    ids = sorted(s.id for s in store.list())
    assert ids == ["a", "b"]


def test_list_filters_by_tool(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="c1", tool="claude"), [_msg("a")])
    store.create(_session(id="c2", tool="codex"), [_msg("b")])
    claude_only = list(store.list(tool="claude"))
    assert len(claude_only) == 1
    assert claude_only[0].id == "c1"


def test_list_filters_by_cwd(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="a", cwd="/x"), [_msg("a")])
    store.create(_session(id="b", cwd="/y"), [_msg("b")])
    only_x = list(store.list(cwd="/x"))
    assert {s.id for s in only_x} == {"a"}


def test_list_filters_by_since(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="old", last_active="2025-01-01T00:00:00Z"), [_msg("a")])
    store.create(_session(id="new", last_active="2026-04-30T00:00:00Z"), [_msg("b")])
    recent = list(store.list(since="2026-01-01T00:00:00Z"))
    assert {s.id for s in recent} == {"new"}


def test_list_sorts_most_recent_first(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="old", last_active="2025-01-01T00:00:00Z"), [_msg("a")])
    store.create(_session(id="new", last_active="2026-04-30T00:00:00Z"), [_msg("b")])
    out = list(store.list())
    assert [s.id for s in out] == ["new", "old"]


def test_list_limit(tmp_path: Path):
    store = _store(tmp_path)
    for i in range(5):
        store.create(_session(id=f"s{i}", last_active=f"2026-04-3{i}T00:00:00Z"), [_msg("x")])
    out = list(store.list(limit=3))
    assert len(out) == 3


# ------------------------------------------------------------------ #
# append                                                               #
# ------------------------------------------------------------------ #


def test_append_extends_session(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="s1"), [_msg("first")])
    store.append("s1", [_msg("second"), _msg("third")])
    events = list(store.events("s1"))
    assert [e.text for e in events] == ["first", "second", "third"]


def test_append_to_missing_raises(tmp_path: Path):
    store = _store(tmp_path)
    with pytest.raises(KeyError):
        store.append("nope", [_msg("x")])


# ------------------------------------------------------------------ #
# delete                                                               #
# ------------------------------------------------------------------ #


def test_delete_removes_session(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="s1"), [_msg("a")])
    assert store.delete("s1") is True
    assert store.get("s1") is None


def test_delete_returns_false_for_missing(tmp_path: Path):
    store = _store(tmp_path)
    assert store.delete("nope") is False


def test_delete_does_not_cascade_to_children(tmp_path: Path):
    """Deleting a parent leaves children's `forked_from` dangling but
    the child still exists and its events still walk gracefully."""
    store = _store(tmp_path)
    store.create(_session(id="A"), [_msg("a1"), _msg("a2"), _msg("a3")])
    store.create(_session(id="B", forked_from="A", fork_point=2), [_msg("b1")])

    store.delete("A")
    assert store.get("A") is None
    assert store.get("B") is not None  # child still exists


# ------------------------------------------------------------------ #
# Persistence + tolerance                                              #
# ------------------------------------------------------------------ #


def test_index_persists_across_store_instances(tmp_path: Path):
    """Reopening a store sees previously-created sessions."""
    paths = TrackPaths.under(tmp_path)
    s1 = LocalSessionStore(paths)
    s1.create(_session(id="s1"), [_msg("a")])

    s2 = LocalSessionStore(paths)
    fetched = s2.get("s1")
    assert fetched is not None
    assert fetched.event_count == 1


def test_index_ignores_unknown_fields(tmp_path: Path):
    """An older store reading a session written by a newer schema
    must not crash."""
    import json as j
    store = _store(tmp_path)
    store.create(_session(id="s1"), [_msg("a")])
    # Manually append a row with extra fields.
    paths = TrackPaths.under(tmp_path)
    extra = {"id": "s2", "tool": "claude", "future_field": "surprise",
             "started_at": "2026-04-30T00:00:00Z"}
    with open(paths.track_dir / "local-store" / "index.jsonl", "a") as f:
        f.write(j.dumps(extra) + "\n")
    # Should still read both sessions.
    ids = {s.id for s in store.list()}
    assert ids == {"s1", "s2"}
