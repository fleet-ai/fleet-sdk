"""Unit tests for fleet.track.mcp_install — config writers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet.track import mcp_install
from fleet.track.mcp_install import CommandSpec, install_for, uninstall_for


SPEC = CommandSpec(command="/usr/local/bin/fleetcode-mcp", args=[])


def _patch_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    paths = {
        "claude-code": tmp_path / "claude_code.json",
        "claude-desktop": tmp_path / "claude_desktop.json",
        "codex": tmp_path / "codex.toml",
    }
    monkeypatch.setattr(
        mcp_install, "claude_code_config_path", lambda: paths["claude-code"]
    )
    monkeypatch.setattr(
        mcp_install, "claude_desktop_config_path", lambda: paths["claude-desktop"]
    )
    monkeypatch.setattr(mcp_install, "codex_config_path", lambda: paths["codex"])
    return paths


# ------------------------------------------------------------------ #
# JSON writers (Claude Code + Claude Desktop)                         #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("client", ["claude-code", "claude-desktop"])
def test_json_install_creates_config_when_absent(client, tmp_path, monkeypatch):
    paths = _patch_paths(monkeypatch, tmp_path)
    result = install_for(client, spec=SPEC)

    assert result.action == "added"
    body = json.loads(paths[client].read_text())
    assert body == {
        "mcpServers": {
            "fleetcode": {"command": SPEC.command, "args": []}
        }
    }


@pytest.mark.parametrize("client", ["claude-code", "claude-desktop"])
def test_json_install_preserves_unrelated_keys(client, tmp_path, monkeypatch):
    paths = _patch_paths(monkeypatch, tmp_path)
    paths[client].write_text(
        json.dumps(
            {
                "preferences": {"theme": "dark"},
                "mcpServers": {
                    "other": {"command": "other-mcp", "args": ["--keep"]},
                },
            }
        )
    )

    install_for(client, spec=SPEC)

    body = json.loads(paths[client].read_text())
    assert body["preferences"] == {"theme": "dark"}
    assert body["mcpServers"]["other"] == {"command": "other-mcp", "args": ["--keep"]}
    assert body["mcpServers"]["fleetcode"] == {"command": SPEC.command, "args": []}


@pytest.mark.parametrize("client", ["claude-code", "claude-desktop"])
def test_json_install_is_idempotent(client, tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    assert install_for(client, spec=SPEC).action == "added"
    assert install_for(client, spec=SPEC).action == "unchanged"


@pytest.mark.parametrize("client", ["claude-code", "claude-desktop"])
def test_json_install_updates_changed_command(client, tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    install_for(client, spec=SPEC)
    new_spec = CommandSpec(command="/different/path/fleetcode-mcp", args=["x"])

    result = install_for(client, spec=new_spec)

    assert result.action == "updated"


@pytest.mark.parametrize("client", ["claude-code", "claude-desktop"])
def test_json_uninstall_removes_only_fleetcode(client, tmp_path, monkeypatch):
    paths = _patch_paths(monkeypatch, tmp_path)
    paths[client].write_text(
        json.dumps(
            {
                "preferences": {"theme": "dark"},
                "mcpServers": {
                    "fleetcode": {"command": "old", "args": []},
                    "other": {"command": "other-mcp", "args": []},
                },
            }
        )
    )

    result = uninstall_for(client)

    assert result.action == "removed"
    body = json.loads(paths[client].read_text())
    assert "fleetcode" not in body["mcpServers"]
    assert body["mcpServers"]["other"]["command"] == "other-mcp"
    assert body["preferences"] == {"theme": "dark"}


@pytest.mark.parametrize("client", ["claude-code", "claude-desktop"])
def test_json_uninstall_is_noop_when_absent(client, tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    assert uninstall_for(client).action == "skipped"


@pytest.mark.parametrize("client", ["claude-code", "claude-desktop"])
def test_json_install_does_not_escape_non_ascii(client, tmp_path, monkeypatch):
    """Configs typically contain em-dashes, bullets, etc. — they must round-trip
    unchanged. Python's default `ensure_ascii=True` would mangle them."""
    paths = _patch_paths(monkeypatch, tmp_path)
    paths[client].write_text(
        '{"prompt": "use — these • characters █░"}',
        encoding="utf-8",
    )

    install_for(client, spec=SPEC)

    text = paths[client].read_text(encoding="utf-8")
    assert "—" in text
    assert "•" in text
    assert "█" in text
    assert "░" in text
    assert "\\u2014" not in text  # em-dash, must NOT be ASCII-escaped


# ------------------------------------------------------------------ #
# TOML writer (Codex)                                                 #
# ------------------------------------------------------------------ #


def test_codex_install_preserves_existing_servers_and_other_keys(tmp_path, monkeypatch):
    paths = _patch_paths(monkeypatch, tmp_path)
    existing = (
        'service_tier = "fast"\n'
        'approval_policy = "never"\n'
        '\n'
        '[projects."/Users/me/repo"]\n'
        'trust_level = "trusted"\n'
        '\n'
        '[mcp_servers.linear-server]\n'
        'url = "https://mcp.linear.app/mcp"\n'
    )
    paths["codex"].write_text(existing)

    result = install_for("codex", spec=SPEC)

    assert result.action == "added"
    text = paths["codex"].read_text()
    # Original keys + sections preserved verbatim by tomlkit.
    assert 'service_tier = "fast"' in text
    assert '[projects."/Users/me/repo"]' in text
    assert 'trust_level = "trusted"' in text
    assert '[mcp_servers.linear-server]' in text
    assert 'url = "https://mcp.linear.app/mcp"' in text
    # New entry added.
    assert "fleetcode" in text
    assert SPEC.command in text


def test_codex_install_creates_config_when_absent(tmp_path, monkeypatch):
    paths = _patch_paths(monkeypatch, tmp_path)
    result = install_for("codex", spec=SPEC)

    assert result.action == "added"
    text = paths["codex"].read_text()
    assert "fleetcode" in text
    assert SPEC.command in text


def test_codex_install_is_idempotent(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    assert install_for("codex", spec=SPEC).action == "added"
    assert install_for("codex", spec=SPEC).action == "unchanged"


def test_codex_uninstall_removes_only_fleetcode(tmp_path, monkeypatch):
    paths = _patch_paths(monkeypatch, tmp_path)
    install_for("codex", spec=SPEC)
    # Add another server so we can verify it survives.
    text = paths["codex"].read_text()
    paths["codex"].write_text(
        text + '\n[mcp_servers.other]\ncommand = "other-mcp"\nargs = []\n'
    )

    result = uninstall_for("codex")

    assert result.action == "removed"
    text = paths["codex"].read_text()
    assert "fleetcode" not in text
    assert "[mcp_servers.other]" in text


def test_codex_uninstall_is_noop_when_absent(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    assert uninstall_for("codex").action == "skipped"


# ------------------------------------------------------------------ #
# Detection                                                           #
# ------------------------------------------------------------------ #


def test_detect_only_returns_clients_whose_config_exists(tmp_path, monkeypatch):
    paths = _patch_paths(monkeypatch, tmp_path)
    paths["claude-code"].write_text("{}")
    paths["codex"].write_text("")

    detected = mcp_install.detect_installed_clients()

    assert detected == ["claude-code", "codex"]


# ------------------------------------------------------------------ #
# Command resolution                                                  #
# ------------------------------------------------------------------ #


def test_resolve_command_spec_prefers_venv_co_located_binary(tmp_path, monkeypatch):
    fake_bin = tmp_path / "fleetcode-mcp"
    fake_bin.write_text("#!/bin/sh\n")
    fake_bin.chmod(0o755)
    monkeypatch.setattr(mcp_install.sys, "executable", str(tmp_path / "python"))

    spec = mcp_install.resolve_command_spec()

    assert spec.command == str(fake_bin)
    assert spec.args == []


def test_resolve_command_spec_falls_back_to_path(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_install.sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(
        mcp_install.shutil,
        "which",
        lambda name: "/usr/local/bin/fleetcode-mcp" if name == "fleetcode-mcp" else None,
    )

    spec = mcp_install.resolve_command_spec()

    assert spec.command == "/usr/local/bin/fleetcode-mcp"
    assert spec.args == []


def test_resolve_command_spec_falls_back_to_uv_run_dev_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_install.sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(
        mcp_install.shutil,
        "which",
        lambda name: "/opt/homebrew/bin/uv" if name == "uv" else None,
    )

    spec = mcp_install.resolve_command_spec(fleet_sdk_root=tmp_path)

    assert spec.command == "/opt/homebrew/bin/uv"
    assert spec.args == [
        "run",
        "--directory",
        str(tmp_path),
        "--extra",
        "fleetcode",
        "fleetcode-mcp",
    ]


def test_resolve_command_spec_raises_when_nothing_found(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_install.sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(mcp_install.shutil, "which", lambda name: None)
    monkeypatch.setattr(mcp_install, "_detect_dev_checkout", lambda: None)

    with pytest.raises(RuntimeError, match="fleet-python\\[fleetcode\\]"):
        mcp_install.resolve_command_spec()
