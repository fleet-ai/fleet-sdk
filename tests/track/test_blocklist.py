"""Tests for FleetTrack local upload blocklist."""

from __future__ import annotations

from fleet.track.blocklist import (
    TrackBlocklist,
    add_blocked_session_ids,
    read_track_config,
    remove_blocked_session_ids,
)
from fleet.track.paths import TrackPaths


def test_blocklist_matches_claude_session_filename():
    blocklist = TrackBlocklist.from_config(
        {"blocked_session_ids": ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]}
    )

    assert blocklist.is_blocked_path(
        ".claude/projects/x/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jsonl"
    )


def test_blocklist_matches_codex_session_suffix():
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    blocklist = TrackBlocklist.from_config({"blocked_session_ids": [sid]})

    assert blocklist.is_blocked_path(
        f".codex/sessions/2026/05/06/rollout-2026-05-06T00-00-00-{sid}.jsonl"
    )


def test_blocklist_matches_exact_paths_and_globs():
    blocklist = TrackBlocklist.from_config(
        {
            "blocked_paths": [".cursor/projects/p/session.txt"],
            "blocked_path_globs": [
                "Library/Application Support/Claude/**/secret.jsonl"
            ],
        }
    )

    assert blocklist.is_blocked_path("/.cursor/projects/p/session.txt")
    assert blocklist.is_blocked_path(
        "Library/Application Support/Claude/local-agent-mode-sessions/x/secret.jsonl"
    )
    assert not blocklist.is_blocked_path(".cursor/projects/p/other.txt")


def test_add_and_remove_blocked_session_ids(tmp_path):
    paths = TrackPaths.under(tmp_path)

    added = add_blocked_session_ids(paths, ["s1", "s2", "s1"])
    assert added == ["s1", "s2"]
    assert read_track_config(paths)["blocked_session_ids"] == ["s1", "s2"]

    removed = remove_blocked_session_ids(paths, ["s2", "missing"])
    assert removed == ["s2"]
    assert read_track_config(paths)["blocked_session_ids"] == ["s1"]
