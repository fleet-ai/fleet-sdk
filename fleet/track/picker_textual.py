"""Textual-based session picker.

Replaces the fzf + reload-helper subprocess dance with a single in-process
Textual app:

  - `Input` on top: types into the search box and re-queries the store on
    every keystroke (server-side filter, same as the old `--disabled +
    change:reload` pattern).
  - `DataTable` below: shows the current page of rows. Up/down move the
    row cursor.
  - `pgdn` / `pgup` page next/back. Cursors are stacked so re-walking is
    free (matches the old `_picker_page.py` state machine).
  - `enter` selects the highlighted row, returning the Session.
  - `escape` cancels, returning None.

The store contract is unchanged — we just call `store.page()` directly
instead of marshaling args through a tempfile + subprocess.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Input, Static
from textual.widgets._data_table import CellDoesNotExist

from .store import Session


# How long to wait after a keystroke before applying the new query.
# In the snapshot model the filter is in-memory so this can be 0; we
# keep a small value as a safety net for very fast typists on huge
# session sets. Tests override with 0.
SEARCH_DEBOUNCE_S: float = 0.0

# How many sessions to pull on mount. Big enough to cover any realistic
# user, small enough to fit in memory without ceremony. Walking the
# native session files on disk is ~O(N) disk reads per session — so we
# want to pay that cost ONCE per picker open, not per keystroke.
SNAPSHOT_LIMIT: int = 2000


class SessionPickerApp(App):
    """The picker. Built on top of a `SessionStore` (any backend works
    — local stub, native files, chained, future remote)."""

    CSS = """
    #search {
        dock: top;
        height: 3;
        border: tall $accent;
    }
    #status {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    DataTable {
        height: 1fr;
    }
    """

    # Both ←/→ and pgup/pgdn page; the user can use either. ←/→ are
    # bound at app level with `priority=True` so the search Input doesn't
    # eat them as cursor-movement keystrokes — typing in the search box
    # is short and rarely needs intra-text navigation, and stealing those
    # keys is the price of having them page.
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("up", "cursor_up", "Up", show=False, priority=True),
        Binding("down", "cursor_down", "Down", show=False, priority=True),
        Binding("right", "next_page", "Next", show=True, priority=True),
        Binding("left", "prev_page", "Prev", show=True, priority=True),
        Binding("pagedown", "next_page", "Next", show=False, priority=True),
        Binding("pageup", "prev_page", "Prev", show=False, priority=True),
        Binding("enter", "submit", "Open", show=True, priority=True),
    ]

    def __init__(
        self,
        store,
        *,
        tool: Optional[str] = None,
        cwd: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 20,
        header: str = "",
        debounce_s: float = SEARCH_DEBOUNCE_S,
        snapshot_limit: int = SNAPSHOT_LIMIT,
    ) -> None:
        super().__init__()
        self.store = store
        self.tool = tool
        self.cwd = cwd
        self.since = since
        self.limit = limit
        self.header_text = header
        self.debounce_s = debounce_s
        self.snapshot_limit = snapshot_limit

        # In-memory snapshot of (up to) `snapshot_limit` sessions, fetched
        # once on mount. None = not yet loaded. Filtering on every
        # keystroke walks this list in-process; we never re-hit the store
        # on a search. The store's `page()` walks ~O(N_files * disk-reads)
        # for native sessions — too slow per keystroke.
        #
        # Live mode (`_mode == "live"`) is used when the store has more
        # rows than the snapshot can hold — typically a remote backend.
        # In live mode we don't keep `_snapshot`; every keystroke + page
        # action calls `store.page(query=..., cursor=...)` directly.
        self._mode: str = "loading"  # "snapshot" | "live" | "loading"
        self._snapshot: Optional[list[Session]] = None

        # Cursor stack for live mode (analogous to `_picker_page.py`'s
        # state file). cursors[i] is the cursor used to fetch page i.
        self._live_cursors: list[Optional[str]] = [None]

        # Page index. In snapshot mode, indexes into the filtered list.
        # In live mode, indexes into `_live_cursors`.
        self.current_index = 0

        # Live query string. Empty = no filter.
        # NB: named `query_text` (not `query`) to avoid shadowing
        # `App.query()` — the DOM-query method we use to look up widgets.
        self.query_text = ""

        # Map from session id → Session for the currently rendered page,
        # so submit() can look up the highlighted row in O(1).
        self.sessions_by_id: dict[str, Session] = {}

    # -- compose / mount --------------------------------------------- #

    def compose(self) -> ComposeResult:
        yield Input(placeholder="search…", id="search")
        yield DataTable(id="rows", cursor_type="row", zebra_stripes=True)
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("id", "tool", "when", "project", "#events", "title")
        self.query_one(Input).focus()
        self.query_one("#status", Static).update("loading sessions…")
        self._populate_snapshot()

    # -- input / events ---------------------------------------------- #

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search":
            return
        # Update local state synchronously so the Input renders the
        # character immediately.
        self.query_text = event.value
        self.current_index = 0
        if self._mode == "live":
            # Reset cursor stack on every query change — cursors are
            # scoped to a particular filter set, so prev cursors are
            # invalid against the new query.
            self._live_cursors = [None]
            self._live_search()
        else:
            # Snapshot mode: filter in-memory. Microseconds for
            # thousands of rows; no worker needed.
            if self.debounce_s > 0:
                self._render_filtered_debounced()
            else:
                self._render_filtered()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Pressing Enter inside the Input fires `Input.Submitted` instead
        # of routing to the app-level `enter` binding. Forward to submit.
        if event.input.id == "search":
            self.action_submit()

    # -- actions ------------------------------------------------------ #

    def action_cursor_up(self) -> None:
        self.query_one(DataTable).action_cursor_up()

    def action_cursor_down(self) -> None:
        self.query_one(DataTable).action_cursor_down()

    def action_next_page(self) -> None:
        if self._mode == "live":
            self._live_advance()
            return
        if self._snapshot is None:
            return
        if (self.current_index + 1) * self.limit >= len(self._filtered()):
            return  # already at last page
        self.current_index += 1
        self._render_filtered()

    def action_prev_page(self) -> None:
        if self.current_index == 0:
            return
        self.current_index -= 1
        if self._mode == "live":
            self._live_search()  # re-fetch page at new index
        else:
            self._render_filtered()

    def action_cancel(self) -> None:
        self.exit(None)

    def action_submit(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return
        sid = cell_key.row_key.value
        if sid is None:
            return
        chosen = self.sessions_by_id.get(sid)
        if chosen is not None:
            self.exit(chosen)

    # -- workers / snapshot ------------------------------------------ #

    @work(exclusive=True, group="snapshot")
    async def _populate_snapshot(self) -> None:
        """One-shot fetch of up to `snapshot_limit` sessions, off-thread.

        Auto-detects which mode to operate in:
          - `next_cursor is None` → snapshot mode. All rows fit in
            memory; every keystroke filters in-process.
          - `next_cursor is not None` → live mode. The store has more
            rows than fit; every keystroke (and page action) hits the
            store with `query=...` so server-side filtering can scale.

        For local backends with <2000 sessions this is always snapshot
        mode. RemoteSessionStore against a real user with 10k+ sessions
        will fall into live mode automatically.
        """
        loop = asyncio.get_running_loop()
        items, next_cursor = await loop.run_in_executor(
            None,
            lambda: self.store.page(
                tool=self.tool,
                cwd=self.cwd,
                since=self.since,
                limit=self.snapshot_limit,
            ),
        )
        if next_cursor is None:
            self._mode = "snapshot"
            self._snapshot = items
            self._render_filtered()
        else:
            # More rows than the snapshot holds — defer to the store on
            # every interaction. The snapshot fetch used `snapshot_limit`
            # only to detect overflow, so fetch the real first page using
            # the UI page size before rendering.
            self._mode = "live"
            items, next_cursor = await loop.run_in_executor(
                None,
                lambda: self.store.page(
                    tool=self.tool,
                    cwd=self.cwd,
                    since=self.since,
                    query=self.query_text or None,
                    limit=self.limit,
                    cursor=None,
                ),
            )
            self._live_cursors = [None]
            if next_cursor is not None:
                self._live_cursors.append(next_cursor)
            self._render_live(items, next_cursor)

    @work(exclusive=True, group="search")
    async def _render_filtered_debounced(self) -> None:
        """Debounced wrapper around `_render_filtered`. Only used when
        `debounce_s > 0` (default 0 — filtering is fast enough that we
        can render on every keystroke)."""
        await asyncio.sleep(self.debounce_s)
        self._render_filtered()

    @work(exclusive=True, group="live")
    async def _live_search(self) -> None:
        """Live-mode equivalent of `_render_filtered`: fetch the current
        page from the store with the current query, render it. Debounced
        so fast typists don't queue up redundant fetches."""
        if self.debounce_s > 0:
            await asyncio.sleep(self.debounce_s)
        loop = asyncio.get_running_loop()
        cursor = (
            self._live_cursors[self.current_index]
            if (0 <= self.current_index < len(self._live_cursors))
            else None
        )
        items, next_cursor = await loop.run_in_executor(
            None,
            lambda: self.store.page(
                tool=self.tool,
                cwd=self.cwd,
                since=self.since,
                query=self.query_text or None,
                limit=self.limit,
                cursor=cursor,
            ),
        )
        # Cache the next cursor so a subsequent next-page is O(1).
        if next_cursor is not None and self.current_index + 1 == len(
            self._live_cursors
        ):
            self._live_cursors.append(next_cursor)
        self._render_live(items, next_cursor)

    @work(exclusive=True, group="live")
    async def _live_advance(self) -> None:
        """Move to the next page in live mode. If we don't yet know the
        next cursor (last cached page), fetch the current page just to
        learn it; then move forward and fetch the next."""
        if self.current_index + 1 < len(self._live_cursors):
            self.current_index += 1
            self._live_search()
            return
        loop = asyncio.get_running_loop()
        cursor = self._live_cursors[self.current_index]
        _, next_cursor = await loop.run_in_executor(
            None,
            lambda: self.store.page(
                tool=self.tool,
                cwd=self.cwd,
                since=self.since,
                query=self.query_text or None,
                limit=self.limit,
                cursor=cursor,
            ),
        )
        if next_cursor is None:
            return  # already at last page
        self._live_cursors.append(next_cursor)
        self.current_index += 1
        self._live_search()

    # -- filter / render --------------------------------------------- #

    def _filtered(self) -> list[Session]:
        """Apply the current query against the snapshot. Empty snapshot
        before mount-fetch completes; empty list when no rows match."""
        if self._snapshot is None:
            return []
        if not self.query_text:
            return self._snapshot
        # `_matches_query` is the same predicate the server uses, kept
        # in store.py so wire and in-memory filters stay aligned.
        from .store import _matches_query

        q = self.query_text
        return [s for s in self._snapshot if _matches_query(s, q)]

    def _render_filtered(self) -> None:
        """Snapshot mode: slice the in-memory filtered list."""
        filtered = self._filtered()
        start = self.current_index * self.limit
        end = start + self.limit
        items = filtered[start:end]
        has_more = end < len(filtered)
        # Status: "page X · K of M rows" when loaded; "loading…" otherwise.
        if self._snapshot is None:
            status = "loading sessions…"
        else:
            page_num = self.current_index + 1
            more = "+" if has_more else ""
            prefix = f"{self.header_text} · " if self.header_text else ""
            status = (
                f"{prefix}page {page_num}{more} · "
                f"{len(items)} of {len(filtered)} rows"
            )
        self._render_table(items, status)

    def _render_live(self, items: list[Session], next_cursor: Optional[str]) -> None:
        """Live mode: render whatever the store just returned."""
        page_num = self.current_index + 1
        more = "+" if next_cursor else ""
        prefix = f"{self.header_text} · live · " if self.header_text else "live · "
        status = f"{prefix}page {page_num}{more} · {len(items)} rows"
        self._render_table(items, status)

    def _render_table(self, items: list[Session], status: str) -> None:
        """Common DataTable update. Both render paths share this."""
        table = self.query_one(DataTable)
        table.clear()
        self.sessions_by_id = {s.id: s for s in items}
        for s in items:
            table.add_row(*_row_for(s), key=s.id)
        if table.row_count > 0:
            table.move_cursor(row=0)
        self.query_one("#status", Static).update(status)


# ------------------------------------------------------------------ #
# Row formatting (cell-by-cell so DataTable can align columns nicely)  #
# ------------------------------------------------------------------ #


def _row_for(s: Session) -> tuple[str, str, str, str, str, str]:
    """Return the six cells we render per row.

    Mirrors the data shown by `picker._format_line` but split into cells
    so DataTable can size columns. Title comes from server-populated
    metadata; we never reach into S3 / native files at list time.

    The "project" column shows `repo · subpath` (cross-machine portable)
    when `metadata.repo_url` is set; falls back to a short cwd otherwise.
    """
    from .picker import _human_when, _short_title

    short_id = (s.id or "?")[:8]
    tool = (s.tool or "?")[:7]
    when = _human_when(s.last_active or s.started_at)
    project = _project_label(s)
    events = str(s.event_count)
    title = _short_title(
        s.metadata.get("title") if isinstance(s.metadata, dict) else None
    )
    return short_id, tool, when, project, events, title


def _project_label(s: Session) -> str:
    """Format the project column. Prefers repo identity; falls back to cwd.

    Examples:
      `fleet-sdk · fleet/track`   — repo with subpath
      `fleet-sdk`                 — repo at root
      `fleet-sdk`                 — fallback when no repo metadata (cwd basename)
      `?`                         — unknown
    """
    from .picker import _short_cwd

    md = s.metadata if isinstance(s.metadata, dict) else {}
    repo_url = md.get("repo_url") if isinstance(md, dict) else None
    if isinstance(repo_url, str) and repo_url:
        repo_name = repo_url.rsplit("/", 1)[-1]  # "github.com/org/repo" → "repo"
        subpath = md.get("repo_subpath") if isinstance(md, dict) else None
        if isinstance(subpath, str) and subpath:
            return f"{repo_name} · {subpath}"
        return repo_name
    return _short_cwd(s.cwd)


# ------------------------------------------------------------------ #
# Public entrypoint                                                    #
# ------------------------------------------------------------------ #


def pick_session_textual(
    store,
    *,
    tool: Optional[str] = None,
    cwd: Optional[str] = None,
    since: Optional[str] = None,
    limit: Optional[int] = None,
    header: Optional[str] = None,
) -> Optional[Session]:
    """Open the picker. Returns the chosen `Session`, or None on cancel.

    `limit` defaults to a terminal-readable page size so the user never
    has to scroll within a page. Other filters (`tool`, `cwd`, `since`)
    pass straight to `store.page()`.
    """
    from .picker import _terminal_page_size

    if limit is None:
        limit = _terminal_page_size()
    app = SessionPickerApp(
        store=store,
        tool=tool,
        cwd=cwd,
        since=since,
        limit=limit,
        header=header or "",
    )
    return app.run()


# ------------------------------------------------------------------ #
# Tool picker (stage 2 of resume)                                      #
# ------------------------------------------------------------------ #


class ToolPickerApp(App):
    """Tiny picker for the second stage of `flt track resume` — choose
    which CLI to launch the resumed session in."""

    CSS = """
    #header { dock: top; height: auto; padding: 1; color: $text-muted; }
    OptionList { height: 1fr; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        tools: list[str],
        *,
        source_tool: str,
        header: str = "",
    ) -> None:
        super().__init__()
        self.tools = tools
        self.source_tool = source_tool
        self.header_text = header

    def compose(self) -> ComposeResult:
        from textual.widgets import OptionList
        from textual.widgets.option_list import Option

        if self.header_text:
            yield Static(self.header_text, id="header")
        opts = []
        for t in self.tools:
            label = "(same as source)" if t == self.source_tool else "cross-tool: lossy"
            opts.append(Option(f"{t:<10}  {label}", id=t))
        yield OptionList(*opts, id="tools")
        yield Footer()

    def on_mount(self) -> None:
        from textual.widgets import OptionList

        ol = self.query_one(OptionList)
        ol.focus()
        # Pre-highlight source tool (it's index 0 by construction).
        if self.source_tool in self.tools:
            ol.highlighted = self.tools.index(self.source_tool)

    def on_option_list_option_selected(self, event) -> None:
        self.exit(event.option.id)

    def action_cancel(self) -> None:
        self.exit(None)


def pick_tool_textual(
    source_tool: str,
    *,
    available: Optional[list[str]] = None,
    header: Optional[str] = None,
) -> Optional[str]:
    """Open the tool picker. Returns the chosen tool name, or None on cancel.

    Keeps source_tool first when present so Enter resumes in the same CLI.
    """
    from .picker import installed_tools

    tools = available if available is not None else installed_tools()
    if not tools:
        return None
    # Source-tool first if installed; rest in the canonical order.
    if source_tool in tools:
        ordered = [source_tool] + [t for t in tools if t != source_tool]
    else:
        ordered = list(tools)
    app = ToolPickerApp(tools=ordered, source_tool=source_tool, header=header or "")
    return app.run()
