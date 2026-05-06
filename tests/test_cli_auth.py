from __future__ import annotations

import httpx
import pytest
import typer

from fleet.cli import _mask_secret, _run_oversight, get_client


def test_mask_secret_redacts_short_values():
    assert _mask_secret("short-key") == "[redacted]"


def test_mask_secret_keeps_prefix_and_suffix_for_long_values():
    assert _mask_secret("abcdefgh1234567890") == "abcdefgh...7890"


def test_get_client_uses_browser_login_auth_once(monkeypatch):
    calls = 0

    def fake_get_valid_token():
        nonlocal calls
        calls += 1
        return ("jwt-token", "team-1")

    monkeypatch.delenv("FLEET_API_KEY", raising=False)
    monkeypatch.setenv("FLEET_BASE_URL", "https://api.example.com")
    monkeypatch.setattr("fleet.auth.get_valid_token", fake_get_valid_token)

    client = get_client()
    headers = client.client.get_headers()

    assert calls == 1
    assert headers["X-JWT-Token"] == "jwt-token"
    assert headers["X-Team-ID"] == "team-1"
    assert "Authorization" not in headers


def test_get_client_exits_without_auth(monkeypatch):
    monkeypatch.delenv("FLEET_API_KEY", raising=False)
    monkeypatch.setenv("FLEET_BASE_URL", "https://api.example.com")
    monkeypatch.setattr("fleet.auth.get_valid_token", lambda: None)

    with pytest.raises(typer.Exit):
        get_client()


class _FakeOversightResponse:
    status_code = 200
    text = ""

    def json(self):
        return {"summary_id": "summary-1"}


class _FakeOversightClient:
    request = None

    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, headers, json):
        type(self).request = {
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": self.timeout,
        }
        return _FakeOversightResponse()


def test_run_oversight_uses_api_key_auth(monkeypatch):
    _FakeOversightClient.request = None
    monkeypatch.setenv("FLEET_API_KEY", "test-api-key")
    monkeypatch.setenv("FLEET_BASE_URL", "https://api.example.com")
    monkeypatch.setattr("fleet.auth.get_valid_token", lambda: None)
    monkeypatch.setattr(httpx, "Client", _FakeOversightClient)

    _run_oversight("job-1")

    assert _FakeOversightClient.request == {
        "url": "https://api.example.com/v1/summarize/job",
        "headers": {
            "accept": "application/json",
            "Authorization": "Bearer test-api-key",
            "Content-Type": "application/json",
        },
        "json": {
            "job_id": "job-1",
            "model": "anthropic/claude-sonnet-4",
            "max_context_tokens": 180000,
            "force_new_summary": False,
            "max_concurrent": 20,
        },
        "timeout": 300,
    }


def test_run_oversight_uses_browser_login_auth(monkeypatch):
    _FakeOversightClient.request = None
    monkeypatch.delenv("FLEET_API_KEY", raising=False)
    monkeypatch.setenv("FLEET_BASE_URL", "https://api.example.com")
    monkeypatch.setattr("fleet.auth.get_valid_token", lambda: ("jwt-token", "team-1"))
    monkeypatch.setattr(httpx, "Client", _FakeOversightClient)

    _run_oversight("job-1")

    assert _FakeOversightClient.request["headers"]["X-JWT-Token"] == "jwt-token"
    assert _FakeOversightClient.request["headers"]["X-Team-ID"] == "team-1"
    assert "Authorization" not in _FakeOversightClient.request["headers"]


def test_run_oversight_skips_without_auth(monkeypatch):
    _FakeOversightClient.request = None
    monkeypatch.delenv("FLEET_API_KEY", raising=False)
    monkeypatch.setenv("FLEET_BASE_URL", "https://api.example.com")
    monkeypatch.setattr("fleet.auth.get_valid_token", lambda: None)
    monkeypatch.setattr(httpx, "Client", _FakeOversightClient)

    _run_oversight("job-1")

    assert _FakeOversightClient.request is None
