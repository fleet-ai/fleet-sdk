"""Unit tests for the Textual session/tool pickers.

Drives the apps via `App.run_test()` (Textual's built-in pilot harness)
so we don't need a real terminal. We assert on:

  - Initial render: first page rows match `store.page()`.
  - Live search: typing a query triggers a re-fetch and resets to page 0.
  - Paging: `pagedown` advances; `pageup` rewinds; cursors are stacked.
  - Submission: Enter exits with the highlighted Session.
  - Cancellation: Escape exits with None.
  - Tool picker: option ordering puts source-tool first; selection
    returns the tool name; Escape cancels.

The store is a real `LocalSessionStore` seeded with deterministic rows
so we can pin the "page 0 / page 1" output exactly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("textual")

from fleet.track.paths import TrackPaths  # noqa: E402
from fleet.track.picker_textual import (  # noqa: E402
    SessionPickerApp,
    ToolPickerApp,
)
from fleet.track.store import LocalSessionStore, Session  # noqa: E402
from fleet.track.unified import UserMessage  # noqa: E402


# ------------------------------------------------------------------ #
# Fixtures                                                              #
# ------------------------------------------------------------------ #


@pytest.fixture
def stub_store(tmp_path: Path):
    """A LocalSessionStore seeded with 7 sessions so we can paginate
    in pages of 2 and exercise both forward and backward walks."""
    paths = TrackPaths.under(tmp_path)
    store = LocalSessionStore(paths)
    for i in range(7):
        store.create(
            Session(
                id=f"s{i}",
                tool="claude",
                last_active=f"2026-04-3{i}T00:00:00Z",
                metadata={"title": f"title-{i}"},
            ),
            [UserMessage(source="claude", text=f"hi-{i}")],
        )
    return store


async def _settle(app, pilot) -> None:
    """Wait for any in-flight fetch worker to complete and the UI to
    reflect its result. Tests use this anywhere they previously called
    a single `pilot.pause()` — workers + run_in_executor mean the
    pipeline takes a few ticks to settle."""
    await app.workers.wait_for_complete()
    await pilot.pause()


# ------------------------------------------------------------------ #
# SessionPickerApp                                                      #
# ------------------------------------------------------------------ #


def _picker(stub_store, **kwargs) -> SessionPickerApp:
    """Build a picker with debounce disabled — tests don't need to
    simulate human typing speed."""
    return SessionPickerApp(stub_store, debounce_s=0, **kwargs)


@pytest.mark.asyncio
async def test_initial_page_renders_first_page(stub_store):
    app = _picker(stub_store, limit=2)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        assert app.current_index == 0
        # 7 rows, limit 2 → first page has rows s6 and s5 (recency-DESC).
        assert list(app.sessions_by_id) == ["s6", "s5"]


@pytest.mark.asyncio
async def test_right_arrow_advances_to_next_page(stub_store):
    """Left/right arrows are the primary paging keys."""
    app = _picker(stub_store, limit=2)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        await pilot.press("right")
        await _settle(app, pilot)
        assert app.current_index == 1
        assert list(app.sessions_by_id) == ["s4", "s3"]


@pytest.mark.asyncio
async def test_left_arrow_rewinds_one_page(stub_store):
    app = _picker(stub_store, limit=2)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        await pilot.press("right")
        await _settle(app, pilot)
        await pilot.press("right")
        await _settle(app, pilot)
        assert app.current_index == 2

        await pilot.press("left")
        await _settle(app, pilot)
        assert app.current_index == 1
        assert list(app.sessions_by_id) == ["s4", "s3"]


@pytest.mark.asyncio
async def test_pagedown_also_pages(stub_store):
    """pgdn/pgup are aliases for left/right — both should work."""
    app = _picker(stub_store, limit=2)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        await pilot.press("pagedown")
        await _settle(app, pilot)
        assert app.current_index == 1
        assert list(app.sessions_by_id) == ["s4", "s3"]


@pytest.mark.asyncio
async def test_left_at_first_page_is_noop(stub_store):
    app = _picker(stub_store, limit=2)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        await pilot.press("left")
        await _settle(app, pilot)
        assert app.current_index == 0


@pytest.mark.asyncio
async def test_right_at_last_page_is_noop(stub_store):
    app = _picker(stub_store, limit=2)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        # 7 rows / 2 per page → 4 pages (indexes 0..3).
        for _ in range(4):
            await pilot.press("right")
            await _settle(app, pilot)
        last_idx = app.current_index
        await pilot.press("right")
        await _settle(app, pilot)
        assert app.current_index == last_idx


@pytest.mark.asyncio
async def test_typing_query_resets_to_page_zero(stub_store):
    app = _picker(stub_store, limit=2)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        # Walk forward first so we can verify the reset.
        await pilot.press("right")
        await _settle(app, pilot)
        assert app.current_index == 1

        # Type "title-6". Each keystroke triggers on_input_changed, which
        # re-queries and resets to page 0.
        for ch in "title-6":
            await pilot.press(ch)
        await _settle(app, pilot)
        assert app.current_index == 0
        assert app.query_text == "title-6"
        # Only s6 matches that title.
        assert list(app.sessions_by_id) == ["s6"]


@pytest.mark.asyncio
async def test_typing_updates_query_text_synchronously(stub_store):
    """The Input's value (and our `query_text`) must reflect the
    keystroke immediately — that's what makes typing feel snappy.
    The store fetch happens in a worker after, but `query_text` is
    set synchronously inside on_input_changed."""
    app = _picker(stub_store, limit=2)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        await pilot.press("a")
        # Don't wait for the worker — just one tick for Input to fire.
        await pilot.pause()
        assert app.query_text == "a"


@pytest.mark.asyncio
async def test_clearing_query_restores_full_set(stub_store):
    """When the user backspaces to an empty query, the picker must
    revert to the unfiltered first page."""
    app = _picker(stub_store, limit=10)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        for ch in "title-6":
            await pilot.press(ch)
        await _settle(app, pilot)
        assert list(app.sessions_by_id) == ["s6"]

        for _ in range(len("title-6")):
            await pilot.press("backspace")
        await _settle(app, pilot)
        assert app.query_text == ""
        # All 7 sessions back (limit=10 fits them all on one page).
        assert len(app.sessions_by_id) == 7


@pytest.mark.asyncio
async def test_enter_submits_highlighted_session(stub_store):
    app = _picker(stub_store, limit=2)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        # First row of page 0 is s6 (highest last_active).
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.return_value, Session)
    assert app.return_value.id == "s6"


@pytest.mark.asyncio
async def test_down_then_enter_submits_second_row(stub_store):
    app = _picker(stub_store, limit=3)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert app.return_value.id == "s5"


@pytest.mark.asyncio
async def test_escape_cancels_returning_none(stub_store):
    app = _picker(stub_store, limit=2)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        await pilot.press("escape")
        await pilot.pause()
    assert app.return_value is None


@pytest.mark.asyncio
async def test_query_with_no_matches_renders_empty(stub_store):
    app = _picker(stub_store, limit=10)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        for ch in "no-such-thing":
            await pilot.press(ch)
        await _settle(app, pilot)
        assert app.sessions_by_id == {}
        # Submitting an empty page must not crash and must not exit.
        await pilot.press("enter")
        await pilot.pause()
        assert app.return_value is None  # still running effectively


# ------------------------------------------------------------------ #
# Live mode — store-side filtering for backends with too many rows     #
# ------------------------------------------------------------------ #


class _LiveStore:
    """Stub that reports more rows than fit in a snapshot — forces the
    picker into live mode. Tracks every page() call so tests can assert
    the picker actually re-queries on each keystroke."""

    def __init__(self, rows: list[Session]) -> None:
        from fleet.track.store import _matches_query, _sort_key

        self._rows_sorted = sorted(rows, key=_sort_key, reverse=True)
        self._matches_query = _matches_query
        self.calls: list[dict] = []

    def page(
        self, *, tool=None, cwd=None, since=None, query=None,
        limit=20, cursor=None,
    ):
        self.calls.append({"query": query, "cursor": cursor, "limit": limit})
        rows = self._rows_sorted
        if query:
            rows = [s for s in rows if self._matches_query(s, query)]
        idx = int(cursor) if cursor else 0
        page = rows[idx : idx + limit]
        next_idx = idx + limit
        next_cursor = str(next_idx) if next_idx < len(rows) else None
        return page, next_cursor

    def list(self, **_):
        return list(self._rows_sorted)


@pytest.mark.asyncio
async def test_picker_falls_into_live_mode_when_snapshot_overflows():
    """When the snapshot fetch returns a next_cursor (i.e. more rows
    exist than fit), the picker must switch to live mode and serve
    every keystroke + page action via store.page()."""
    from fleet.track.store import Session

    rows = [
        Session(id=f"s{i:02d}", tool="claude",
                last_active=f"2026-04-{(i % 28) + 1:02d}T00:00:00Z",
                metadata={"title": f"item-{i}"})
        for i in range(50)
    ]
    store = _LiveStore(rows)
    app = SessionPickerApp(
        store, limit=5, snapshot_limit=10, debounce_s=0,
    )
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        # Snapshot fetch returned 10 rows + a cursor → live mode.
        assert app._mode == "live"
        # Initial render shows up to `limit` rows from the snapshot,
        # NOT the full 10.
        assert len(app.sessions_by_id) == 5

        before = len(store.calls)
        for ch in "item-7":
            await pilot.press(ch)
        await _settle(app, pilot)
        # Each keystroke triggered a store.page() call (or coalesced via
        # exclusive=True), and at least one fetch landed.
        assert len(store.calls) > before
        # Last call carried the typed query.
        assert store.calls[-1]["query"] == "item-7"


@pytest.mark.asyncio
async def test_picker_live_mode_paging_uses_cursors():
    """Right arrow in live mode should advance via the store's cursor
    contract — picker holds a cursor stack, fetches next page on
    advance, and prev page from the cached cursor."""
    from fleet.track.store import Session

    rows = [
        Session(id=f"s{i:02d}", tool="claude",
                last_active=f"2026-04-{(i % 28) + 1:02d}T00:00:00Z")
        for i in range(20)
    ]
    store = _LiveStore(rows)
    app = SessionPickerApp(
        store, limit=4, snapshot_limit=4, debounce_s=0,
    )
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        assert app._mode == "live"
        first_page_ids = list(app.sessions_by_id)

        await pilot.press("right")
        await _settle(app, pilot)
        second_page_ids = list(app.sessions_by_id)
        assert first_page_ids != second_page_ids
        assert app.current_index == 1

        await pilot.press("left")
        await _settle(app, pilot)
        # Back to page 0, same rows as the first time.
        assert list(app.sessions_by_id) == first_page_ids


@pytest.mark.asyncio
async def test_picker_local_store_uses_snapshot_mode(stub_store):
    """With our seeded local stub (7 rows, snapshot_limit=2000), the
    snapshot easily fits and the picker should pick snapshot mode —
    every keystroke filters in-process, no further store calls."""
    app = SessionPickerApp(stub_store, limit=2, debounce_s=0)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        assert app._mode == "snapshot"
        assert app._snapshot is not None
        assert len(app._snapshot) == 7


# ------------------------------------------------------------------ #
# ToolPickerApp                                                         #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_tool_picker_source_tool_first():
    """`pick_tool_textual` is responsible for ordering, but ToolPickerApp
    just renders what it's given. We pass an already-ordered list."""
    app = ToolPickerApp(
        ["claude", "codex", "cursor"], source_tool="claude"
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        # Default highlight is the source tool's index.
        from textual.widgets import OptionList
        ol = app.query_one(OptionList)
        assert ol.highlighted == 0  # "claude" sits at index 0


@pytest.mark.asyncio
async def test_tool_picker_enter_returns_id():
    app = ToolPickerApp(
        ["claude", "codex"], source_tool="claude"
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert app.return_value == "claude"


@pytest.mark.asyncio
async def test_tool_picker_down_then_enter_picks_second():
    app = ToolPickerApp(
        ["claude", "codex"], source_tool="claude"
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
    assert app.return_value == "codex"


@pytest.mark.asyncio
async def test_tool_picker_escape_cancels():
    app = ToolPickerApp(
        ["claude", "codex"], source_tool="claude"
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.return_value is None
