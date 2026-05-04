"""Picker tests — only the pure formatting bits.

The actual fzf invocation is exercised manually; piping output through
subprocess in unit tests would couple to fzf availability and is more
trouble than it's worth. (Tool-picker logic is exception: `pick_tool`
takes a `runner` injection so we can verify ordering / labels / cancel.)
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from fleet.track.picker import (
    _format_line,
    _format_tool_line,
    _human_when,
    _short_cwd,
    fzf_available,
    installed_tools,
    pick_tool,
)
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


# ------------------------------------------------------------------ #
# installed_tools                                                      #
# ------------------------------------------------------------------ #


def test_installed_tools_returns_only_binaries_on_path():
    def fake_which(name: str):
        return f"/usr/bin/{name}" if name in {"claude", "codex"} else None

    with mock.patch("fleet.track.picker.shutil.which", side_effect=fake_which):
        assert installed_tools() == ["claude", "codex"]


def test_installed_tools_canonical_order_independent_of_shutil():
    """Even if shutil reports them in a different order, the function
    returns the canonical [claude, codex, cursor, opencode] subset."""
    found = {"opencode", "claude"}
    with mock.patch(
        "fleet.track.picker.shutil.which",
        side_effect=lambda n: "/x" if n in found else None,
    ):
        assert installed_tools() == ["claude", "opencode"]


def test_installed_tools_empty_when_nothing_on_path():
    with mock.patch("fleet.track.picker.shutil.which", return_value=None):
        assert installed_tools() == []


# ------------------------------------------------------------------ #
# _format_tool_line                                                    #
# ------------------------------------------------------------------ #


def test_format_tool_line_marks_source_tool():
    line = _format_tool_line("claude", source_tool="claude")
    assert line.startswith("claude")
    assert "(same as source)" in line


def test_format_tool_line_marks_cross_tool_lossy():
    line = _format_tool_line("codex", source_tool="claude")
    assert line.startswith("codex")
    assert "cross-tool: lossy" in line


# ------------------------------------------------------------------ #
# pick_tool                                                            #
# ------------------------------------------------------------------ #


class _FakeResult:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def _runner_returning(stdout: str, returncode: int = 0):
    """Build a runner callable that records its inputs and returns a
    fixed FakeResult — analogue to subprocess.run for tests."""
    captured: dict[str, Any] = {}

    def runner(args, input, capture_output, text):
        captured["args"] = args
        captured["input"] = input
        return _FakeResult(returncode=returncode, stdout=stdout)

    runner.captured = captured  # type: ignore[attr-defined]
    return runner


@pytest.fixture(autouse=True)
def _force_fzf_available(monkeypatch):
    """Pretend fzf is installed for these tests so they run on any host."""
    monkeypatch.setattr("fleet.track.picker.fzf_available", lambda: True)


def test_pick_tool_returns_chosen_tool():
    runner = _runner_returning("codex      cross-tool: lossy\n")
    out = pick_tool("claude", available=["claude", "codex"], runner=runner)
    assert out == "codex"


def test_pick_tool_returns_none_on_cancel():
    runner = _runner_returning("", returncode=130)  # ctrl-c
    out = pick_tool("claude", available=["claude", "codex"], runner=runner)
    assert out is None


def test_pick_tool_lists_source_tool_first():
    """Source tool must be on the first row so it's the default highlight."""
    runner = _runner_returning("codex      cross-tool: lossy\n")
    pick_tool("codex", available=["claude", "codex", "cursor"], runner=runner)
    lines = runner.captured["input"].splitlines()
    assert lines[0].startswith("codex")
    # Remaining are claude/cursor in canonical order.
    assert lines[1].startswith("claude")
    assert lines[2].startswith("cursor")


def test_pick_tool_falls_back_to_canonical_when_source_not_installed():
    """If the source tool isn't available locally, the picker still
    works — just no '(same as source)' row, all rows are cross-tool."""
    runner = _runner_returning("claude     cross-tool: lossy\n")
    pick_tool("opencode", available=["claude", "codex"], runner=runner)
    lines = runner.captured["input"].splitlines()
    assert lines[0].startswith("claude")
    assert lines[1].startswith("codex")
    assert "cross-tool: lossy" in lines[0]
    assert "cross-tool: lossy" in lines[1]


def test_pick_tool_returns_none_when_no_tools_available():
    runner = _runner_returning("")
    assert pick_tool("claude", available=[], runner=runner) is None


def test_pick_tool_passes_header_to_fzf():
    runner = _runner_returning("claude     (same as source)\n")
    pick_tool(
        "claude",
        available=["claude", "codex"],
        header="Resume abc123 in which tool?",
        runner=runner,
    )
    args = runner.captured["args"]
    assert "--header" in args
    assert args[args.index("--header") + 1] == "Resume abc123 in which tool?"
