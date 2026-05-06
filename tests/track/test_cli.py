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
from fleet.track.status import TrackStatus
from fleet.track.store import LocalSessionStore, RemoteSessionStore, Session


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


def test_resolve_session_store_only_accepts_remote_or_local(tmp_path, monkeypatch):
    paths = TrackPaths.under(tmp_path)
    monkeypatch.setattr(cli.TrackPaths, "default", lambda: paths)

    assert isinstance(cli._resolve_session_store("remote"), RemoteSessionStore)
    assert isinstance(cli._resolve_session_store(""), RemoteSessionStore)
    assert isinstance(cli._resolve_session_store("local"), LocalSessionStore)
    for source in ("auto", "stub", "native"):
        with pytest.raises(typer.BadParameter):
            cli._resolve_session_store(source)


def test_status_shows_blocklist_summary(tmp_path, monkeypatch):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()
    paths.config_file.write_text(
        json.dumps(
            {
                "blocked_session_ids": ["s1", "s2"],
                "blocked_paths": [".cursor/projects/p/session.jsonl"],
                "blocked_path_globs": [".claude/projects/private/*.jsonl"],
            }
        )
    )

    monkeypatch.setattr(cli.TrackPaths, "default", lambda: paths)
    monkeypatch.setattr(cli, "is_running", lambda p: True)
    monkeypatch.setattr(
        cli,
        "read_status",
        lambda p: TrackStatus(
            pid=123,
            state="idle",
            last_sync="2026-05-06T00:00:00Z",
        ),
    )

    result = runner.invoke(cli.app, ["status"])

    assert result.exit_code == 0, result.stdout
    assert "Blocked:" in result.stdout
    assert "2 session ids" in result.stdout
    assert "1 path" in result.stdout
    assert "1 path glob" in result.stdout
    assert "flt track blocked" in result.stdout


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


def test_track_search_posts_inline_json_to_remote_search(monkeypatch):
    calls: list[dict] = []

    class FakeAPI:
        def search_sessions(self, body):
            calls.append(body)
            return {
                "items": [
                    {
                        "id": "session-2",
                        "tool": "claude",
                        "cwd": "/theseus",
                        "last_active": "2026-05-06T00:00:00Z",
                        "metadata": {"title": "Turbopuffer indexing"},
                    }
                ],
                "next_cursor": None,
            }

    monkeypatch.setattr(cli, "TrackAPIClient", FakeAPI)

    result = runner.invoke(
        cli.app,
        [
            "search",
            json.dumps(
                {
                    "query": "who worked on turbopuffer indexing",
                    "limit": 5,
                }
            ),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls == [{"query": "who worked on turbopuffer indexing", "limit": 5}]
    payload = json.loads(result.stdout)
    assert payload["mode"] == "hybrid"
    assert payload["source"] == "remote"
    assert payload["query"] == "who worked on turbopuffer indexing"
    assert payload["items"][0]["metadata"]["title"] == "Turbopuffer indexing"


def test_track_search_rejects_non_json_body(monkeypatch):
    class FakeAPI:
        def search_sessions_raw(self, body):  # pragma: no cover - must not call
            raise AssertionError("unexpected API call")

    monkeypatch.setattr(cli, "TrackAPIClient", FakeAPI)

    result = runner.invoke(cli.app, ["search", "who worked on turbopuffer indexing"])

    assert result.exit_code != 0
    assert "invalid JSON" in (result.stdout + result.stderr)


def test_track_search_requires_json_object(monkeypatch):
    class FakeAPI:
        def search_sessions_raw(self, body):  # pragma: no cover - must not call
            raise AssertionError("unexpected API call")

    monkeypatch.setattr(cli, "TrackAPIClient", FakeAPI)

    result = runner.invoke(cli.app, ["search", json.dumps(["not", "an", "object"])])

    assert result.exit_code != 0
    assert "body must be a JSON object" in (result.stdout + result.stderr)


def test_track_search_requires_body_unless_listing_filters(monkeypatch):
    class FakeAPI:
        def search_sessions_raw(self, body):  # pragma: no cover - must not call
            raise AssertionError("unexpected API call")

    monkeypatch.setattr(cli, "TrackAPIClient", FakeAPI)

    result = runner.invoke(cli.app, ["search"])

    assert result.exit_code != 0
    assert "BODY is required unless --filters is provided" in (
        result.stdout + result.stderr
    )


def test_track_search_filters_outputs_catalog_json(monkeypatch):
    class FakeAPI:
        def search_sessions_raw(self, body):  # pragma: no cover - must not call
            raise AssertionError("unexpected API call")

    monkeypatch.setattr(cli, "TrackAPIClient", FakeAPI)

    result = runner.invoke(cli.app, ["search", "--filters"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert "Structured Fleet session filters" in payload["description"]
    assert {field["name"] for field in payload["filterable_attributes"]} >= {
        "tool",
        "repo_url",
        "event_count",
        "last_active",
    }
    assert "gte/$gte" in payload["operators"]
    assert "contains/$contains" in payload["operators"]
    assert "$or" in payload["logical_operators"]
    assert "time_bucket" in payload["aggregate_features"]


def test_track_search_applies_default_top_k(monkeypatch):
    calls: list[dict] = []

    class FakeAPI:
        def search_sessions(self, body):
            calls.append(body)
            return {"items": [], "next_cursor": None}

    monkeypatch.setattr(cli, "TrackAPIClient", FakeAPI)

    result = runner.invoke(
        cli.app,
        [
            "search",
            json.dumps({"filters": {"tool": "claude"}}),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls == [
        {
            "filters": {"tool": "claude"},
            "limit": 50,
        }
    ]


def test_track_search_posts_json_file_to_remote_api(tmp_path, monkeypatch):
    calls: list[dict] = []
    spec = {
        "query": "bugbot local index",
        "filters": {
            "repo_url": "github.com/fleet-ai/fleet-sdk",
            "tool": "codex",
        },
        "limit": 10,
    }
    spec_path = tmp_path / "search.json"
    spec_path.write_text(json.dumps(spec))

    class FakeAPI:
        def search_sessions(self, body):
            calls.append(body)
            return {
                "items": [
                    {
                        "id": "session-raw",
                        "tool": "codex",
                        "cwd": "/repo",
                        "last_active": "2026-05-06T00:00:00Z",
                        "metadata": {"title": "Raw search"},
                    }
                ],
                "next_cursor": None,
            }

    monkeypatch.setattr(cli, "TrackAPIClient", FakeAPI)

    result = runner.invoke(cli.app, ["search", f"@{spec_path}"])

    assert result.exit_code == 0, result.stdout
    assert calls == [spec]
    payload = json.loads(result.stdout)
    assert payload["mode"] == "hybrid"
    assert payload["source"] == "remote"
    assert payload["query"] == "bugbot local index"
    assert payload["items"][0]["id"] == "session-raw"


def test_track_search_reads_json_from_stdin(monkeypatch):
    calls: list[dict] = []

    class FakeAPI:
        def search_sessions(self, body):
            calls.append(body)
            return {"items": [], "next_cursor": None}

    monkeypatch.setattr(cli, "TrackAPIClient", FakeAPI)

    result = runner.invoke(
        cli.app,
        ["search", "-"],
        input=json.dumps({"mode": "recent", "limit": 25}),
    )

    assert result.exit_code == 0, result.stdout
    assert calls == [{"mode": "recent", "limit": 25}]


def test_track_search_help_documents_json_body_mode():
    result = runner.invoke(cli.app, ["search", "--help"])

    assert result.exit_code == 0, result.stdout
    assert "JSON search body" in result.stdout
    assert "flt track search @search.json" in result.stdout
    assert "mode" in result.stdout
    assert "filters" in result.stdout
    assert "limit" in result.stdout
    assert "Filterable attributes" in result.stdout
    assert "repo_url" in result.stdout
    assert "last_active" in result.stdout
    assert "event_count" in result.stdout
    assert "team_id" in result.stdout
    assert "--tpuf" not in result.stdout
    assert "--limit" not in result.stdout
    assert "--filters" in result.stdout
    assert "--tool" not in result.stdout
    assert "--cwd" not in result.stdout
    assert "--since" not in result.stdout
    assert "--cursor" not in result.stdout
    assert "--source" not in result.stdout


def test_track_aggregate_posts_json_to_aggregate_api(monkeypatch):
    calls: list[dict] = []

    class FakeAPI:
        def aggregate_sessions(self, body):
            calls.append(body)
            return {
                "backend": "postgres",
                "groups": [{"key": {"tool": "codex"}, "count": 2}],
                "row_count": 2,
                "total_groups": 1,
                "truncated": False,
            }

    monkeypatch.setattr(cli, "TrackAPIClient", FakeAPI)

    body = {"group_by": ["tool"], "metrics": ["count"]}
    result = runner.invoke(cli.app, ["aggregate", json.dumps(body)])

    assert result.exit_code == 0, result.stdout
    assert calls == [body]
    payload = json.loads(result.stdout)
    assert payload["backend"] == "postgres"
    assert payload["groups"][0]["count"] == 2


def test_track_download_outputs_cached_session_json(monkeypatch):
    from fleet.track import download as download_mod

    class FakeCached:
        def to_dict(self):
            return {
                "session_id": "s1",
                "path": "/tmp/session.jsonl",
                "metadata_path": "/tmp/metadata.json",
                "cache_status": "downloaded",
                "content_codec": "gzip",
                "raw_bytes": 1000,
                "stored_bytes": 200,
                "event_count": 10,
                "last_active": "2026-05-06T00:00:00Z",
            }

    calls: list[tuple[str, bool]] = []

    def fake_ensure(session_id, *, force=False):
        calls.append((session_id, force))
        return FakeCached()

    monkeypatch.setattr(download_mod, "ensure_local_session", fake_ensure)

    result = runner.invoke(cli.app, ["download", "s1", "--force"])

    assert result.exit_code == 0, result.stdout
    assert calls == [("s1", True)]
    payload = json.loads(result.stdout)
    assert payload["path"] == "/tmp/session.jsonl"
    assert payload["cache_status"] == "downloaded"


def test_build_local_index_scans_native_files_into_local_store(tmp_path, monkeypatch):
    paths = TrackPaths.under(tmp_path)
    monkeypatch.setattr(cli.TrackPaths, "default", lambda: paths)

    sid = "11111111-2222-3333-4444-555555555555"
    native_dir = tmp_path / ".claude" / "projects" / "-tmp-project"
    native_dir.mkdir(parents=True)
    native_file = native_dir / f"{sid}.jsonl"
    rows = [
        {
            "type": "user",
            "uuid": "u1",
            "sessionId": sid,
            "cwd": "/tmp/project",
            "timestamp": "2026-05-01T00:00:00Z",
            "message": {"role": "user", "content": "hello"},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u1",
            "timestamp": "2026-05-01T00:00:01Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "hi"}],
            },
        },
    ]
    native_file.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    result = runner.invoke(cli.app, ["build-local-index", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["source"] == "local"
    assert payload["indexed"] == 1
    assert payload["skipped"] == 0

    local = LocalSessionStore(paths)
    session = local.get(sid)
    assert session is not None
    assert session.tool == "claude"
    assert list(local.own_events(sid))


def test_build_local_index_indexes_native_sessions_past_first_page(
    tmp_path, monkeypatch
):
    import os
    import time

    paths = TrackPaths.under(tmp_path)
    monkeypatch.setattr(cli.TrackPaths, "default", lambda: paths)

    native_dir = tmp_path / ".claude" / "projects" / "-tmp-project"
    native_dir.mkdir(parents=True)
    native_files = []
    for i in range(60):
        sid = f"00000000-0000-0000-0000-{i:012d}"
        native_file = native_dir / f"{sid}.jsonl"
        rows = [
            {
                "type": "user",
                "uuid": f"u{i}",
                "sessionId": sid,
                "cwd": "/tmp/project",
                "timestamp": "2026-05-01T00:00:00Z",
                "message": {"role": "user", "content": f"hello {i}"},
            }
        ]
        native_file.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        native_files.append(native_file)

    now = time.time()
    for i, native_file in enumerate(native_files):
        timestamp = now - i
        os.utime(native_file, (timestamp, timestamp))

    result = runner.invoke(cli.app, ["build-local-index", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["indexed"] == 60
    assert payload["skipped"] == 0

    target = "00000000-0000-0000-0000-000000000059"
    local = LocalSessionStore(paths)
    assert local.get(target) is not None
    assert list(local.own_events(target))
