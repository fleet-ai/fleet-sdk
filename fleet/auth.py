"""Fleet CLI authentication — credential storage and token management."""

import base64
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple

import httpx

from .config import GLOBAL_BASE_URL

CREDENTIALS_FILE = Path.home() / ".fleet" / "credentials.json"
AUTH_REFRESH_PATH = "/v1/auth/refresh"

# Refresh token 60 seconds before expiry to avoid race conditions
_REFRESH_BUFFER_SECS = 60


def save_credentials(data: dict) -> None:
    """Write credentials to ~/.fleet/credentials.json with restricted permissions."""
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=CREDENTIALS_FILE.parent,
        prefix=f".{CREDENTIALS_FILE.name}-",
        suffix=".tmp",
        text=True,
    )
    try:
        os.fchmod(fd, 0o600)
        f = os.fdopen(fd, "w")
        fd = -1
        with f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, CREDENTIALS_FILE)
        os.chmod(CREDENTIALS_FILE, 0o600)
    except Exception:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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


def _auth_refresh_base_url() -> str:
    return (
        os.environ.get("FLEET_AUTH_BASE_URL")
        or os.environ.get("FLEET_BASE_URL")
        or os.environ.get("FLEET_TRACK_BASE_URL")
        or GLOBAL_BASE_URL
    ).rstrip("/")


def refresh_access_token(refresh_token: str) -> dict:
    """Exchange a stored browser-login refresh token through Fleet."""
    # The SDK intentionally does not call the identity provider directly.
    # Fleet/orchestrator owns the provider exchange and returns SDK-shaped
    # credentials.
    response = httpx.post(
        f"{_auth_refresh_base_url()}{AUTH_REFRESH_PATH}",
        headers={
            "Content-Type": "application/json",
        },
        json={"refresh_token": refresh_token},
        timeout=10.0,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("access_token"):
        raise RuntimeError("Fleet auth refresh response did not include access_token")
    return data


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
