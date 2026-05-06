"""Install the FleetCode MCP server into local agent client configs.

Supports three clients, all stdio + `flt login` auth:

  - claude-code     ~/.claude.json                                       (JSON)
  - claude-desktop  ~/Library/Application Support/Claude/                (JSON)
  - codex           ~/.codex/config.toml                                 (TOML)

The writers are idempotent and atomic: existing keys outside `mcpServers`
(or `mcp_servers` for Codex) are preserved exactly, and writes go through
a temp file + rename. TOML formatting/comments are preserved via tomlkit.

`tomlkit` is imported lazily inside the Codex writer so the rest of the
SDK does not require it.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

ENTRY_NAME = "fleetcode"

CLIENT_CHOICES = ("claude-code", "claude-desktop", "codex")


@dataclass(frozen=True)
class CommandSpec:
    """Stdio launch spec written into client configs."""

    command: str
    args: list[str]


@dataclass(frozen=True)
class InstallResult:
    client: str
    path: Path
    action: str  # "added" | "updated" | "unchanged" | "skipped" | "removed"
    detail: str = ""


# ------------------------------------------------------------------ #
# Path resolution                                                     #
# ------------------------------------------------------------------ #


def claude_code_config_path() -> Path:
    return Path.home() / ".claude.json"


def claude_desktop_config_path() -> Path:
    if platform.system() == "Darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def config_path_for(client: str) -> Path:
    if client == "claude-code":
        return claude_code_config_path()
    if client == "claude-desktop":
        return claude_desktop_config_path()
    if client == "codex":
        return codex_config_path()
    raise ValueError(f"Unknown client: {client}")


# ------------------------------------------------------------------ #
# Command resolution                                                  #
# ------------------------------------------------------------------ #


def resolve_command_spec(*, fleet_sdk_root: Optional[Path] = None) -> CommandSpec:
    """Find the best `fleetcode-mcp` invocation for the current install.

    Priority:
      1. `fleetcode-mcp` co-located with the current Python interpreter (same
         venv as `flt`).
      2. `fleetcode-mcp` anywhere on PATH.
      3. `uv run --directory <repo> --extra fleetcode fleetcode-mcp` if a dev
         checkout is detectable.
    Otherwise raises RuntimeError with an install hint.
    """
    candidate = Path(sys.executable).parent / "fleetcode-mcp"
    if candidate.exists():
        return CommandSpec(command=str(candidate), args=[])

    on_path = shutil.which("fleetcode-mcp")
    if on_path:
        return CommandSpec(command=on_path, args=[])

    repo = fleet_sdk_root or _detect_dev_checkout()
    if repo is not None:
        uv = shutil.which("uv")
        if uv:
            return CommandSpec(
                command=uv,
                args=[
                    "run",
                    "--directory",
                    str(repo),
                    "--extra",
                    "fleetcode",
                    "fleetcode-mcp",
                ],
            )

    raise RuntimeError(
        "Could not find `fleetcode-mcp`. Install with: "
        "pip install 'fleet-python[fleetcode]'"
    )


def _detect_dev_checkout() -> Optional[Path]:
    """Walk up from this module to find a fleet-python pyproject."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        pyproject = parent / "pyproject.toml"
        if pyproject.is_file():
            try:
                text = pyproject.read_text()
            except OSError:
                return None
            if 'name = "fleet-python"' in text:
                return parent
            return None
    return None


# ------------------------------------------------------------------ #
# Writers — one per client                                            #
# ------------------------------------------------------------------ #


def install_for(client: str, *, spec: CommandSpec) -> InstallResult:
    """Install / update the FleetCode entry for one client. Idempotent."""
    path = config_path_for(client)
    if client in ("claude-code", "claude-desktop"):
        return _install_json(client, path, spec)
    if client == "codex":
        return _install_toml(client, path, spec)
    raise ValueError(f"Unknown client: {client}")


def uninstall_for(client: str) -> InstallResult:
    path = config_path_for(client)
    if client in ("claude-code", "claude-desktop"):
        return _uninstall_json(client, path)
    if client == "codex":
        return _uninstall_toml(client, path)
    raise ValueError(f"Unknown client: {client}")


def render_snippet(client: str, spec: CommandSpec) -> str:
    """Return the JSON/TOML snippet that would be written, for --print mode."""
    if client in ("claude-code", "claude-desktop"):
        return json.dumps(
            {"mcpServers": {ENTRY_NAME: _json_entry(spec)}}, indent=2
        )
    if client == "codex":
        return _toml_snippet(spec)
    raise ValueError(f"Unknown client: {client}")


def _json_entry(spec: CommandSpec) -> dict:
    return {"command": spec.command, "args": list(spec.args)}


def _install_json(client: str, path: Path, spec: CommandSpec) -> InstallResult:
    existing = _read_json(path)
    servers = existing.setdefault("mcpServers", {})
    new_entry = _json_entry(spec)
    prior = servers.get(ENTRY_NAME)
    if prior == new_entry:
        return InstallResult(client, path, "unchanged")
    action = "updated" if prior is not None else "added"
    servers[ENTRY_NAME] = new_entry
    _atomic_write(path, json.dumps(existing, indent=2) + "\n")
    return InstallResult(client, path, action)


def _uninstall_json(client: str, path: Path) -> InstallResult:
    if not path.exists():
        return InstallResult(client, path, "skipped", "config not found")
    existing = _read_json(path)
    servers = existing.get("mcpServers")
    if not isinstance(servers, dict) or ENTRY_NAME not in servers:
        return InstallResult(client, path, "skipped", "entry not present")
    servers.pop(ENTRY_NAME)
    if not servers:
        existing.pop("mcpServers", None)
    _atomic_write(path, json.dumps(existing, indent=2) + "\n")
    return InstallResult(client, path, "removed")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text()
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError(
            f"{path} does not contain a JSON object; refusing to overwrite."
        )
    return data


def _install_toml(client: str, path: Path, spec: CommandSpec) -> InstallResult:
    import tomlkit
    from tomlkit.items import Table

    doc = _read_toml_doc(path)
    servers = doc.get("mcp_servers")
    if servers is None:
        servers = tomlkit.table()
        doc["mcp_servers"] = servers
    elif not isinstance(servers, Table):
        raise RuntimeError(
            f"{path}: mcp_servers must be a table; refusing to overwrite."
        )

    new_entry = tomlkit.table()
    new_entry["command"] = spec.command
    new_entry["args"] = list(spec.args)

    prior = servers.get(ENTRY_NAME)
    if prior is not None and dict(prior) == {"command": spec.command, "args": list(spec.args)}:
        return InstallResult(client, path, "unchanged")
    action = "updated" if prior is not None else "added"
    servers[ENTRY_NAME] = new_entry
    _atomic_write(path, tomlkit.dumps(doc))
    return InstallResult(client, path, action)


def _uninstall_toml(client: str, path: Path) -> InstallResult:
    import tomlkit

    if not path.exists():
        return InstallResult(client, path, "skipped", "config not found")
    doc = _read_toml_doc(path)
    servers = doc.get("mcp_servers")
    if servers is None or ENTRY_NAME not in servers:
        return InstallResult(client, path, "skipped", "entry not present")
    del servers[ENTRY_NAME]
    if len(servers) == 0:
        del doc["mcp_servers"]
    _atomic_write(path, tomlkit.dumps(doc))
    return InstallResult(client, path, "removed")


def _read_toml_doc(path: Path):
    import tomlkit

    if not path.exists():
        return tomlkit.document()
    raw = path.read_text()
    if not raw.strip():
        return tomlkit.document()
    return tomlkit.parse(raw)


def _toml_snippet(spec: CommandSpec) -> str:
    """Render a copy-pasteable TOML block for --print mode."""
    import tomlkit

    body = tomlkit.dumps(
        {"command": spec.command, "args": list(spec.args)}
    ).rstrip()
    return f"[mcp_servers.{ENTRY_NAME}]\n{body}\n"


# ------------------------------------------------------------------ #
# Atomic write                                                        #
# ------------------------------------------------------------------ #


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------ #
# Detection                                                           #
# ------------------------------------------------------------------ #


def detect_installed_clients() -> list[str]:
    """Return clients whose config file currently exists.

    Note: Claude Code's `~/.claude.json` is created on first run of `claude`,
    so a non-existent path means the user hasn't run Claude Code yet — we
    skip writing rather than create a config the user never opted into.
    """
    return [c for c in CLIENT_CHOICES if config_path_for(c).exists()]


def install_many(
    clients: Iterable[str], *, spec: CommandSpec
) -> list[InstallResult]:
    return [install_for(c, spec=spec) for c in clients]


def uninstall_many(clients: Iterable[str]) -> list[InstallResult]:
    return [uninstall_for(c) for c in clients]
