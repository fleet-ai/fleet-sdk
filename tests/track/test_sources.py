"""Unit tests for the sources package."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.track.sources import (
    DEFAULT_EXCLUDE_PATTERNS,
    ClaudeDesktopSource,
    ClaudeSource,
    CodexSource,
    CursorSource,
    Source,
    SourceSummary,
    default_sources,
    relative_to_home,
)


# ------------------------------------------------------------------ #
# Fixture helpers                                                      #
# ------------------------------------------------------------------ #


def _seed_claude(home: Path) -> None:
    base = home / ".claude" / "projects" / "-some-cwd"
    base.mkdir(parents=True)
    (base / "abc.jsonl").write_text('{"role": "user"}\n')
    (base / "session-env").write_text("FOO=bar")  # excluded


def _seed_claude_desktop(home: Path, app_name: str = "Claude") -> Path:
    base = (
        home
        / "Library"
        / "Application Support"
        / app_name
        / "local-agent-mode-sessions"
        / "account"
        / "workspace"
        / "local_11111111-2222-3333-4444-555555555555"
        / ".claude"
        / "projects"
        / "-desktop-cwd"
    )
    base.mkdir(parents=True)
    f = base / "22222222-3333-4444-5555-666666666666.jsonl"
    f.write_text('{"type": "user"}\n')
    return f


def _seed_cursor(home: Path) -> None:
    base = home / ".cursor" / "projects" / "p1" / "agent-transcripts" / "t1"
    base.mkdir(parents=True)
    (base / "session.jsonl").write_text('{"x": 1}\n')
    (base / "session.txt").write_text("flat text")


def _seed_codex(home: Path) -> None:
    sessions = home / ".codex" / "sessions" / "2026" / "04" / "30"
    archived = home / ".codex" / "archived_sessions"
    sessions.mkdir(parents=True)
    archived.mkdir(parents=True)
    (sessions / "rollout-x.jsonl").write_text('{"type": "session_meta"}\n')
    (archived / "rollout-old.jsonl").write_text('{"type": "session_meta"}\n')


# ------------------------------------------------------------------ #
# relative_to_home                                                     #
# ------------------------------------------------------------------ #


def test_relative_to_home_with_explicit_home(tmp_path: Path):
    p = tmp_path / "a" / "b.txt"
    assert relative_to_home(p, tmp_path) == "a/b.txt"


def test_relative_to_home_raises_for_path_outside_home(tmp_path: Path):
    with pytest.raises(ValueError):
        relative_to_home(Path("/elsewhere/x.txt"), tmp_path)


# ------------------------------------------------------------------ #
# ClaudeSource                                                         #
# ------------------------------------------------------------------ #


def test_claude_is_present_after_seed(tmp_path: Path):
    s = ClaudeSource(home=tmp_path)
    assert s.is_present() is False

    _seed_claude(tmp_path)
    assert s.is_present() is True


def test_claude_iter_files_finds_jsonl_skips_excluded(tmp_path: Path):
    _seed_claude(tmp_path)
    s = ClaudeSource(home=tmp_path)
    files = list(s.iter_files())
    assert len(files) == 1
    assert files[0].name == "abc.jsonl"


def test_claude_read_for_upload_trims_partial_jsonl_line(tmp_path: Path):
    _seed_claude(tmp_path)
    s = ClaudeSource(home=tmp_path)
    f = next(s.iter_files())
    f.write_text('{"a": 1}\n{"partial":')  # mid-write
    assert s.read_for_upload(f) == b'{"a": 1}\n'


# ------------------------------------------------------------------ #
# ClaudeDesktopSource                                                  #
# ------------------------------------------------------------------ #


def test_claude_desktop_iter_files_finds_embedded_project_jsonl(tmp_path: Path):
    expected = _seed_claude_desktop(tmp_path)
    s = ClaudeDesktopSource(home=tmp_path)

    assert s.is_present() is True
    assert list(s.iter_files()) == [expected]


def test_claude_desktop_checks_3p_root_too(tmp_path: Path):
    expected = _seed_claude_desktop(tmp_path, app_name="Claude-3p")
    s = ClaudeDesktopSource(home=tmp_path)

    assert s.is_present() is True
    assert list(s.iter_files()) == [expected]


def test_claude_desktop_skips_non_session_embedded_claude_dirs(tmp_path: Path):
    base = (
        tmp_path
        / "Library"
        / "Application Support"
        / "Claude"
        / "local-agent-mode-sessions"
        / "account"
        / "workspace"
        / "not-a-session"
        / ".claude"
        / "projects"
        / "-desktop-cwd"
    )
    base.mkdir(parents=True)
    (base / "22222222-3333-4444-5555-666666666666.jsonl").write_text("{}\n")

    assert list(ClaudeDesktopSource(home=tmp_path).iter_files()) == []


# ------------------------------------------------------------------ #
# CursorSource                                                         #
# ------------------------------------------------------------------ #


def test_cursor_finds_both_jsonl_and_txt(tmp_path: Path):
    _seed_cursor(tmp_path)
    s = CursorSource(home=tmp_path)
    files = sorted(f.name for f in s.iter_files())
    assert files == ["session.jsonl", "session.txt"]


def test_cursor_read_for_upload_only_trims_jsonl(tmp_path: Path):
    _seed_cursor(tmp_path)
    s = CursorSource(home=tmp_path)
    files = {f.name: f for f in s.iter_files()}

    files["session.txt"].write_text("flat text without newline")
    assert s.read_for_upload(files["session.txt"]) == b"flat text without newline"

    files["session.jsonl"].write_text('{"a":1}\n{"partial":')
    assert s.read_for_upload(files["session.jsonl"]) == b'{"a":1}\n'


# ------------------------------------------------------------------ #
# CodexSource                                                          #
# ------------------------------------------------------------------ #


def test_codex_iter_yields_sessions_and_archived(tmp_path: Path):
    _seed_codex(tmp_path)
    s = CodexSource(home=tmp_path)
    files = list(s.iter_files())
    assert len(files) == 2
    paths = {str(f.relative_to(tmp_path)) for f in files}
    assert any("sessions/2026/04/30/rollout-x.jsonl" in p for p in paths)
    assert any("archived_sessions/rollout-old.jsonl" in p for p in paths)


def test_codex_is_present_when_only_sessions_exists(tmp_path: Path):
    (tmp_path / ".codex" / "sessions").mkdir(parents=True)
    assert CodexSource(home=tmp_path).is_present() is True


def test_codex_is_present_when_only_archived_exists(tmp_path: Path):
    (tmp_path / ".codex" / "archived_sessions").mkdir(parents=True)
    assert CodexSource(home=tmp_path).is_present() is True


def test_codex_is_absent_when_neither_exists(tmp_path: Path):
    (tmp_path / ".codex").mkdir(parents=True)  # only the parent
    assert CodexSource(home=tmp_path).is_present() is False


# ------------------------------------------------------------------ #
# Source.summary                                                       #
# ------------------------------------------------------------------ #


def test_summary_when_absent(tmp_path: Path):
    s = ClaudeSource(home=tmp_path)
    assert s.summary() == SourceSummary(name="claude", found=False)


def test_summary_when_present_counts_files_and_bytes(tmp_path: Path):
    _seed_claude(tmp_path)
    s = ClaudeSource(home=tmp_path)
    summary = s.summary()
    assert summary.found is True
    assert summary.files == 1
    assert summary.bytes > 0
    assert summary.newest_mtime is not None


# ------------------------------------------------------------------ #
# parse / serialize stubs                                              #
# ------------------------------------------------------------------ #


def test_serialize_returns_bytes(tmp_path: Path):
    """`serialize` is implemented for claude/codex; cursor still raises
    NotImplementedError until we have sample data."""
    s = ClaudeSource(home=tmp_path)
    out = s.serialize([])
    assert out == b""

    cursor = CursorSource(home=tmp_path)
    with pytest.raises(NotImplementedError):
        cursor.serialize([])


# ------------------------------------------------------------------ #
# default_sources                                                      #
# ------------------------------------------------------------------ #


def test_default_sources_returns_indexable_sources(tmp_path: Path):
    sources = default_sources(home=tmp_path)
    names = [s.name for s in sources]
    assert names == ["claude", "claude-desktop", "codex", "cursor"]


def test_default_sources_use_provided_home(tmp_path: Path):
    sources = default_sources(home=tmp_path)
    assert all(str(s.root).startswith(str(tmp_path)) for s in sources)


def test_exclude_patterns_is_immutable():
    assert isinstance(DEFAULT_EXCLUDE_PATTERNS, frozenset)
    assert "session-env" in DEFAULT_EXCLUDE_PATTERNS


def test_source_is_abstract():
    """Source ABC cannot be instantiated directly."""
    with pytest.raises(TypeError):
        Source()  # type: ignore[abstract]
