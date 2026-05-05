"""fzf-based session picker.

We hard-require fzf (per design decision). If it's not installed, the
picker raises a helpful error suggesting `brew install fzf`. Building a
fallback Python TUI was considered and rejected — fzf is mature, fast,
and ubiquitous; the maintenance cost of a second picker isn't worth the
edge case.

Usage:

    from fleet.track.picker import pick_session
    selected = pick_session(sessions, header="Resume which session?")
    if selected is None:
        return  # user cancelled

The picker streams a one-line-per-session summary into fzf's stdin and
reads the user's choice back from stdout. Each line carries a stable
prefix (the session id) so we can map the choice back to a `Session`
object without parsing the human-readable parts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .store import Session


class FzfNotInstalled(RuntimeError):
    """Raised when fzf is required but not on PATH."""

    DEFAULT_HINT = (
        "fzf is required for the interactive picker. Install with "
        "`brew install fzf` (mac) or `apt install fzf` (debian/ubuntu), "
        "or pass an explicit session id (e.g. `flt track resume <id>`)."
    )

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(message or self.DEFAULT_HINT)


def fzf_available() -> bool:
    return shutil.which("fzf") is not None


# Tool-name → binary-name map for `installed_tools()` PATH detection.
# Order is the canonical sort order in the picker when no source is set.
_TOOL_BINARIES: list[tuple[str, str]] = [
    ("claude", "claude"),
    ("codex", "codex"),
    ("cursor", "cursor"),
    ("opencode", "opencode"),
]


def installed_tools() -> list[str]:
    """Return the names of supported AI CLIs whose binary is on `PATH`.

    Used by the second-stage picker to hide tools the user couldn't actually
    launch into. Order matches `_TOOL_BINARIES` (claude, codex, cursor,
    opencode) so the picker is deterministic regardless of $PATH ordering.
    """
    return [name for name, binary in _TOOL_BINARIES if shutil.which(binary)]


def pick_tool(
    source_tool: str,
    *,
    available: Optional[list[str]] = None,
    header: Optional[str] = None,
    runner=None,
) -> Optional[str]:
    """Show a second-stage fzf picker for the target tool.

    `source_tool` highlights as the default (`(same as source)`); the rest
    are labelled `cross-tool: lossy` so the user knows the conversion is
    best-effort. Returns the chosen tool name, or None on cancel.

    `available` defaults to `installed_tools()`. `runner` is the
    subprocess-style callable injected by tests (defaults to
    `subprocess.run`); kept narrow because we only need stdin/stdout/return.
    """
    if not fzf_available():
        raise FzfNotInstalled()

    tools = available if available is not None else installed_tools()
    if not tools:
        return None

    # Source-tool first if installed; rest in canonical order.
    if source_tool in tools:
        ordered = [source_tool] + [t for t in tools if t != source_tool]
    else:
        ordered = list(tools)

    lines = [_format_tool_line(t, source_tool) for t in ordered]

    args = ["fzf", "--prompt", "tool> ", "--ansi", "--no-multi"]
    if header:
        args.extend(["--header", header])

    run = runner or subprocess.run
    result = run(args, input="\n".join(lines), capture_output=True, text=True)
    if result.returncode != 0:
        return None

    chosen = result.stdout.strip()
    if not chosen:
        return None
    # First whitespace-delimited token is the tool name.
    return chosen.split(None, 1)[0]


def _format_tool_line(tool: str, source_tool: str) -> str:
    """One row in the tool picker. First token is the tool name (used to
    map back to a string after fzf returns)."""
    label = "(same as source)" if tool == source_tool else "cross-tool: lossy"
    return f"{tool:<10}  {label}"


@dataclass(frozen=True)
class PageState:
    """Initial state for cursor-paged fzf picking. Persists to a temp
    file so fzf's reload-bound subcommand can advance / rewind / re-query
    across keypresses.

    The same struct serializes to the JSON state file consumed by
    `fleet.track._picker_page` — keep field names aligned.
    """

    source: str        # `--source` value the parent picker was opened with
    tool: Optional[str] = None
    cwd: Optional[str] = None
    since: Optional[str] = None
    query: str = ""
    limit: int = 20

    def to_state(self, *, current_index: int = 0,
                 cursors: Optional[list] = None) -> dict:
        return {
            "source": self.source,
            "tool": self.tool,
            "cwd": self.cwd,
            "since": self.since,
            "query": self.query,
            "limit": self.limit,
            "current_index": current_index,
            "cursors": cursors or [None],
        }


def _terminal_page_size(*, min_size: int = 8, max_size: int = 50) -> int:
    """Derive a sensible page size from the current terminal height.

    Reserve room for fzf's chrome (header line, prompt, status, a few
    rows of breathing space). Falls back to a sane default when stdout
    isn't a tty (`shutil.get_terminal_size()` returns the env defaults
    in that case, which is fine).
    """
    rows = shutil.get_terminal_size((80, 24)).lines
    return max(min_size, min(rows - 6, max_size))


def pick_session(
    sessions: Iterable[Session],
    *,
    header: Optional[str] = None,
    prompt: str = "session> ",
    page_state: Optional[PageState] = None,
) -> Optional[Session]:
    """Show an fzf picker; return the chosen Session, or None if cancelled.

    Raises `FzfNotInstalled` if fzf isn't on PATH.

    `page_state`: opt-in cursor pagination. When provided, right-arrow
    advances to the next page and left-arrow steps back. fzf's normal
    right/left = move-cursor-in-query is overridden in that case;
    pressing them while typing a query reloads to the next/previous
    page. When omitted, the full `sessions` iterable is buffered eagerly
    (existing behavior).
    """
    if not fzf_available():
        raise FzfNotInstalled()

    # Build picker lines + a parallel index back to the Session objects.
    sessions_list = list(sessions)
    if not sessions_list:
        return None

    lines = [_format_line(s) for s in sessions_list]
    by_id = {s.id: s for s in sessions_list}

    args = ["fzf", "--prompt", prompt, "--ansi", "--no-multi"]
    if header:
        args.extend(["--header", header])

    state_path: Optional[Path] = None
    if page_state is not None:
        # Server-side search pattern: fzf is `--disabled` (no native
        # filtering); every keystroke triggers `change:reload` which
        # re-queries the store with the new query string. Right/left
        # arrows page within the current query. Pages are sized for the
        # terminal so the user never has to scroll within a page.
        state_path = _make_state_file(page_state)
        helper = (
            f'{_shell_quote(sys.executable)} -m fleet.track._picker_page '
            f'--state-file {_shell_quote(str(state_path))}'
        )
        args.extend([
            "--disabled",
            "--bind", f"change:reload({helper} --direction query --query {{q}})",
            "--bind", f"right:reload({helper} --direction next)",
            "--bind", f"left:reload({helper} --direction prev)",
            "--bind", f"alt-h:reload({helper} --direction first)",
        ])

    try:
        result = subprocess.run(
            args,
            input="\n".join(lines),
            capture_output=True,
            text=True,
        )
    finally:
        if state_path is not None:
            try:
                state_path.unlink()
            except OSError:
                pass

    if result.returncode != 0:
        # 1 = no match, 130 = ctrl-c. Either way, user cancelled.
        return None

    chosen = result.stdout.strip()
    if not chosen:
        return None

    # First column is the session id (8-char prefix kept in line for
    # disambiguation); we look it up by exact id from the line.
    chosen_id = chosen.split(None, 1)[0]
    # The id printed is a prefix; the chosen row may have come from a
    # later page that isn't in our local lookup. Best-effort: try the
    # in-memory map first; fall back to letting the caller resolve via
    # store.get(prefix). To avoid false positives, return None and let
    # the resume flow handle it.
    for sid, s in by_id.items():
        if sid.startswith(chosen_id):
            return s
    # Synthesize a minimal Session from the picked id so the caller can
    # resolve via store.get(). The CLI does that anyway and provides a
    # better error if not found.
    return Session(id=chosen_id, tool="?")


def _make_state_file(page_state: "PageState") -> Path:
    """Write the initial paging state to a tempfile and return its path.
    Caller is responsible for unlinking when fzf exits."""
    fd, name = tempfile.mkstemp(prefix="flt-track-picker-", suffix=".json")
    os.close(fd)
    path = Path(name)
    path.write_text(json.dumps(page_state.to_state()))
    return path


def _shell_quote(s: str) -> str:
    """Quote a single argument for inclusion in a shell command string.
    fzf's `--bind ...:reload(<cmd>)` parses <cmd> as a shell command, so
    paths with spaces need quoting. Single quotes work for everything
    except literal single quotes themselves."""
    if not s:
        return "''"
    if "'" not in s:
        return f"'{s}'"
    # Escape embedded single quotes the POSIX way.
    return "'" + s.replace("'", "'\\''") + "'"


def _format_line(s: Session) -> str:
    """Render one fzf row.

    Format: `<short-id>  <tool:7>  <when:14>  <cwd-basename:30>  <events>e  <title>`

    Stays under 200 chars so fzf rendering is snappy. The first
    whitespace-delimited token is the short id; the picker uses it to
    map back to the Session object.

    Title comes from `s.metadata.get("title")` — server-populated. We
    deliberately avoid fetching from S3 or scanning native session files
    at list time; an empty title is fine until the daemon learns to
    write it through the metadata index.
    """
    short_id = (s.id or "?")[:8]
    tool = (s.tool or "?")[:7].ljust(7)
    when = _human_when(s.last_active or s.started_at)
    cwd_short = _short_cwd(s.cwd)
    fork_marker = " ↳" if s.forked_from else "  "
    title = _short_title(s.metadata.get("title") if isinstance(s.metadata, dict) else None)
    line = f"{short_id}  {tool}  {when:>14}  {cwd_short:<30}{fork_marker} {s.event_count:>4}e  {title}"
    return line.rstrip()  # no trailing whitespace; keeps stream-compare tests honest


def _short_title(title: Optional[str], *, max_len: int = 60) -> str:
    """Single-line, length-capped rendering for the picker. Newlines and
    runs of whitespace collapse to one space so titles don't break the row."""
    if not title:
        return ""
    flattened = " ".join(title.split())
    if len(flattened) > max_len:
        return flattened[: max_len - 1] + "…"
    return flattened


def _short_cwd(cwd: Optional[str]) -> str:
    """`/Users/me/git/fleet-sdk` → `fleet-sdk`. None or empty → '?'."""
    if not cwd:
        return "?"
    parts = [p for p in cwd.rstrip("/").split("/") if p]
    if not parts:
        return "?"
    last = parts[-1]
    return last[:30] if len(last) > 30 else last


def _human_when(ts: Optional[str]) -> str:
    """Render an ISO-8601 timestamp as `5m ago` / `2h ago` / etc.

    Returns the raw string if we can't parse it; never raises.
    """
    if not ts:
        return ""
    from datetime import datetime, timezone

    try:
        # Tolerate `Z` suffix and `+00:00` form.
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return ts[:14]

    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "future"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    if days < 30:
        return f"{days}d ago"
    return ts[:10]
