"""Picker tests — only the pure formatting bits.

The actual fzf invocation is exercised manually; piping output through
subprocess in unit tests would couple to fzf availability and is more
trouble than it's worth.
"""

from __future__ import annotations

from fleet.track.picker import _format_line, _human_when, _short_cwd, fzf_available
from fleet.track.store import Session


# ------------------------------------------------------------------ #
# _short_cwd                                                           #
# ------------------------------------------------------------------ #


def test_short_cwd_takes_basename():
    assert _short_cwd("/Users/me/git/fleet-sdk") == "fleet-sdk"


def test_short_cwd_handles_root():
    assert _short_cwd("/") == "?"


def test_short_cwd_none():
    assert _short_cwd(None) == "?"


def test_short_cwd_truncates_long_basenames():
    long_name = "a" * 50
    out = _short_cwd(f"/x/{long_name}")
    assert len(out) == 30


# ------------------------------------------------------------------ #
# _human_when                                                          #
# ------------------------------------------------------------------ #


def test_human_when_seconds():
    from datetime import datetime, timezone, timedelta
    ts = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    out = _human_when(ts)
    assert "s ago" in out


def test_human_when_minutes():
    from datetime import datetime, timezone, timedelta
    ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    out = _human_when(ts)
    assert "m ago" in out


def test_human_when_hours():
    from datetime import datetime, timezone, timedelta
    ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    out = _human_when(ts)
    assert "h ago" in out


def test_human_when_handles_z_suffix():
    from datetime import datetime, timezone, timedelta
    ts = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    out = _human_when(ts)
    assert "ago" in out


def test_human_when_unparseable():
    out = _human_when("not a timestamp")
    assert out  # returned something, didn't raise


def test_human_when_none():
    assert _human_when(None) == ""


# ------------------------------------------------------------------ #
# _format_line                                                         #
# ------------------------------------------------------------------ #


def test_format_line_starts_with_short_id():
    s = Session(id="abcd1234-5678", tool="claude", cwd="/x")
    line = _format_line(s)
    assert line.startswith("abcd1234")


def test_format_line_marks_forks():
    s = Session(id="x", tool="claude", forked_from="parent", fork_point=10)
    line = _format_line(s)
    assert "↳" in line


def test_format_line_no_fork_marker_for_root():
    s = Session(id="x", tool="claude")
    line = _format_line(s)
    assert "↳" not in line


def test_format_line_includes_tool():
    s = Session(id="x", tool="codex")
    assert "codex" in _format_line(s)


def test_format_line_includes_event_count():
    s = Session(id="x", tool="claude", event_count=42)
    assert "42e" in _format_line(s)


# ------------------------------------------------------------------ #
# fzf availability check                                               #
# ------------------------------------------------------------------ #


def test_fzf_available_returns_bool():
    """Doesn't matter if it's True or False on the test machine, just
    that the call doesn't raise."""
    assert isinstance(fzf_available(), bool)
