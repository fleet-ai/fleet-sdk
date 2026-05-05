"""Unit tests for api.py — uses httpx.MockTransport, no network."""

from __future__ import annotations

import json
from typing import Optional

import httpx
import pytest

from fleet.track.api import (
    SERVER_UPLOAD_URL_BATCH_CAP,
    TrackAPIClient,
    TrackAPIError,
)


def _auth() -> Optional[str]:
    return "test-api-key"


def _no_auth() -> Optional[str]:
    return None


def _client_with_handler(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url="http://test")


def test_provision_sends_expected_payload_and_headers():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"device_id": "dev1", "team_id": "team-1", "user_id": "user-1"},
        )

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_auth)
    out = api.provision("dev1")

    assert out == {"device_id": "dev1", "team_id": "team-1", "user_id": "user-1"}
    assert captured["url"] == "http://test/v1/track/provision"
    assert captured["headers"]["authorization"] == "Bearer test-api-key"
    assert captured["body"]["device_id"] == "dev1"
    assert "hostname" in captured["body"]
    assert "platform" in captured["body"]


def test_get_manifest_returns_files_dict():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers.get("x-device-id") == "dev1"
        return httpx.Response(
            200,
            json={
                "root_hash": "abc",
                "files": {".claude/x.jsonl": "h1", ".codex/y.jsonl": "h2"},
            },
        )

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_auth)
    files = api.get_manifest("dev1")
    assert files == {".claude/x.jsonl": "h1", ".codex/y.jsonl": "h2"}


def test_get_manifest_empty_on_first_run():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"root_hash": "", "files": {}})

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_auth)
    assert api.get_manifest("dev1") == {}


def test_get_upload_urls_round_trips():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"urls": {p: f"https://s3/{p}?sig=x" for p in body["paths"]}},
        )

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_auth)
    urls = api.get_upload_urls("dev1", [".claude/a.jsonl", ".codex/b.jsonl"])
    assert urls == {
        ".claude/a.jsonl": "https://s3/.claude/a.jsonl?sig=x",
        ".codex/b.jsonl": "https://s3/.codex/b.jsonl?sig=x",
    }


def test_get_upload_urls_empty_paths_skips_request():
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json={"urls": {}})

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_auth)
    assert api.get_upload_urls("dev1", []) == {}
    assert called["n"] == 0


def test_get_upload_urls_chunks_above_server_cap():
    """Server caps at 100; client must chunk so one logical request → many HTTP calls."""
    requests_received: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests_received.append(len(body["paths"]))
        return httpx.Response(200, json={"urls": {p: f"u/{p}" for p in body["paths"]}})

    paths = [f"f{i}.jsonl" for i in range(250)]  # 250 > cap of 100
    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_auth)
    urls = api.get_upload_urls("dev1", paths)

    # Three chunks expected: 100 + 100 + 50.
    assert requests_received == [
        SERVER_UPLOAD_URL_BATCH_CAP,
        SERVER_UPLOAD_URL_BATCH_CAP,
        50,
    ]
    assert len(urls) == 250


def test_upsert_session_posts_relative_path_and_session_payload():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(204)

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_auth)
    api.upsert_session(
        device_id="dev1",
        path=".codex/sessions/rollout-2026-05-05T00-00-00-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl",
        session={
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "tool": "codex",
            "cwd": "/tmp/project",
            "event_count": 3,
            "metadata": {"title": "demo"},
        },
    )

    assert captured["url"] == (
        "http://test/v1/track/sessions/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    assert captured["body"]["device_id"] == "dev1"
    assert captured["body"]["path"].startswith(".codex/sessions/")
    assert captured["body"]["session"]["tool"] == "codex"


def test_list_sessions_sends_filters_and_returns_json():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "s1",
                        "tool": "claude",
                        "last_active": "2026-05-05T00:00:00Z",
                    }
                ],
                "next_cursor": "next",
            },
        )

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_auth)
    out = api.list_sessions(tool="claude", query="fleet", limit=25, cursor="cur")

    assert captured["params"] == {
        "tool": "claude",
        "query": "fleet",
        "limit": "25",
        "cursor": "cur",
    }
    assert out["items"][0]["id"] == "s1"
    assert out["next_cursor"] == "next"


def test_download_session_content_uses_presigned_url_without_auth_headers():
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization")))
        if request.url.path == "/v1/track/sessions/s1/content":
            return httpx.Response(200, json={"url": "https://s3.test/session"})
        if str(request.url) == "https://s3.test/session":
            return httpx.Response(200, content=b'{"ok": true}\n')
        raise AssertionError(f"unexpected request: {request.url}")

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_auth)
    assert api.download_session_content("s1") == b'{"ok": true}\n'
    assert seen == [
        ("http://test/v1/track/sessions/s1/content", "Bearer test-api-key"),
        ("https://s3.test/session", None),
    ]


def test_unauthenticated_raises_track_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_no_auth)
    with pytest.raises(TrackAPIError, match="Not authenticated"):
        api.provision("dev1")


def test_4xx_response_raises_with_detail_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"detail": "Track requires user-scoped credentials."}
        )

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_auth)
    with pytest.raises(TrackAPIError) as ei:
        api.provision("dev1")
    assert "403" in str(ei.value)
    assert "user-scoped" in str(ei.value)


def test_5xx_response_includes_status_in_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream exploded")

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_auth)
    with pytest.raises(TrackAPIError) as ei:
        api.get_manifest("dev1")
    assert "500" in str(ei.value)


def test_context_manager_closes_owned_client():
    """When the API client constructs its own httpx.Client, exiting the context
    closes it. When client is injected, we must not close the caller's."""
    api_owned = TrackAPIClient(auth_provider=_auth)
    api_owned.close()  # must not raise

    injected = httpx.Client(base_url="http://test")
    with TrackAPIClient(client=injected, auth_provider=_auth):
        pass
    # Injected client was NOT owned by the API; should still be usable.
    assert not injected.is_closed
    injected.close()
