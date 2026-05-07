from __future__ import annotations

from dataclasses import dataclass

import pytest

from fleet.track import mcp_server


class FakeAPI:
    def __init__(self):
        self.search_bodies = []
        self.aggregate_bodies = []
        self.fabric_search_bodies = []
        self.fabric_aggregate_bodies = []

    def search_sessions(self, body):
        self.search_bodies.append(body)
        return {"items": [{"id": "s1"}], "next_cursor": None}

    def aggregate_sessions(self, body):
        self.aggregate_bodies.append(body)
        return {"groups": [{"key": {"tool": "codex"}, "count": 1}]}

    def search_fabric(self, body):
        self.fabric_search_bodies.append(body)
        return {"items": [{"source": "slack", "identifier": "C123"}]}

    def aggregate_fabric(self, body):
        self.fabric_aggregate_bodies.append(body)
        return {"groups": [{"key": {"source": "github"}, "count": 2}]}


@dataclass(frozen=True)
class FakeCachedSession:
    path: str = "/tmp/session.jsonl"

    def to_dict(self):
        return {
            "session_id": "s1",
            "path": self.path,
            "metadata_path": "/tmp/metadata.json",
            "cache_status": "downloaded",
            "content_codec": "raw",
            "raw_bytes": 10,
            "stored_bytes": 10,
            "event_count": 1,
            "last_active": "2026-05-06T00:00:00Z",
        }


def test_fleetcode_query_guide_describes_query_contract():
    guide = mcp_server.fleetcode_query_guide()

    assert "fleetcode_search_sessions" in guide["tools"]
    assert "fleetcode_aggregate_sessions" in guide["tools"]
    assert "fleetcode_download_session" in guide["tools"]
    assert "repo_url" in guide["filters"]["attributes"]
    assert "search_text" in guide["filters"]["search_filter_attributes"]
    assert "gte/$gte" in guide["filters"]["operators"]
    assert "prefix/$prefix" in guide["filters"]["search_text_operators"]
    assert (
        "text_match"
        in guide["tools"]["fleetcode_search_sessions"]["body_fields"]
    )
    assert (
        "items[].search_match"
        in guide["tools"]["fleetcode_search_sessions"]["response_fields"]
    )
    assert "$or" in guide["filters"]["logical_operators"]
    assert (
        "avg_event_count"
        in guide["tools"]["fleetcode_aggregate_sessions"]["body_fields"]["metrics"]
    )
    assert "time_bucket" in guide["tools"]["fleetcode_aggregate_sessions"]["body_fields"]
    assert "fleetcode_search_fabric" in guide["tools"]
    assert "fleetcode_aggregate_fabric" in guide["tools"]
    assert (
        "github"
        in guide["tools"]["fleetcode_search_fabric"]["body_fields"]["sources"]
    )
    assert (
        "linear_team"
        in guide["tools"]["fleetcode_aggregate_fabric"]["body_fields"]["group_by"]
    )
    assert "q" in guide["tools"]["fleetcode_search_fabric"]["body_fields"]
    assert "filters" not in guide["tools"]["fleetcode_search_fabric"]["body_fields"]
    assert "q" in guide["tools"]["fleetcode_aggregate_fabric"]["body_fields"]
    assert "filters" not in guide["tools"]["fleetcode_aggregate_fabric"]["body_fields"]
    assert "fabric_search" in guide["examples"]
    assert "fabric_aggregate" in guide["examples"]
    assert "q" in guide["examples"]["fabric_search"]
    assert "filters" not in guide["examples"]["fabric_search"]
    assert "q" in guide["examples"]["fabric_aggregate"]
    assert "filters" not in guide["examples"]["fabric_aggregate"]


def test_fleetcode_search_sessions_defaults_limit_and_calls_api():
    api = FakeAPI()

    out = mcp_server.fleetcode_search_sessions({"query": "deployment"}, api=api)

    assert out["items"][0]["id"] == "s1"
    assert api.search_bodies == [{"query": "deployment", "limit": 50}]


def test_fleetcode_search_sessions_preserves_explicit_limit():
    api = FakeAPI()

    mcp_server.fleetcode_search_sessions({"query": "deployment", "limit": 5}, api=api)

    assert api.search_bodies == [{"query": "deployment", "limit": 5}]


def test_fleetcode_search_sessions_preserves_text_match_fields():
    api = FakeAPI()
    body = {
        "text_match": {"query": "database schema", "operator": "phrase"},
        "last_as_prefix": True,
        "filters": {"search_text": {"$prefix": "database schem"}},
        "limit": 10,
    }

    mcp_server.fleetcode_search_sessions(body, api=api)

    assert api.search_bodies == [body]


def test_fleetcode_aggregate_sessions_calls_api():
    api = FakeAPI()
    body = {"group_by": ["tool"], "metrics": ["count"]}

    out = mcp_server.fleetcode_aggregate_sessions(body, api=api)

    assert out["groups"][0]["count"] == 1
    assert api.aggregate_bodies == [body]


def test_fleetcode_search_fabric_calls_api():
    api = FakeAPI()
    body = {"q": "deployment", "sources": ["slack"], "limit": 5}

    out = mcp_server.fleetcode_search_fabric(body, api=api)

    assert out["items"][0]["source"] == "slack"
    assert api.fabric_search_bodies == [body]


def test_fleetcode_aggregate_fabric_calls_api():
    api = FakeAPI()
    body = {
        "q": "deployment",
        "sources": ["github"],
        "group_by": ["source", "github_repo"],
    }

    out = mcp_server.fleetcode_aggregate_fabric(body, api=api)

    assert out["groups"][0]["count"] == 2
    assert api.fabric_aggregate_bodies == [body]


def test_fleetcode_download_session_returns_path_and_local_guidance(monkeypatch):
    calls = []
    clients = []

    def fake_ensure(session_id, *, api=None, paths=None, force=False):
        calls.append((session_id, api, paths, force))
        return FakeCachedSession()

    class FakeTrackAPIClient:
        closed = False

        def __enter__(self):
            clients.append(self)
            return self

        def __exit__(self, *exc):
            self.closed = True

    monkeypatch.setattr(mcp_server, "ensure_local_session", fake_ensure)
    monkeypatch.setattr(mcp_server, "TrackAPIClient", FakeTrackAPIClient)

    out = mcp_server.fleetcode_download_session("s1", force=True)

    assert calls == [("s1", clients[0], None, True)]
    assert clients[0].closed is True
    assert out["path"] == "/tmp/session.jsonl"
    assert "rg '<pattern>' /tmp/session.jsonl" == out["local_analysis"]["examples"]["grep"]


def test_fleetcode_tools_reject_non_object_body():
    with pytest.raises(TypeError, match="body must be a JSON object"):
        mcp_server.fleetcode_search_sessions(["not", "an", "object"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "tool",
    [mcp_server.fleetcode_search_fabric, mcp_server.fleetcode_aggregate_fabric],
)
def test_fleetcode_fabric_tools_reject_non_object_body(tool):
    with pytest.raises(TypeError, match="body must be a JSON object"):
        tool(["not", "an", "object"])  # type: ignore[arg-type]


def test_mcp_install_error_mentions_python_requirement(monkeypatch):
    monkeypatch.setattr(mcp_server.sys, "version_info", (3, 9, 0))

    message = mcp_server._mcp_install_error_message()

    assert "Python 3.10+" in message
    assert "fleet-python[fleetcode]" in message


def test_main_allows_flt_login_auth_without_api_key(monkeypatch):
    calls = []

    class FakeMCP:
        def run(self, *, transport):
            calls.append(transport)

    monkeypatch.delenv("FLEET_API_KEY", raising=False)
    monkeypatch.setattr(mcp_server, "create_mcp", lambda: FakeMCP())

    mcp_server.main()

    assert calls == ["stdio"]
