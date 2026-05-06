from __future__ import annotations

import base64
import json
import time

from fleet import auth


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


def test_clear_credentials_removes_file(tmp_path, monkeypatch):
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", path)
    auth.save_credentials({"access_token": "jwt", "team_id": "team"})

    auth.clear_credentials()

    assert not path.exists()
