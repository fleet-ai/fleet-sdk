from __future__ import annotations

import base64
import json
import time

import pytest

from fleet import auth
from fleet._auth_headers import AuthenticatedWrapperMixin


class _Wrapper(AuthenticatedWrapperMixin):
    pass


def _jwt(exp: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode()
    payload = payload.rstrip("=")
    return f"header.{payload}.signature"


def test_save_and_load_credentials_uses_private_file(tmp_path, monkeypatch):
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", path)

    auth.save_credentials({"access_token": "jwt", "team_id": "team"})

    assert auth.load_credentials() == {"access_token": "jwt", "team_id": "team"}
    assert (path.stat().st_mode & 0o777) == 0o600


def test_get_valid_token_returns_stored_unexpired_token(tmp_path, monkeypatch):
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", path)
    auth.save_credentials(
        {
            "access_token": _jwt(int(time.time()) + 3600),
            "team_id": "team-1",
        }
    )

    assert auth.get_valid_token() == (auth.load_credentials()["access_token"], "team-1")


def test_get_valid_token_refreshes_expired_token(tmp_path, monkeypatch):
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", path)
    old_token = _jwt(int(time.time()) - 10)
    new_token = _jwt(int(time.time()) + 3600)
    auth.save_credentials(
        {
            "access_token": old_token,
            "refresh_token": "refresh",
            "team_id": "team-1",
        }
    )
    monkeypatch.setattr(
        auth,
        "refresh_access_token",
        lambda refresh_token: {
            "access_token": new_token,
            "refresh_token": f"{refresh_token}-next",
        },
    )

    assert auth.get_valid_token() == (new_token, "team-1")
    stored = auth.load_credentials()
    assert stored["access_token"] == new_token
    assert stored["refresh_token"] == "refresh-next"


def test_stored_login_auth_refreshes_headers_per_request(monkeypatch):
    tokens = iter(
        [
            ("initial-token", "team-1"),
            ("refreshed-token", "team-1"),
        ]
    )

    monkeypatch.setattr(auth, "get_valid_token", lambda: next(tokens))

    wrapper = _Wrapper()
    wrapper._init_auth(api_key=None, base_url=None)

    headers = wrapper.get_headers()

    assert headers["X-JWT-Token"] == "refreshed-token"
    assert headers["X-Team-ID"] == "team-1"


def test_explicit_jwt_auth_does_not_refresh_headers(monkeypatch):
    monkeypatch.setattr(
        auth,
        "get_valid_token",
        lambda: pytest.fail("explicit JWT auth should not read stored login"),
    )

    wrapper = _Wrapper()
    wrapper._init_auth(
        api_key=None,
        jwt="explicit-token",
        team_id="team-1",
        base_url=None,
    )

    headers = wrapper.get_headers()

    assert headers["X-JWT-Token"] == "explicit-token"
    assert headers["X-Team-ID"] == "team-1"


def test_stored_login_auth_raises_when_refresh_fails(monkeypatch):
    tokens = iter([("initial-token", "team-1"), None])
    monkeypatch.setattr(auth, "get_valid_token", lambda: next(tokens))

    wrapper = _Wrapper()
    wrapper._init_auth(api_key=None, base_url=None)

    with pytest.raises(RuntimeError, match="Stored login credentials are expired"):
        wrapper.get_headers()


def test_clear_credentials_removes_file(tmp_path, monkeypatch):
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", path)
    auth.save_credentials({"access_token": "jwt", "team_id": "team"})

    auth.clear_credentials()

    assert not path.exists()
