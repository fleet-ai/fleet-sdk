from __future__ import annotations

import base64
import json
import stat
import time

from fleet import auth


def _jwt_with_exp(exp: int) -> str:
    def encode(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{encode({'alg': 'none'})}.{encode({'exp': exp})}.sig"


def test_save_credentials_writes_private_file(tmp_path, monkeypatch):
    credentials_file = tmp_path / "credentials.json"
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)

    auth.save_credentials({"access_token": "token"})

    assert json.loads(credentials_file.read_text()) == {"access_token": "token"}
    assert stat.S_IMODE(credentials_file.stat().st_mode) == 0o600


def test_refresh_access_token_calls_fleet_auth_endpoint(monkeypatch):
    calls = {}

    class Response:
        def raise_for_status(self):
            calls["raise_for_status"] = True

        def json(self):
            return {"access_token": "new-jwt", "refresh_token": "new-refresh"}

    def fake_post(url, *, headers, json, timeout):
        calls.update(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return Response()

    monkeypatch.setenv("FLEET_AUTH_BASE_URL", "https://staging.fleetai.com/")
    monkeypatch.setattr(auth.httpx, "post", fake_post)

    refreshed = auth.refresh_access_token("old-refresh")

    assert refreshed == {"access_token": "new-jwt", "refresh_token": "new-refresh"}
    assert calls["url"] == "https://staging.fleetai.com/v1/auth/refresh"
    assert calls["headers"] == {"Content-Type": "application/json"}
    assert calls["json"] == {"refresh_token": "old-refresh"}
    assert calls["timeout"] == 10.0
    assert calls["raise_for_status"] is True


def test_refresh_access_token_defaults_to_orchestrator(monkeypatch):
    calls = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "new-jwt"}

    def fake_post(url, *, headers, json, timeout):
        calls["url"] = url
        return Response()

    monkeypatch.delenv("FLEET_AUTH_BASE_URL", raising=False)
    monkeypatch.delenv("FLEET_BASE_URL", raising=False)
    monkeypatch.delenv("FLEET_TRACK_BASE_URL", raising=False)
    monkeypatch.setattr(auth.httpx, "post", fake_post)

    auth.refresh_access_token("old-refresh")

    assert calls["url"] == "https://orchestrator.fleetai.com/v1/auth/refresh"


def test_get_valid_token_refreshes_through_fleet(tmp_path, monkeypatch):
    credentials_file = tmp_path / "credentials.json"
    expired = _jwt_with_exp(int(time.time()) - 120)
    fresh = _jwt_with_exp(int(time.time()) + 3600)

    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)
    auth.save_credentials(
        {
            "access_token": expired,
            "refresh_token": "old-refresh",
            "team_id": "team-1",
        }
    )

    def fake_refresh(refresh_token):
        assert refresh_token == "old-refresh"
        return {"access_token": fresh, "refresh_token": "rotated-refresh"}

    monkeypatch.setattr(auth, "refresh_access_token", fake_refresh)

    assert auth.get_valid_token() == (fresh, "team-1")
    saved = json.loads(credentials_file.read_text())
    assert saved["access_token"] == fresh
    assert saved["refresh_token"] == "rotated-refresh"
