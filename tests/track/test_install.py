"""Unit tests for install.py — rendering and file writes only, no shelling out."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

from fleet.track.install import (
    PRIVATE_FILE_MODE,
    PLIST_LABEL,
    SYSTEMD_SERVICE,
    _install_launchd,
    _install_systemd,
    _launchd_service_target,
    _launchd_user_domain,
    _write_private_text,
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


def test_render_launchd_plist_excludes_track_base_url_when_unset(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("FLEET_API_KEY", raising=False)
    monkeypatch.delenv("FLEET_TRACK_BASE_URL", raising=False)
    body = render_launchd_plist(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert "FLEET_TRACK_BASE_URL" not in body
    assert "FLEET_API_KEY" not in body


def test_render_launchd_plist_includes_track_base_url_when_set(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("FLEET_API_KEY", raising=False)
    monkeypatch.setenv("FLEET_TRACK_BASE_URL", "https://example.fleetai.com")
    body = render_launchd_plist(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert "FLEET_TRACK_BASE_URL" in body
    assert "https://example.fleetai.com" in body


def test_render_launchd_plist_includes_api_key_when_set(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FLEET_API_KEY", "sk_test")
    monkeypatch.delenv("FLEET_TRACK_BASE_URL", raising=False)
    body = render_launchd_plist(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert "FLEET_API_KEY" in body
    assert "sk_test" in body


def test_render_systemd_unit_has_required_directives(tmp_path: Path):
    body = render_systemd_unit(_paths(tmp_path), flt_path="/usr/local/bin/flt")

    assert "[Unit]" in body
    assert "[Service]" in body
    assert "[Install]" in body
    assert "ExecStart=/usr/local/bin/flt track daemon" in body
    assert "Restart=always" in body
    assert f"append:{tmp_path}/.fleet/track/daemon.log" in body
    assert SYSTEMD_SERVICE  # imported, sanity check


def test_render_systemd_unit_excludes_track_base_url_when_unset(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("FLEET_API_KEY", raising=False)
    monkeypatch.delenv("FLEET_TRACK_BASE_URL", raising=False)
    body = render_systemd_unit(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert "FLEET_TRACK_BASE_URL" not in body
    assert "FLEET_API_KEY" not in body


def test_render_systemd_unit_includes_track_base_url_when_set(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("FLEET_API_KEY", raising=False)
    monkeypatch.setenv("FLEET_TRACK_BASE_URL", "https://dev.example.com")
    body = render_systemd_unit(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert 'Environment="FLEET_TRACK_BASE_URL=https://dev.example.com"' in body


def test_render_systemd_unit_includes_api_key_when_set(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FLEET_API_KEY", "sk_test")
    monkeypatch.delenv("FLEET_TRACK_BASE_URL", raising=False)
    body = render_systemd_unit(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert 'Environment="FLEET_API_KEY=sk_test"' in body


def test_render_systemd_unit_escapes_percent_specifiers(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FLEET_API_KEY", "sk_%team%")
    monkeypatch.delenv("FLEET_TRACK_BASE_URL", raising=False)
    body = render_systemd_unit(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert 'Environment="FLEET_API_KEY=sk_%%team%%"' in body


def test_render_systemd_unit_escapes_quoted_value(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FLEET_API_KEY", 'sk_"quoted"\\path')
    monkeypatch.delenv("FLEET_TRACK_BASE_URL", raising=False)
    body = render_systemd_unit(_paths(tmp_path), flt_path="/usr/local/bin/flt")
    assert 'Environment="FLEET_API_KEY=sk_\\"quoted\\"\\\\path"' in body


def test_write_private_text_uses_user_only_permissions(tmp_path: Path):
    target = tmp_path / "fleet-track.service"
    _write_private_text(target, "secret")

    assert target.read_text() == "secret"
    assert stat.S_IMODE(target.stat().st_mode) == PRIVATE_FILE_MODE


def test_write_private_text_tightens_existing_permissions(tmp_path: Path):
    target = tmp_path / "fleet-track.service"
    target.write_text("old")
    target.chmod(0o644)

    _write_private_text(target, "new")

    assert target.read_text() == "new"
    assert stat.S_IMODE(target.stat().st_mode) == PRIVATE_FILE_MODE


def test_flt_executable_returns_a_string():
    """Don't assert the value (it depends on the venv) but assert the shape."""
    exe = flt_executable()
    assert isinstance(exe, str)
    assert exe  # non-empty


def test_install_launchd_relaunches_existing_service(tmp_path: Path, monkeypatch):
    plist_path = tmp_path / "io.fleet.track.plist"
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("fleet.track.install._launchd_plist_path", lambda: plist_path)
    monkeypatch.setattr("fleet.track.install.flt_executable", lambda: "/bin/flt")
    monkeypatch.setattr("fleet.track.install.subprocess.run", fake_run)

    _install_launchd(_paths(tmp_path))

    assert plist_path.exists()
    assert calls == [
        ["launchctl", "bootout", _launchd_service_target()],
        ["launchctl", "bootout", _launchd_user_domain(), str(plist_path)],
        ["launchctl", "unload", str(plist_path)],
        ["launchctl", "bootstrap", _launchd_user_domain(), str(plist_path)],
        ["launchctl", "kickstart", "-k", _launchd_service_target()],
    ]


def test_install_launchd_falls_back_to_legacy_load(tmp_path: Path, monkeypatch):
    plist_path = tmp_path / "io.fleet.track.plist"
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        returncode = 1 if args[:2] == ["launchctl", "bootstrap"] else 0
        return subprocess.CompletedProcess(args, returncode)

    monkeypatch.setattr("fleet.track.install._launchd_plist_path", lambda: plist_path)
    monkeypatch.setattr("fleet.track.install.flt_executable", lambda: "/bin/flt")
    monkeypatch.setattr("fleet.track.install.subprocess.run", fake_run)

    _install_launchd(_paths(tmp_path))

    assert ["launchctl", "load", str(plist_path)] in calls


def test_install_systemd_restarts_service_after_reload(tmp_path: Path, monkeypatch):
    service_path = tmp_path / "fleet-track.service"
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(
        "fleet.track.install._systemd_service_path", lambda: service_path
    )
    monkeypatch.setattr("fleet.track.install.flt_executable", lambda: "/bin/flt")
    monkeypatch.setattr("fleet.track.install.subprocess.run", fake_run)

    _install_systemd(_paths(tmp_path))

    assert service_path.exists()
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", SYSTEMD_SERVICE],
        ["systemctl", "--user", "restart", SYSTEMD_SERVICE],
    ]


def test_render_paths_use_paths_home(tmp_path: Path):
    """Renderers must use the passed `paths`, not `Path.home()`, so two test runs
    don't collide on the same plist body."""
    a = render_launchd_plist(TrackPaths.under(tmp_path / "a"), "/x/flt")
    b = render_launchd_plist(TrackPaths.under(tmp_path / "b"), "/x/flt")
    assert a != b
    assert str(tmp_path / "a") in a
    assert str(tmp_path / "b") in b
