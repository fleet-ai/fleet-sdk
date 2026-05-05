from __future__ import annotations

import json
import stat

from fleet import auth


def test_save_credentials_writes_private_file(tmp_path, monkeypatch):
    credentials_file = tmp_path / "credentials.json"
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)

    auth.save_credentials({"access_token": "token"})

    assert json.loads(credentials_file.read_text()) == {"access_token": "token"}
    assert stat.S_IMODE(credentials_file.stat().st_mode) == 0o600
