"""Theseus track API client.

Three endpoints:
  POST /v1/track/provision     → register machine, get S3 prefix
  GET  /v1/track/manifest      → fetch remote Merkle state
  POST /v1/track/upload-urls   → get presigned S3 PUT URLs for a list of paths
"""

from __future__ import annotations

import logging
import os
import socket
from typing import Optional

import platform
import socket

import httpx

from ..auth import get_valid_token
from ..config import GLOBAL_BASE_URL

log = logging.getLogger("fleet.track.api")

TIMEOUT = 30.0


class TrackAPIError(Exception):
    pass


class TrackAPIClient:
    def __init__(self, base_url: str = "") -> None:
        self._base = (base_url or os.getenv("FLEET_TRACK_BASE_URL", GLOBAL_BASE_URL)).rstrip("/")

    def _headers(self, device_id: Optional[str] = None) -> dict[str, str]:
        token_info = get_valid_token()
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

    def provision(self, device_id: str) -> dict:
        """Register this device. Returns {device_id, team_id, user_id}."""
        resp = httpx.post(
            f"{self._base}/v1/track/provision",
            json={
                "device_id": device_id,
                "hostname": socket.gethostname(),
                "platform": platform.system().lower(),
            },
            headers=self._headers(),
            timeout=TIMEOUT,
        )
        _raise(resp)
        return resp.json()

    def get_manifest(self, device_id: str) -> dict[str, str]:
        """
        Fetch the remote Merkle manifest for this device.
        Returns flat {relative_path: sha256} map, empty dict on first run.
        """
        resp = httpx.get(
            f"{self._base}/v1/track/manifest",
            headers=self._headers(device_id=device_id),
            timeout=TIMEOUT,
        )
        _raise(resp)
        return resp.json().get("files", {})

    def get_upload_urls(self, device_id: str, paths: list[str]) -> dict[str, str]:
        """
        Request presigned PUT URLs for the given relative paths.
        Returns {relative_path: presigned_url}.
        """
        if not paths:
            return {}
        resp = httpx.post(
            f"{self._base}/v1/track/upload-urls",
            json={"device_id": device_id, "paths": paths},
            headers=self._headers(),
            timeout=TIMEOUT,
        )
        _raise(resp)
        return resp.json().get("urls", {})


def _raise(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise TrackAPIError(f"HTTP {resp.status_code}: {detail}")
