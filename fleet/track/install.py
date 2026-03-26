"""Install / uninstall the fleet track daemon as an OS service.

Mac:  ~/Library/LaunchAgents/io.fleet.track.plist  (launchd)
Linux: ~/.config/systemd/user/fleet-track.service  (systemd --user)
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PLIST_LABEL = "io.fleet.track"
SYSTEMD_SERVICE = "fleet-track"
TRACK_DIR = Path.home() / ".fleet" / "track"
LOG_FILE = TRACK_DIR / "daemon.log"


def _flt_executable() -> str:
    # Prefer the flt script co-located with the current Python interpreter
    # (same venv) so launchd/systemd don't need to activate the venv.
    candidate = Path(sys.executable).parent / "flt"
    if candidate.exists():
        return str(candidate)
    exe = shutil.which("flt")
    if exe:
        return exe
    return str(candidate)


def install() -> None:
    system = platform.system()
    if system == "Darwin":
        _install_launchd()
    elif system == "Linux":
        _install_systemd()
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
# macOS launchd                                                        #
# ------------------------------------------------------------------ #

def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def _install_launchd() -> None:
    TRACK_DIR.mkdir(parents=True, exist_ok=True)
    flt = _flt_executable()
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{flt}</string>
        <string>track</string>
        <string>daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_FILE}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}</string>
        <key>HOME</key>
        <string>{Path.home()}</string>
        {f"<key>FLEET_TRACK_BASE_URL</key><string>{os.environ['FLEET_TRACK_BASE_URL']}</string>" if os.environ.get("FLEET_TRACK_BASE_URL") else ""}
    </dict>
</dict>
</plist>
"""
    plist_path = _launchd_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist)

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


def _install_systemd() -> None:
    TRACK_DIR.mkdir(parents=True, exist_ok=True)
    flt = _flt_executable()
    unit = f"""[Unit]
Description=Fleet track daemon — AI session sync
After=network-online.target

[Service]
Type=simple
ExecStart={flt} track daemon
Restart=always
RestartSec=5
StandardOutput=append:{LOG_FILE}
StandardError=append:{LOG_FILE}
Environment=PATH={os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
{f'Environment=FLEET_TRACK_BASE_URL={os.environ["FLEET_TRACK_BASE_URL"]}' if os.environ.get("FLEET_TRACK_BASE_URL") else ""}

[Install]
WantedBy=default.target
"""
    service_path = _systemd_service_path()
    service_path.parent.mkdir(parents=True, exist_ok=True)
    service_path.write_text(unit)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", SYSTEMD_SERVICE], check=True)


def _uninstall_systemd() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", SYSTEMD_SERVICE], capture_output=True)
    _systemd_service_path().unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
