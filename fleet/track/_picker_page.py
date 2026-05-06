"""fzf-reload helper: emit a page of session lines for the picker.

Invoked by `pick_session` via fzf's `--bind` reload triggers:

  - `change:reload(... --direction query --query {q})` — fired on every
    keystroke; resets to page 0 with the new query string. fzf's own
    fuzzy filtering is `--disabled` so this is the only path that
    surfaces matching rows.
  - `right:reload(... --direction next)` — paginate within the current
    query.
  - `left:reload(... --direction prev)` — go back one page.
  - `alt-h:reload(... --direction first)` — back to page 0.

State file (JSON):

    {
      "source":         "remote" | "local",
      "tool":           Optional[str],
      "cwd":            Optional[str],
      "since":          Optional[str],
      "query":          str,
      "limit":          int,
      "current_index":  int,
      "cursors":        list[str|None]  # cursor used to fetch each page
    }

`cursors[i]` is the cursor passed to `store.page()` to load page `i`.
Bidirectional walks work because cursors are deterministic w.r.t.
their inputs — re-fetching page `i` with `cursors[i]` returns the same
rows (modulo concurrent inserts, which are fine to surface).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state))


def _resolve_store(source: str):
    # Lazy-import so this script stays fast to start. Reuses the CLI's
    # store-resolution so behavior is consistent with the rest of `flt
    # track` (remote default, manually built local index, etc.).
    from .cli import _resolve_session_store

    return _resolve_session_store(source)


def _fetch(state: dict[str, Any], cursor: Any):
    store = _resolve_store(state["source"])
    return store.page(
        tool=state.get("tool"),
        cwd=state.get("cwd"),
        since=state.get("since"),
        query=state.get("query") or None,
        limit=state.get("limit", 20),
        cursor=cursor,
    )


def _emit_page(
    state: dict[str, Any],
    direction: str,
) -> tuple[list[str], dict[str, Any]]:
    """Return (lines, updated_state).

    `direction`:
      - "query" — query already replaced upstream; reset to page 0.
      - "first" — same as query but keep the existing query string.
      - "next"  — advance one page (no-op at last).
      - "prev"  — go back one page (no-op at page 0).
    """
    from .picker import _format_line

    cursors = list(state.get("cursors") or [None])
    idx = state.get("current_index", 0)

    if direction in ("query", "first"):
        # New query (or explicit reset) → page 0 of fresh result set.
        new_idx = 0
        cursors = [None]
    elif direction == "next":
        if idx + 1 < len(cursors):
            new_idx = idx + 1
        else:
            # Need the current page's next_cursor before we can advance.
            current_items, next_cursor = _fetch(state, cursors[idx])
            if next_cursor is None:
                return [_format_line(s) for s in current_items], state
            cursors.append(next_cursor)
            new_idx = idx + 1
    elif direction == "prev":
        if idx == 0:
            return [], state  # already at first page
        new_idx = idx - 1
    else:
        raise SystemExit(f"unknown direction: {direction!r}")

    items, next_cursor = _fetch(state, cursors[new_idx])
    if next_cursor is not None and new_idx + 1 == len(cursors):
        cursors.append(next_cursor)

    lines = [_format_line(s) for s in items]
    new_state = {
        **state,
        "current_index": new_idx,
        "cursors": cursors,
    }
    return lines, new_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Internal helper for fzf reload paging in the track picker.",
    )
    parser.add_argument("--state-file", required=True)
    parser.add_argument(
        "--direction",
        choices=["next", "prev", "first", "query"],
        default="next",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Replaces state.query when --direction=query (else ignored).",
    )
    args = parser.parse_args(argv)

    state_path = Path(args.state_file)
    state = _load_state(state_path)

    if args.direction == "query":
        # `{q}` from fzf may be empty (zero-length query) — treat as no filter.
        state = {**state, "query": args.query or ""}

    lines, new_state = _emit_page(state, args.direction)
    _save_state(state_path, new_state)

    # No-op at boundaries (first/last page, or "next" with nothing more):
    # re-emit the current page so fzf's reload doesn't end up empty.
    if not lines:
        items, _ = _fetch(
            new_state,
            new_state.get("cursors", [None])[new_state.get("current_index", 0)],
        )
        from .picker import _format_line

        lines = [_format_line(s) for s in items]

    sys.stdout.write("\n".join(lines))
    if lines:
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
