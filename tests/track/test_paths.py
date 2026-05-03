"""Unit tests for TrackPaths."""

from __future__ import annotations

from pathlib import Path

from fleet.track.paths import TrackPaths


def test_default_uses_home():
    paths = TrackPaths.default()
    assert paths.home == Path.home()
    assert paths.track_dir == Path.home() / ".fleet" / "track"


def test_under_roots_everything_at_given_dir(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    assert paths.home == tmp_path
    assert paths.track_dir == tmp_path / ".fleet" / "track"
    assert paths.state_db == tmp_path / ".fleet" / "track" / "state.db"
    assert paths.status_file == tmp_path / ".fleet" / "track" / "status.json"
    assert paths.pid_file == tmp_path / ".fleet" / "track" / "daemon.pid"
    assert paths.log_file == tmp_path / ".fleet" / "track" / "daemon.log"
    assert paths.config_file == tmp_path / ".fleet" / "track" / "config.json"
    assert paths.credentials_file == tmp_path / ".fleet" / "credentials.json"


def test_under_does_not_create_directories(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    assert not paths.track_dir.exists()


def test_ensure_track_dir_creates_and_is_idempotent(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()
    assert paths.track_dir.is_dir()
    paths.ensure_track_dir()  # second call must not raise
    assert paths.track_dir.is_dir()


def test_frozen_dataclass_is_immutable(tmp_path: Path):
    import dataclasses

    paths = TrackPaths.under(tmp_path)
    try:
        paths.home = tmp_path / "elsewhere"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("TrackPaths should be frozen")
