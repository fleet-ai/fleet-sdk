"""Unit tests for install.py — pure rendering only, no shelling out."""

from __future__ import annotations

from pathlib import Path

from fleet.track.install import (
    PLIST_LABEL,
    SYSTEMD_SERVICE,
    flt_executable,
    render_launchd_plist,
    render_systemd_unit,
)
from fleet.track.paths import TrackPaths


def _paths(tmp_path: Path) -> TrackPaths:
    return TrackPaths.under(tmp_path)


def test_render_launchd_plist_has_required_keys(tmp_path: Path):
    body = render_launchd_plist(_paths(tmp_path), flt_path="/usr/local/bin/flt")

    assert PLIST_LABEL in body
    assert "/usr/local/bin/flt" in body
    assert "<key>RunAtLoad</key>" in body
    assert "<true/>" in body
    assert "<key>KeepAlive</key>" in body
    assert str(tmp_path / ".fleet" / "track" / "daemon.log") in body
    assert "<key>HOME</key>" in body
    assert str(tmp_path) in body


def test_render_launchd_plist_excludes_track_base_url_when_unset(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FLEET_TRACK_BASE_URL", raising=False)
    body = render_launchd_plist(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert "FLEET_TRACK_BASE_URL" not in body


def test_render_launchd_plist_includes_track_base_url_when_set(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FLEET_TRACK_BASE_URL", "https://example.fleetai.com")
    body = render_launchd_plist(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert "FLEET_TRACK_BASE_URL" in body
    assert "https://example.fleetai.com" in body


def test_render_systemd_unit_has_required_directives(tmp_path: Path):
    body = render_systemd_unit(_paths(tmp_path), flt_path="/usr/local/bin/flt")

    assert "[Unit]" in body
    assert "[Service]" in body
    assert "[Install]" in body
    assert "ExecStart=/usr/local/bin/flt track daemon" in body
    assert "Restart=always" in body
    assert f"append:{tmp_path}/.fleet/track/daemon.log" in body
    assert SYSTEMD_SERVICE  # imported, sanity check


def test_render_systemd_unit_excludes_track_base_url_when_unset(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FLEET_TRACK_BASE_URL", raising=False)
    body = render_systemd_unit(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert "FLEET_TRACK_BASE_URL" not in body


def test_render_systemd_unit_includes_track_base_url_when_set(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FLEET_TRACK_BASE_URL", "https://dev.example.com")
    body = render_systemd_unit(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert "Environment=FLEET_TRACK_BASE_URL=https://dev.example.com" in body


def test_flt_executable_returns_a_string():
    """Don't assert the value (it depends on the venv) but assert the shape."""
    exe = flt_executable()
    assert isinstance(exe, str)
    assert exe  # non-empty


def test_render_paths_use_paths_home(tmp_path: Path):
    """Renderers must use the passed `paths`, not `Path.home()`, so two test runs
    don't collide on the same plist body."""
    a = render_launchd_plist(TrackPaths.under(tmp_path / "a"), "/x/flt")
    b = render_launchd_plist(TrackPaths.under(tmp_path / "b"), "/x/flt")
    assert a != b
    assert str(tmp_path / "a") in a
    assert str(tmp_path / "b") in b
