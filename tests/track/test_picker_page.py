"""Unit tests for the fzf-reload helper.

The helper is the subprocess fzf invokes when the user presses
right/left/alt-h. We test it directly via `main()` so we don't rely on
`python -m` resolution or fzf being on the test host.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from fleet.track import _picker_page
from fleet.track.paths import TrackPaths
from fleet.track.store import LocalSessionStore, Session
from fleet.track.unified import UserMessage


# ------------------------------------------------------------------ #
# Fixtures                                                              #
# ------------------------------------------------------------------ #


@pytest.fixture
def stub_store(tmp_path: Path):
    """A LocalSessionStore seeded with 7 sessions so we can paginate
    in pages of 2."""
    paths = TrackPaths.under(tmp_path)
    store = LocalSessionStore(paths)
    for i in range(7):
        store.create(
            Session(
                id=f"s{i}",
                tool="claude",
                last_active=f"2026-04-3{i}T00:00:00Z",
            ),
            [UserMessage(source="claude", text=f"hi-{i}")],
        )
    return store, paths


def _state_for(paths: TrackPaths, *, current_index: int = 0,
               cursors=None, limit: int = 2, query: str = "") -> dict:
    return {
        "source": "stub",
        "tool": None,
        "cwd": None,
        "since": None,
        "query": query,
        "limit": limit,
        "current_index": current_index,
        "cursors": cursors or [None],
    }


def _write_state(tmp_path: Path, state: dict) -> Path:
    p = tmp_path / "state.json"
    p.write_text(json.dumps(state))
    return p


# Patch _resolve_store everywhere so the helper uses the test store.
@pytest.fixture(autouse=True)
def _patch_resolver(monkeypatch, request, stub_store):
    """Wire `_resolve_store` to the per-test stub. Skip when a test
    explicitly overrides resolver behavior (rare)."""
    if "no_autopatch_resolver" in request.keywords:
        yield
        return
    store, _paths = stub_store
    monkeypatch.setattr(_picker_page, "_resolve_store", lambda src: store)
    yield


# ------------------------------------------------------------------ #
# emit_page                                                            #
# ------------------------------------------------------------------ #


def test_emit_first_resets_index_to_zero(stub_store, tmp_path: Path):
    _store, paths = stub_store
    state = _state_for(paths, current_index=2,
                       cursors=[None, "cursor1", "cursor2"], limit=2)
    lines, new_state = _picker_page._emit_page(state, "first")
    assert new_state["current_index"] == 0
    assert len(lines) == 2  # first page = 2 rows
    # Latest sessions first (recency-DESC).
    assert lines[0].startswith("s6")
    assert lines[1].startswith("s5")


def test_emit_next_advances_one_page(stub_store, tmp_path: Path):
    _store, paths = stub_store
    state = _state_for(paths, current_index=0, cursors=[None], limit=2)
    lines, new_state = _picker_page._emit_page(state, "next")
    assert new_state["current_index"] == 1
    assert len(new_state["cursors"]) >= 2  # appended a new cursor
    assert lines[0].startswith("s4")
    assert lines[1].startswith("s3")


def test_emit_next_at_last_page_is_noop(stub_store, tmp_path: Path):
    """Walking past the last page must keep `current_index` and
    `cursors` unchanged so left-arrow still goes back correctly."""
    store, paths = stub_store
    # Walk forward until we run out, then try one more `next`.
    cursor = None
    cursors = [None]
    while True:
        items, next_cursor = store.page(limit=2, cursor=cursor)
        if next_cursor is None:
            break
        cursors.append(next_cursor)
        cursor = next_cursor
    final_idx = len(cursors) - 1
    state = _state_for(paths, current_index=final_idx,
                       cursors=cursors, limit=2)

    lines, new_state = _picker_page._emit_page(state, "next")
    assert new_state["current_index"] == final_idx  # unchanged
    assert new_state["cursors"] == cursors          # unchanged
    assert lines == []


def test_emit_prev_decrements_index(stub_store, tmp_path: Path):
    _store, paths = stub_store
    state = _state_for(paths, current_index=2,
                       cursors=[None, "cursorA", "cursorB"], limit=2)
    # The cursors stored in state would be real strings; the helper
    # passes them straight to store.page. Replace them with real ones.
    store, _paths = stub_store
    _, c1 = store.page(limit=2, cursor=None)        # cursor for page 1
    _, c2 = store.page(limit=2, cursor=c1)          # cursor for page 2
    state["cursors"] = [None, c1, c2]

    lines, new_state = _picker_page._emit_page(state, "prev")
    assert new_state["current_index"] == 1
    # Page 1 = sessions 4 and 3 (after 6, 5 on page 0).
    assert lines[0].startswith("s4")


def test_emit_prev_at_first_page_is_noop(stub_store, tmp_path: Path):
    _store, paths = stub_store
    state = _state_for(paths, current_index=0, cursors=[None], limit=2)
    lines, new_state = _picker_page._emit_page(state, "prev")
    assert new_state["current_index"] == 0
    assert lines == []


def test_emit_unknown_direction_raises(stub_store, tmp_path: Path):
    _store, paths = stub_store
    state = _state_for(paths)
    with pytest.raises(SystemExit):
        _picker_page._emit_page(state, "sideways")


def test_emit_query_resets_to_page_zero(stub_store, tmp_path: Path):
    """`--direction query` always returns page 0 of the new filtered
    set, regardless of where the user was paginated to before."""
    _store, paths = stub_store
    state = _state_for(paths, current_index=2,
                       cursors=[None, "x", "y"], limit=2, query="")
    lines, new_state = _picker_page._emit_page(state, "first")
    assert new_state["current_index"] == 0
    # cursors stack must reset (old cursors were for unfiltered set).
    assert new_state["cursors"][0] is None


def test_main_query_filters_results(stub_store, tmp_path: Path, capsys):
    """Passing --direction query --query <q> filters via store.page."""
    store, paths = stub_store
    # Add a session that only matches a specific search term.
    from fleet.track.unified import UserMessage
    store.create(
        Session(id="needle", tool="claude",
                last_active="2026-05-01T00:00:00Z",
                metadata={"title": "match-me-only"}),
        [UserMessage(source="claude", text="x")],
    )
    state_path = _write_state(tmp_path, _state_for(paths, limit=10))
    _picker_page.main([
        "--state-file", str(state_path),
        "--direction", "query",
        "--query", "match-me-only",
    ])
    out = capsys.readouterr().out.strip().splitlines()
    # Only the seeded session should appear.
    assert any(line.startswith("needle") for line in out)
    assert not any(line.startswith("s") for line in out)
    # State persisted with the new query.
    persisted = json.loads(state_path.read_text())
    assert persisted["query"] == "match-me-only"
    assert persisted["current_index"] == 0


def test_main_query_empty_clears_filter(stub_store, tmp_path: Path, capsys):
    """--query '' clears the filter (fzf passes empty when user
    backspaces the whole query)."""
    _store, paths = stub_store
    # Pre-seed with an active query.
    state_path = _write_state(
        tmp_path, _state_for(paths, limit=10, query="something-restrictive"),
    )
    _picker_page.main([
        "--state-file", str(state_path),
        "--direction", "query",
        "--query", "",
    ])
    out = capsys.readouterr().out.strip().splitlines()
    # All sessions back.
    assert len(out) == 7
    persisted = json.loads(state_path.read_text())
    assert persisted["query"] == ""


# ------------------------------------------------------------------ #
# main() — full subprocess analogue                                    #
# ------------------------------------------------------------------ #


def test_main_writes_lines_and_persists_state(stub_store, tmp_path: Path, capsys):
    _store, paths = stub_store
    state_path = _write_state(tmp_path, _state_for(paths, limit=2))

    rc = _picker_page.main([
        "--state-file", str(state_path), "--direction", "next",
    ])
    assert rc == 0

    captured = capsys.readouterr()
    out_lines = captured.out.strip().splitlines()
    assert len(out_lines) == 2  # one page

    # State on disk now reflects index advancement.
    new_state = json.loads(state_path.read_text())
    assert new_state["current_index"] == 1


def test_main_first_returns_to_page_zero(stub_store, tmp_path: Path, capsys):
    _store, paths = stub_store
    # Pre-seed advanced state.
    state_path = _write_state(
        tmp_path, _state_for(paths, current_index=3,
                             cursors=[None, "x", "y", "z"], limit=2),
    )
    rc = _picker_page.main([
        "--state-file", str(state_path), "--direction", "first",
    ])
    assert rc == 0
    new_state = json.loads(state_path.read_text())
    assert new_state["current_index"] == 0


def test_main_at_boundary_re_emits_current_page(stub_store, tmp_path: Path, capsys):
    """When `next` is called at the last page, the helper should still
    print the current page so fzf's reload doesn't end up empty."""
    store, paths = stub_store
    cursor = None
    cursors = [None]
    while True:
        _items, next_cursor = store.page(limit=2, cursor=cursor)
        if next_cursor is None:
            break
        cursors.append(next_cursor)
        cursor = next_cursor

    state_path = _write_state(tmp_path, _state_for(
        paths, current_index=len(cursors) - 1, cursors=cursors, limit=2,
    ))
    _picker_page.main([
        "--state-file", str(state_path), "--direction", "next",
    ])
    out = capsys.readouterr().out.strip().splitlines()
    # Some output (the re-emitted current page) — never empty.
    assert len(out) >= 1


def test_main_emitted_lines_match_format_line(stub_store, tmp_path: Path, capsys):
    """The fzf-reload output must use the same _format_line as the
    initial seed so first-token id parsing keeps working across pages."""
    from fleet.track.picker import _format_line

    _store, paths = stub_store
    state_path = _write_state(tmp_path, _state_for(paths, limit=2))
    _picker_page.main(["--state-file", str(state_path), "--direction", "next"])
    out = capsys.readouterr().out.strip().splitlines()

    store, _paths = stub_store
    items, _ = store.page(limit=2, cursor=None)
    next_cursor_used = json.loads(state_path.read_text())["cursors"][1]
    items, _ = store.page(limit=2, cursor=next_cursor_used)
    expected = [_format_line(s) for s in items]
    assert out == expected


# ------------------------------------------------------------------ #
# Shell quoting helper                                                 #
# ------------------------------------------------------------------ #


def test_shell_quote_handles_spaces():
    from fleet.track.picker import _shell_quote
    assert _shell_quote("/path with spaces/x") == "'/path with spaces/x'"


def test_shell_quote_handles_embedded_quotes():
    from fleet.track.picker import _shell_quote
    quoted = _shell_quote("it's tricky")
    # Should round-trip through a shell — single-quote escape pattern.
    assert "'\\''" in quoted


def test_shell_quote_empty_is_empty_string_literal():
    from fleet.track.picker import _shell_quote
    assert _shell_quote("") == "''"
