"""Fleet CLI authentication — credential storage and token management."""

import base64
import json
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import httpx

from ._supabase import SUPABASE_ANON_KEY, SUPABASE_URL

CREDENTIALS_FILE = Path.home() / ".fleet" / "credentials.json"

# Refresh token 60 seconds before expiry to avoid race conditions
_REFRESH_BUFFER_SECS = 60


def save_credentials(data: dict) -> None:
    """Write credentials to ~/.fleet/credentials.json with restricted permissions."""
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(CREDENTIALS_FILE, 0o600)


def load_credentials() -> Optional[dict]:
    """Read credentials from ~/.fleet/credentials.json, or None if not present."""
    if not CREDENTIALS_FILE.exists():
        return None
    try:
        with open(CREDENTIALS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def clear_credentials() -> None:
    """Delete stored credentials."""
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()


def is_token_expired(access_token: str) -> bool:
    """Return True if the JWT is expired or within the refresh buffer window."""
    try:
        payload_b64 = access_token.split(".")[1]
        # JWT uses base64url; pad to a multiple of 4 (% 4 == 0 needs no padding)
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return time.time() > payload["exp"] - _REFRESH_BUFFER_SECS
    except Exception:
        return True


def refresh_access_token(refresh_token: str) -> dict:
    """Exchange a Supabase refresh token for a new session."""
    response = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={"refresh_token": refresh_token},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def get_valid_token() -> Optional[Tuple[str, str]]:
    """Return (access_token, team_id) from stored credentials, refreshing if needed.

    Returns None if the user is not logged in or credentials are unusable.
    """
    creds = load_credentials()
    if not creds:
        return None

    access_token = creds.get("access_token")
    team_id = creds.get("team_id")

    if not access_token or not team_id:
        return None

    if is_token_expired(access_token):
        stored_refresh = creds.get("refresh_token")
        if not stored_refresh:
            return None
        try:
            refreshed = refresh_access_token(stored_refresh)
            access_token = refreshed["access_token"]
            creds["access_token"] = access_token
            if refreshed.get("refresh_token"):
                creds["refresh_token"] = refreshed["refresh_token"]
            save_credentials(creds)
        except Exception:
            return None

    return (access_token, team_id)
