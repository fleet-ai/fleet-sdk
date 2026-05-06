"""Unit tests for flt track CLI helpers."""

from __future__ import annotations

import json
import socket
import uuid

import pytest
import typer
from typer.testing import CliRunner

from fleet.track import cli
from fleet.track.api import TrackAPIError
from fleet.track.paths import TrackPaths
from fleet.track.store import ChainedSessionStore, RemoteSessionStore, Session


runner = CliRunner()


def test_enable_persists_generated_device_id_before_provision_retry(
    tmp_path,
    monkeypatch,
):
    """A failed first provision must not make the next enable use a new device."""
    paths = TrackPaths.under(tmp_path)
    seen_device_ids: list[str] = []

    class FailingTrackAPIClient:
        def provision(self, device_id: str) -> dict:
            seen_device_ids.append(device_id)
            raise TrackAPIError("network down")

    monkeypatch.setattr(cli.TrackPaths, "default", lambda: paths)
    monkeypatch.setenv("FLEET_API_KEY", "test-api-key")
    monkeypatch.setattr(cli, "TrackAPIClient", FailingTrackAPIClient)
    monkeypatch.setattr(socket, "gethostname", lambda: "Dev Laptop")
    monkeypatch.setattr(
        cli.uuid,
        "uuid4",
        lambda: uuid.UUID("11111111-2222-3333-4444-555555555555"),
    )

    with pytest.raises(typer.Exit):
        cli.enable()

    config = json.loads(paths.config_file.read_text())
    assert config["device_id"] == "dev-laptop-11111111"

    monkeypatch.setattr(
        cli.uuid,
        "uuid4",
        lambda: uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
    )

    with pytest.raises(typer.Exit):
        cli.enable()

    assert seen_device_ids == ["dev-laptop-11111111", "dev-laptop-11111111"]
    assert json.loads(paths.config_file.read_text())["device_id"] == (
        "dev-laptop-11111111"
    )


def test_resolve_session_store_defaults_remote_and_local_alias(tmp_path, monkeypatch):
    paths = TrackPaths.under(tmp_path)
    monkeypatch.setattr(cli.TrackPaths, "default", lambda: paths)

    assert isinstance(cli._resolve_session_store("remote"), RemoteSessionStore)
    assert isinstance(cli._resolve_session_store(""), RemoteSessionStore)
    assert isinstance(cli._resolve_session_store("local"), ChainedSessionStore)
    assert isinstance(cli._resolve_session_store("auto"), ChainedSessionStore)


def test_track_ls_defaults_remote_and_forwards_query(monkeypatch):
    calls: list[dict] = []
    sources: list[str] = []

    class FakeStore:
        def page(self, **kwargs):
            calls.append(kwargs)
            return (
                [
                    Session(
                        id="session-1",
                        tool="codex",
                        cwd="/repo",
                        last_active="2026-05-05T00:00:00Z",
                        event_count=3,
                    )
                ],
                "next-cursor",
            )

    def resolve(source: str):
        sources.append(source)
        return FakeStore()

    monkeypatch.setattr(cli, "_resolve_session_store", resolve)

    result = runner.invoke(cli.app, ["ls", "--query", "repo search", "--json"])

    assert result.exit_code == 0, result.stdout
    assert sources == ["remote"]
    assert calls == [
        {
            "tool": None,
            "cwd": None,
            "since": None,
            "query": "repo search",
            "limit": 50,
            "cursor": None,
        }
    ]
    payload = json.loads(result.stdout)
    assert payload["source"] == "remote"
    assert payload["query"] == "repo search"
    assert payload["items"][0]["id"] == "session-1"
    assert payload["next_cursor"] == "next-cursor"


def test_track_ls_honors_explicit_local_source(monkeypatch):
    sources: list[str] = []

    class FakeStore:
        def page(self, **kwargs):
            return ([], None)

    def resolve(source: str):
        sources.append(source)
        return FakeStore()

    monkeypatch.setattr(cli, "_resolve_session_store", resolve)

    result = runner.invoke(cli.app, ["ls", "--source", "local", "--json"])

    assert result.exit_code == 0, result.stdout
    assert sources == ["local"]
    assert json.loads(result.stdout)["source"] == "local"


def test_track_search_emits_agent_friendly_json_and_passes_cursor(monkeypatch):
    calls: list[dict] = []

    class FakeStore:
        def page(self, **kwargs):
            calls.append(kwargs)
            return (
                [
                    Session(
                        id="session-2",
                        tool="claude",
                        cwd="/theseus",
                        last_active="2026-05-06T00:00:00Z",
                        metadata={"title": "Turbopuffer indexing"},
                    )
                ],
                None,
            )

    monkeypatch.setattr(cli, "_resolve_session_store", lambda source: FakeStore())

    result = runner.invoke(
        cli.app,
        [
            "search",
            "who worked on turbopuffer indexing",
            "--tool",
            "claude",
            "--limit",
            "5",
            "--cursor",
            "opaque-tpuf-cursor",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls == [
        {
            "tool": "claude",
            "cwd": None,
            "since": None,
            "query": "who worked on turbopuffer indexing",
            "limit": 5,
            "cursor": "opaque-tpuf-cursor",
        }
    ]
    payload = json.loads(result.stdout)
    assert payload["source"] == "remote"
    assert payload["query"] == "who worked on turbopuffer indexing"
    assert payload["items"][0]["metadata"]["title"] == "Turbopuffer indexing"
