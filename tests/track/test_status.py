"""Unit tests for status.py."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fleet.track.paths import TrackPaths
from fleet.track.status import (
    STATUS_SCHEMA_VERSION,
    TrackStatus,
    clear_pid,
    is_running,
    read_status,
    write_pid,
    write_status,
)


def _paths(tmp_path: Path) -> TrackPaths:
    return TrackPaths.under(tmp_path)


def test_write_and_clear_pid(tmp_path: Path):
    paths = _paths(tmp_path)
    write_pid(paths)
    assert paths.pid_file.read_text() == str(os.getpid())
    clear_pid(paths)
    assert not paths.pid_file.exists()


def test_clear_pid_no_file_is_noop(tmp_path: Path):
    paths = _paths(tmp_path)
    paths.ensure_track_dir()
    clear_pid(paths)  # must not raise


def test_is_running_no_pid_file(tmp_path: Path):
    assert is_running(_paths(tmp_path)) is False


def test_is_running_with_dead_pid(tmp_path: Path):
    paths = _paths(tmp_path)
    paths.ensure_track_dir()
    paths.pid_file.write_text("99999999")  # almost certainly dead
    assert is_running(paths) is False


def test_is_running_with_garbage_pid(tmp_path: Path):
    paths = _paths(tmp_path)
    paths.ensure_track_dir()
    paths.pid_file.write_text("not-a-number")
    assert is_running(paths) is False


def test_is_running_with_self(tmp_path: Path):
    paths = _paths(tmp_path)
    write_pid(paths)
    assert is_running(paths) is True


def test_write_and_read_status(tmp_path: Path):
    paths = _paths(tmp_path)
    s = TrackStatus(pid=1234, state="syncing", queue_depth=5, files_total=10)
    write_status(paths, s)
    loaded = read_status(paths)
    assert loaded is not None
    assert loaded.pid == 1234
    assert loaded.state == "syncing"
    assert loaded.queue_depth == 5
    assert loaded.files_total == 10
    assert loaded.updated_at != ""  # set by write_status
    assert loaded.schema_version == STATUS_SCHEMA_VERSION


def test_read_status_missing_file(tmp_path: Path):
    assert read_status(_paths(tmp_path)) is None


def test_read_status_corrupt_file(tmp_path: Path):
    paths = _paths(tmp_path)
    paths.ensure_track_dir()
    paths.status_file.write_text("not json{{")
    assert read_status(paths) is None


def test_read_status_ignores_unknown_fields(tmp_path: Path):
    """A newer daemon adding a field shouldn't crash an older CLI."""
    paths = _paths(tmp_path)
    paths.ensure_track_dir()
    paths.status_file.write_text(
        json.dumps({"pid": 1, "state": "idle", "future_field": "surprise"})
    )
    s = read_status(paths)
    assert s is not None
    assert s.pid == 1


def test_write_status_atomic_no_temp_files_left(tmp_path: Path):
    paths = _paths(tmp_path)
    write_status(paths, TrackStatus())
    leftovers = list(paths.track_dir.glob(".status-*"))
    assert leftovers == []
