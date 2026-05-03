"""Unit tests for api.py — uses httpx.MockTransport, no network."""

from __future__ import annotations

import json
from typing import Optional, Tuple

import httpx
import pytest

from fleet.track.api import (
    SERVER_UPLOAD_URL_BATCH_CAP,
    TrackAPIClient,
    TrackAPIError,
)


def _auth() -> Optional[Tuple[str, str]]:
    return ("jwt-abc", "team-1")


def _no_auth() -> Optional[Tuple[str, str]]:
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
    assert captured["headers"]["x-jwt-token"] == "jwt-abc"
    assert captured["headers"]["x-team-id"] == "team-1"
    assert captured["body"]["device_id"] == "dev1"
    assert "hostname" in captured["body"]
    assert "platform" in captured["body"]


def test_get_manifest_returns_files_dict():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers.get("x-device-id") == "dev1"
        return httpx.Response(
            200,
            json={"root_hash": "abc", "files": {".claude/x.jsonl": "h1", ".codex/y.jsonl": "h2"}},
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
    assert requests_received == [SERVER_UPLOAD_URL_BATCH_CAP, SERVER_UPLOAD_URL_BATCH_CAP, 50]
    assert len(urls) == 250


def test_unauthenticated_raises_track_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    api = TrackAPIClient(client=_client_with_handler(handler), auth_provider=_no_auth)
    with pytest.raises(TrackAPIError, match="Not authenticated"):
        api.provision("dev1")


def test_4xx_response_raises_with_detail_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "Track requires user-scoped credentials."})

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
