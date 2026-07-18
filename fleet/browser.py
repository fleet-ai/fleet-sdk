# Copyright 2025 Fleet AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Fleet Browser API — orchestrator-managed remote browser leases.

Thin wrapper around the `/v1/browser` HTTP surface documented at
`https://orchestrator.fleetai.com/docs`. A ``BrowserLease`` exposes the
``cdp_url`` / ``mcp_url`` / ``stream_url`` returned by the create call and
lets you poll, list MCP tools, and release the lease.

This is intentionally independent of ``fleet.resources.browser`` (the
in-instance CDP resource); they solve different problems.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .base import SyncWrapper


_BROWSER_PATH = "/v1/browser"


def _extra_headers(
    jwt_token: Optional[str] = None, team_id: Optional[str] = None
) -> Optional[Dict[str, str]]:
    headers: Dict[str, str] = {}
    if jwt_token:
        headers["X-JWT-Token"] = jwt_token
    if team_id:
        headers["X-Team-ID"] = team_id
    return headers or None


def host_from_url(url: str) -> str:
    """Return the bare hostname for a URL (no scheme, no port, no path).

    Useful when populating ``allowed_hosts`` from ``env.urls.root``.
    """
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.hostname or url


class BrowserLease:
    """A lease created via ``POST /v1/browser``.

    Attribute names mirror the JSON response. Methods that hit the API
    reuse the same :class:`SyncWrapper` that created the lease so auth /
    base URL / retries stay consistent.
    """

    def __init__(self, client: "SyncWrapper", data: Dict[str, Any]):
        self._client = client
        self._raw: Dict[str, Any] = dict(data)
        self._jwt_token: Optional[str] = None
        self._team_id: Optional[str] = None
        self._apply(data)

    def _apply(self, data: Dict[str, Any]) -> None:
        self.id: str = data.get("id") or data["lease_id"]
        self.lease_id: str = data["lease_id"]
        self.browser_id: Optional[str] = data.get("browser_id")
        self.host_domain: Optional[str] = data.get("host_domain")
        self.mcp_url: Optional[str] = data.get("mcp_url")
        self.cdp_url: Optional[str] = data.get("cdp_url")
        self.stream_url: Optional[str] = data.get("stream_url")
        self.status: Optional[str] = data.get("status")
        self.stream_ready: Optional[bool] = data.get("stream_ready")
        self.allowed_hosts: Optional[List[str]] = data.get("allowed_hosts")
        self.created_timestamp_ms: Optional[int] = data.get("created_timestamp_ms")
        self.expires_timestamp_ms: Optional[int] = data.get("expires_timestamp_ms")
        self.age_duration_ms: Optional[int] = data.get("age_duration_ms")
        self.cluster_name: Optional[str] = data.get("cluster_name")

    @property
    def raw(self) -> Dict[str, Any]:
        """Last server response payload (for fields not surfaced as attrs)."""
        return self._raw

    def refresh(self) -> "BrowserLease":
        """Re-fetch the lease (``GET /v1/browser/{lease_id}``)."""
        response = self._client.request(
            "GET",
            f"{_BROWSER_PATH}/{self.lease_id}",
            extra_headers=_extra_headers(self._jwt_token, self._team_id),
        )
        self._raw = response.json()
        self._apply(self._raw)
        return self

    def wait_until_running(
        self,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
        require_stream_ready: bool = False,
    ) -> "BrowserLease":
        """Poll until ``status == 'running'`` (or stream_ready, if requested)."""
        deadline = time.monotonic() + timeout
        while True:
            self.refresh()
            running = self.status == "running"
            if running and (not require_stream_ready or self.stream_ready):
                return self
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Browser lease {self.lease_id} not running after "
                    f"{timeout}s (status={self.status}, stream_ready={self.stream_ready})"
                )
            time.sleep(poll_interval)

    def mcp_tools(self) -> Dict[str, Any]:
        """List MCP tools the browser exposes."""
        response = self._client.request(
            "GET",
            f"{_BROWSER_PATH}/{self.lease_id}/mcp-tools",
            extra_headers=_extra_headers(self._jwt_token, self._team_id),
        )
        return response.json()

    def delete(self) -> None:
        """Release the lease. Idempotent — ignores 404 if already gone."""
        from .exceptions import FleetAPIError

        try:
            self._client.request(
                "DELETE",
                f"{_BROWSER_PATH}/{self.lease_id}",
                extra_headers=_extra_headers(self._jwt_token, self._team_id),
            )
        except FleetAPIError as exc:
            status = getattr(exc, "status_code", None)
            if status not in (404, 410):
                raise

    # Context manager so `with client.create_browser(...) as br: ...` cleans up.
    def __enter__(self) -> "BrowserLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.delete()

    def __repr__(self) -> str:
        return (
            f"BrowserLease(lease_id={self.lease_id!r}, status={self.status!r}, "
            f"cdp_url={self.cdp_url!r})"
        )


def create_browser(
    client: "SyncWrapper",
    *,
    ttl_seconds: int = 300,
    lease_id: Optional[str] = None,
    allowed_hosts: Optional[List[str]] = None,
    request_timestamp_ms: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
    jwt_token: Optional[str] = None,
    team_id: Optional[str] = None,
    wait_until_running: bool = False,
    wait_timeout: float = 60.0,
) -> BrowserLease:
    """POST ``/v1/browser`` and return a :class:`BrowserLease`.

    ``extra`` is merged into the request body so callers can pass
    fields that aren't first-class kwargs yet — keeps this freeform.
    """
    payload: Dict[str, Any] = {"ttl_seconds": ttl_seconds}
    if lease_id is not None:
        payload["lease_id"] = lease_id
    if allowed_hosts is not None:
        payload["allowed_hosts"] = allowed_hosts
    if request_timestamp_ms is not None:
        payload["request_timestamp_ms"] = request_timestamp_ms
    if extra:
        payload.update(extra)

    response = client.request(
        "POST",
        _BROWSER_PATH,
        json=payload,
        extra_headers=_extra_headers(jwt_token, team_id),
    )
    lease = BrowserLease(client, response.json())
    lease._jwt_token = jwt_token
    lease._team_id = team_id
    if wait_until_running:
        lease.wait_until_running(timeout=wait_timeout)
    return lease


def get_browser(
    client: "SyncWrapper",
    lease_id: str,
    *,
    jwt_token: Optional[str] = None,
    team_id: Optional[str] = None,
) -> BrowserLease:
    """Inspect an existing lease (``GET /v1/browser/{lease_id}``)."""
    response = client.request(
        "GET",
        f"{_BROWSER_PATH}/{lease_id}",
        extra_headers=_extra_headers(jwt_token, team_id),
    )
    lease = BrowserLease(client, response.json())
    lease._jwt_token = jwt_token
    lease._team_id = team_id
    return lease
