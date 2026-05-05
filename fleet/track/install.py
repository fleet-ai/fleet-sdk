"""Install / uninstall the fleet track daemon as an OS service.

Mac:   ~/Library/LaunchAgents/io.fleet.track.plist  (launchd)
Linux: ~/.config/systemd/user/fleet-track.service   (systemd --user)

Each plist/unit refers to the daemon's log file via `TrackPaths`, so tests
that build a `TrackPaths.under(tmp_path)` get a deterministic rendered
unit string they can snapshot without ever shelling out.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .paths import TrackPaths

PLIST_LABEL = "io.fleet.track"
SYSTEMD_SERVICE = "fleet-track"


def flt_executable() -> str:
    """Return the absolute path to the `flt` script the OS service should run.

    Prefer the script co-located with the current Python interpreter (same
    venv) so launchd/systemd don't need to activate the venv themselves.
    """
    candidate = Path(sys.executable).parent / "flt"
    if candidate.exists():
        return str(candidate)
    exe = shutil.which("flt")
    if exe:
        return exe
    return str(candidate)


# ------------------------------------------------------------------ #
# Public API                                                           #
# ------------------------------------------------------------------ #


def install(paths: Optional[TrackPaths] = None) -> None:
    paths = paths or TrackPaths.default()
    system = platform.system()
    if system == "Darwin":
        _install_launchd(paths)
    elif system == "Linux":
        _install_systemd(paths)
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def uninstall() -> None:
    system = platform.system()
    if system == "Darwin":
        _uninstall_launchd()
    elif system == "Linux":
        _uninstall_systemd()


def is_installed() -> bool:
    system = platform.system()
    if system == "Darwin":
        return _launchd_plist_path().exists()
    elif system == "Linux":
        return _systemd_service_path().exists()
    return False


# ------------------------------------------------------------------ #
# Plist / unit string rendering — pure functions, snapshot-testable    #
# ------------------------------------------------------------------ #


def render_launchd_plist(paths: TrackPaths, flt_path: str, env_path: str = "/usr/local/bin:/usr/bin:/bin") -> str:
    """Return the plist XML body. Pure: no filesystem side-effects."""
    extra_env = ""
    if os.environ.get("FLEET_TRACK_BASE_URL"):
        extra_env = (
            f"<key>FLEET_TRACK_BASE_URL</key>"
            f"<string>{os.environ['FLEET_TRACK_BASE_URL']}</string>"
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{flt_path}</string>
        <string>track</string>
        <string>daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{paths.log_file}</string>
    <key>StandardErrorPath</key>
    <string>{paths.log_file}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{env_path}</string>
        <key>HOME</key>
        <string>{paths.home}</string>
        {extra_env}
    </dict>
</dict>
</plist>
"""


def render_systemd_unit(paths: TrackPaths, flt_path: str, env_path: str = "/usr/local/bin:/usr/bin:/bin") -> str:
    """Return the systemd service unit body. Pure: no filesystem side-effects."""
    extra_env = ""
    if os.environ.get("FLEET_TRACK_BASE_URL"):
        extra_env = f"Environment=FLEET_TRACK_BASE_URL={os.environ['FLEET_TRACK_BASE_URL']}"
    return f"""[Unit]
Description=Fleet track daemon — AI session sync
After=network-online.target

[Service]
Type=simple
ExecStart={flt_path} track daemon
Restart=always
RestartSec=5
StandardOutput=append:{paths.log_file}
StandardError=append:{paths.log_file}
Environment=PATH={env_path}
{extra_env}

[Install]
WantedBy=default.target
"""


# ------------------------------------------------------------------ #
# macOS launchd                                                        #
# ------------------------------------------------------------------ #


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def _install_launchd(paths: TrackPaths) -> None:
    paths.ensure_track_dir()
    body = render_launchd_plist(
        paths,
        flt_executable(),
        env_path=os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    )
    plist_path = _launchd_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(body)

    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)


def _uninstall_launchd() -> None:
    plist_path = _launchd_plist_path()
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        plist_path.unlink()


# ------------------------------------------------------------------ #
# Linux systemd --user                                                 #
# ------------------------------------------------------------------ #


def _systemd_service_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{SYSTEMD_SERVICE}.service"


def _install_systemd(paths: TrackPaths) -> None:
    paths.ensure_track_dir()
    body = render_systemd_unit(
        paths,
        flt_executable(),
        env_path=os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    )
    service_path = _systemd_service_path()
    service_path.parent.mkdir(parents=True, exist_ok=True)
    service_path.write_text(body)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", SYSTEMD_SERVICE], check=True)


def _uninstall_systemd() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", SYSTEMD_SERVICE], capture_output=True)
    _systemd_service_path().unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
