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


# ------------------------------------------------------------------ #
# Cursor format — must stay byte-compatible with the orchestrator      #
# ------------------------------------------------------------------ #


def test_cursor_format_pinned():
    """Golden test: a cursor for a known (last_active, id) pair must
    encode to a fixed string. If this test ever has to change, you've
    broken wire compat with the server's `_encode_cursor` (see
    theseus:orchestrator/public_api/track.py). Update both sides
    together or paged scripts will paginate against the wrong rows."""
    from fleet.track.store import _encode_cursor, _decode_cursor

    cursor = _encode_cursor("2026-04-30T00:00:00Z", "abc12345")
    # base64url(json({"la":"2026-04-30T00:00:00Z","id":"abc12345"})), no padding.
    assert cursor == "eyJsYSI6IjIwMjYtMDQtMzBUMDA6MDA6MDBaIiwiaWQiOiJhYmMxMjM0NSJ9"
    decoded = _decode_cursor(cursor)
    assert decoded == {"la": "2026-04-30T00:00:00Z", "id": "abc12345"}


def test_cursor_with_null_last_active_round_trips():
    from fleet.track.store import _encode_cursor, _decode_cursor

    cursor = _encode_cursor(None, "deadbeef")
    decoded = _decode_cursor(cursor)
    assert decoded == {"la": None, "id": "deadbeef"}


def test_cursor_decode_rejects_garbage():
    from fleet.track.store import _decode_cursor

    with pytest.raises(ValueError):
        _decode_cursor("not-base64!!")


def test_cursor_decode_rejects_missing_keys():
    """A cursor that decodes to JSON but lacks `la`/`id` is wire garbage."""
    import base64
    import json as j
    from fleet.track.store import _decode_cursor

    raw = j.dumps({"foo": "bar"}, separators=(",", ":"))
    cursor = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    with pytest.raises(ValueError, match="missing keys"):
        _decode_cursor(cursor)


def test_cursor_decode_empty_returns_none():
    from fleet.track.store import _decode_cursor
    assert _decode_cursor(None) is None
    assert _decode_cursor("") is None


# ------------------------------------------------------------------ #
# page() — must mirror the orchestrator's predicate exactly            #
# ------------------------------------------------------------------ #


def test_page_returns_recency_first(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="old", last_active="2025-01-01T00:00:00Z"), [_msg("a")])
    store.create(_session(id="new", last_active="2026-04-30T00:00:00Z"), [_msg("b")])
    items, _cursor = store.page(limit=10)
    assert [s.id for s in items] == ["new", "old"]


def test_page_returns_no_cursor_when_under_limit(tmp_path: Path):
    store = _store(tmp_path)
    store.create(_session(id="a"), [_msg("x")])
    items, cursor = store.page(limit=10)
    assert len(items) == 1
    assert cursor is None


def test_page_returns_cursor_when_more_pages_exist(tmp_path: Path):
    store = _store(tmp_path)
    for i in range(5):
        store.create(
            _session(id=f"s{i}", last_active=f"2026-04-3{i}T00:00:00Z"),
            [_msg("x")],
        )
    items, cursor = store.page(limit=2)
    assert len(items) == 2
    assert cursor is not None


def test_page_walks_full_set_via_cursor(tmp_path: Path):
    """Walking pages with `--cursor` must visit every session exactly once
    in recency-DESC order."""
    store = _store(tmp_path)
    for i in range(7):
        store.create(
            _session(id=f"s{i}", last_active=f"2026-04-3{i}T00:00:00Z"),
            [_msg("x")],
        )

    seen: list[str] = []
    cursor = None
    while True:
        items, cursor = store.page(limit=2, cursor=cursor)
        seen.extend(s.id for s in items)
        if cursor is None:
            break

    assert seen == ["s6", "s5", "s4", "s3", "s2", "s1", "s0"]
    # No duplicates.
    assert len(set(seen)) == len(seen)


def test_page_tiebreak_by_id_desc_when_last_active_equal(tmp_path: Path):
    """Two sessions with identical last_active must sort by id DESC,
    matching the server's ORDER BY clause."""
    store = _store(tmp_path)
    same = "2026-04-30T00:00:00Z"
    store.create(_session(id="aaa", last_active=same), [_msg("x")])
    store.create(_session(id="bbb", last_active=same), [_msg("x")])
    store.create(_session(id="ccc", last_active=same), [_msg("x")])
    items, _ = store.page(limit=10)
    assert [s.id for s in items] == ["ccc", "bbb", "aaa"]


def test_page_null_last_active_sweeps_to_tail(tmp_path: Path):
    """Sessions with NULL last_active sort AFTER any with a value.
    Must hold across the cursor walk too."""
    store = _store(tmp_path)
    store.create(_session(id="dated", last_active="2026-04-30T00:00:00Z"), [_msg("x")])
    store.create(_session(id="nullA", last_active=None), [_msg("x")])
    store.create(_session(id="nullB", last_active=None), [_msg("x")])

    page1, cursor = store.page(limit=2)
    assert [s.id for s in page1] == ["dated", "nullB"]
    assert cursor is not None

    page2, cursor = store.page(limit=2, cursor=cursor)
    assert [s.id for s in page2] == ["nullA"]
    assert cursor is None


def test_page_filters_apply_before_cursor(tmp_path: Path):
    """Filter (--tool=claude) must restrict the row set BEFORE the
    cursor predicate. Otherwise a cursor minted with one filter would
    leak rows when walked under a different filter."""
    store = _store(tmp_path)
    for i in range(4):
        store.create(
            _session(id=f"c{i}", tool="claude", last_active=f"2026-04-3{i}T00:00:00Z"),
            [_msg("x")],
        )
    for i in range(2):
        store.create(
            _session(id=f"x{i}", tool="codex", last_active=f"2026-04-3{i}T00:00:00Z"),
            [_msg("x")],
        )

    page1, cursor = store.page(tool="claude", limit=2)
    assert [s.id for s in page1] == ["c3", "c2"]

    page2, cursor = store.page(tool="claude", limit=2, cursor=cursor)
    assert [s.id for s in page2] == ["c1", "c0"]
    assert cursor is None


def test_page_clamps_limit_to_max(tmp_path: Path):
    """`limit` over MAX_PAGE_LIMIT must be clamped, not used as-is —
    matches the server's `Query(le=200)` constraint."""
    from fleet.track.store import MAX_PAGE_LIMIT

    store = _store(tmp_path)
    # Seed MAX+1 sessions; ask for MAX*10 — should still get exactly MAX
    # in the page.
    for i in range(MAX_PAGE_LIMIT + 1):
        store.create(
            _session(id=f"s{i:04d}", last_active=f"2026-04-30T00:00:{i % 60:02d}Z"),
            [_msg("x")],
        )
    items, cursor = store.page(limit=MAX_PAGE_LIMIT * 10)
    assert len(items) == MAX_PAGE_LIMIT
    assert cursor is not None  # one row remains


def test_page_invalid_cursor_raises_value_error(tmp_path: Path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.page(limit=10, cursor="not-a-real-cursor!!!")


def test_list_uses_default_page_limit(tmp_path: Path):
    """`list()` without an explicit limit must return up to DEFAULT_PAGE_LIMIT
    rows — verifying the delegation to page() didn't regress."""
    from fleet.track.store import DEFAULT_PAGE_LIMIT

    store = _store(tmp_path)
    for i in range(DEFAULT_PAGE_LIMIT + 5):
        store.create(
            _session(id=f"s{i:03d}", last_active=f"2026-04-30T{i % 24:02d}:00:00Z"),
            [_msg("x")],
        )
    out = store.list()
    assert len(out) == DEFAULT_PAGE_LIMIT


def test_page_query_filter_substring_match(tmp_path: Path):
    """`query` is case-insensitive substring across id/tool/cwd/title."""
    store = _store(tmp_path)
    store.create(
        _session(id="abc-fleet", cwd="/tmp/fleet-sdk",
                 metadata={"title": "fleet-track sidecar"}),
        [_msg("x")],
    )
    store.create(
        _session(id="def-other", cwd="/tmp/theseus",
                 metadata={"title": "session metadata index"}),
        [_msg("x")],
    )

    items, _ = store.page(query="fleet", limit=10)
    assert {s.id for s in items} == {"abc-fleet"}

    items, _ = store.page(query="THESEUS", limit=10)  # case-insensitive
    assert {s.id for s in items} == {"def-other"}

    items, _ = store.page(query="metadata", limit=10)  # title field
    assert {s.id for s in items} == {"def-other"}


def test_page_query_empty_string_is_no_filter(tmp_path: Path):
    """Empty query (what fzf passes when the user has typed nothing)
    matches everything, like a missing query."""
    store = _store(tmp_path)
    store.create(_session(id="a"), [_msg("x")])
    store.create(_session(id="b"), [_msg("x")])

    items_none, _ = store.page(query=None, limit=10)
    items_empty, _ = store.page(query="", limit=10)
    assert {s.id for s in items_none} == {s.id for s in items_empty} == {"a", "b"}


def test_page_query_paginates_within_filtered_set(tmp_path: Path):
    """A cursor minted with a query must keep walking the same filtered
    set, not leak unfiltered rows on subsequent pages."""
    store = _store(tmp_path)
    for i in range(4):
        store.create(
            _session(id=f"keep-{i}", tool="claude",
                     last_active=f"2026-04-3{i}T00:00:00Z",
                     metadata={"title": "keep-me"}),
            [_msg("x")],
        )
    for i in range(3):
        store.create(
            _session(id=f"drop-{i}", tool="claude",
                     last_active=f"2026-04-3{i}T00:00:00Z",
                     metadata={"title": "drop-me"}),
            [_msg("x")],
        )

    page1, cursor = store.page(query="keep-me", limit=2)
    assert {s.id for s in page1} == {"keep-3", "keep-2"}
    page2, cursor = store.page(query="keep-me", limit=2, cursor=cursor)
    assert {s.id for s in page2} == {"keep-1", "keep-0"}
    assert cursor is None


def test_chained_page_eager_merge_paginates(tmp_path: Path):
    """ChainedSessionStore.page() eager-merges across backing stores
    and paginates the merged view via cursor. Means the picker's
    default `--source auto` honors page-size and paging just like a
    single backend."""
    from fleet.track.store import ChainedSessionStore, NativeFilesSessionStore

    local = _store(tmp_path)
    for i in range(3):
        local.create(
            _session(id=f"local-{i}", tool="claude",
                     last_active=f"2026-04-3{i}T00:00:00Z"),
            [_msg("x")],
        )

    chained = ChainedSessionStore(local, NativeFilesSessionStore(home=tmp_path))

    page1, cursor = chained.page(limit=2)
    assert len(page1) == 2
    assert cursor is not None
    page2, cursor = chained.page(limit=2, cursor=cursor)
    # 3 sessions total in chain; second page has the leftover one.
    assert len(page2) == 1
    assert cursor is None
    seen = [s.id for s in page1] + [s.id for s in page2]
    assert sorted(seen) == ["local-0", "local-1", "local-2"]


def test_chained_page_dedupes_by_id(tmp_path: Path):
    """When a session appears in multiple backing stores (e.g. native
    and stub both have the same id), chained.page() emits it once."""
    from fleet.track.store import ChainedSessionStore

    local_a = _store(tmp_path)
    local_b = LocalSessionStore(TrackPaths.under(tmp_path), name="other-store")
    for store in (local_a, local_b):
        store.create(
            _session(id="shared", tool="claude",
                     last_active="2026-04-30T00:00:00Z"),
            [_msg("x")],
        )

    chained = ChainedSessionStore(local_a, local_b)
    items, cursor = chained.page(limit=10)
    assert [s.id for s in items] == ["shared"]
    assert cursor is None


def test_chained_page_query_filter(tmp_path: Path):
    """Query filter applies before merging — and stays valid across
    backing stores."""
    from fleet.track.store import ChainedSessionStore, NativeFilesSessionStore

    local = _store(tmp_path)
    local.create(
        _session(id="keep", metadata={"title": "match-me"}),
        [_msg("x")],
    )
    local.create(
        _session(id="drop", metadata={"title": "ignore-me"}),
        [_msg("x")],
    )
    chained = ChainedSessionStore(local, NativeFilesSessionStore(home=tmp_path))

    items, _ = chained.page(query="match-me", limit=10)
    assert [s.id for s in items] == ["keep"]
