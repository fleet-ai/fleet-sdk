"""Theseus track API client.

Three endpoints:
  POST /v1/track/provision     → register machine, get S3 prefix
  GET  /v1/track/manifest      → fetch remote Merkle state
  POST /v1/track/upload-urls   → get presigned S3 PUT URLs for a list of paths

Tests inject an `httpx.Client` built on `httpx.MockTransport` plus a fake
auth provider, so no network and no creds file ever touch a unit test.
"""

from __future__ import annotations

import logging
import os
import platform
import socket
from typing import Callable, Optional, Tuple

import httpx

from ..config import GLOBAL_BASE_URL

log = logging.getLogger("fleet.track.api")

DEFAULT_TIMEOUT = 30.0
SERVER_UPLOAD_URL_BATCH_CAP = 100  # /v1/track/upload-urls returns 400 above this.


# (access_token, team_id) — None when unauthenticated.
AuthProvider = Callable[[], Optional[Tuple[str, str]]]


class TrackAPIError(Exception):
    pass


def _default_auth_provider() -> Optional[Tuple[str, str]]:
    """Production auth: read from `~/.fleet/credentials.json`."""
    from ..auth import get_valid_token

    return get_valid_token()


def _default_base_url() -> str:
    return (os.getenv("FLEET_TRACK_BASE_URL", GLOBAL_BASE_URL)).rstrip("/")


class TrackAPIClient:
    """Wraps the three /v1/track/* endpoints.

    Constructor accepts either an `httpx.Client` (production: real network)
    or an `httpx.Client(transport=httpx.MockTransport(handler))` (tests).
    """

    def __init__(
        self,
        *,
        client: Optional[httpx.Client] = None,
        auth_provider: AuthProvider = _default_auth_provider,
        base_url: Optional[str] = None,
    ) -> None:
        self._auth = auth_provider
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.Client(
                base_url=base_url or _default_base_url(),
                timeout=DEFAULT_TIMEOUT,
            )
            self._owns_client = True

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TrackAPIClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Endpoints                                                            #
    # ------------------------------------------------------------------ #

    def provision(self, device_id: str) -> dict:
        """Register this device. Returns {device_id, team_id, user_id}."""
        resp = self._client.post(
            "/v1/track/provision",
            json={
                "device_id": device_id,
                "hostname": socket.gethostname(),
                "platform": platform.system().lower(),
            },
            headers=self._headers(),
        )
        _raise(resp)
        return resp.json()

    def get_manifest(self, device_id: str) -> dict[str, str]:
        """Fetch the remote Merkle manifest. Returns {} on first run."""
        resp = self._client.get(
            "/v1/track/manifest",
            headers=self._headers(device_id=device_id),
        )
        _raise(resp)
        return resp.json().get("files", {})

    def get_upload_urls(self, device_id: str, paths: list[str]) -> dict[str, str]:
        """Request presigned PUT URLs. Server caps batches at 100; we
        chunk to match so a callsite asking for more never 400s."""
        if not paths:
            return {}

        urls: dict[str, str] = {}
        for chunk_start in range(0, len(paths), SERVER_UPLOAD_URL_BATCH_CAP):
            chunk = paths[chunk_start : chunk_start + SERVER_UPLOAD_URL_BATCH_CAP]
            resp = self._client.post(
                "/v1/track/upload-urls",
                json={"device_id": device_id, "paths": chunk},
                headers=self._headers(),
            )
            _raise(resp)
            urls.update(resp.json().get("urls", {}))
        return urls

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _headers(self, device_id: Optional[str] = None) -> dict[str, str]:
        token_info = self._auth()
        if not token_info:
            raise TrackAPIError("Not authenticated — run `flt login`")
        access_token, team_id = token_info
        headers = {
            "X-JWT-Token": access_token,
            "X-Team-ID": team_id,
        }
        if device_id:
            headers["X-Device-ID"] = device_id
        return headers


def _raise(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise TrackAPIError(f"HTTP {resp.status_code}: {detail}")
