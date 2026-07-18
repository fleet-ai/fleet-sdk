# Copyright 2025 Fleet AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Async mirror of ``fleet.browser``.

See :mod:`fleet.browser` for design notes. Kept as a separate file so the
async surface stays cleanly importable without dragging the sync wrapper
through any asyncio shims.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..browser import host_from_url  # re-export, identical logic

if TYPE_CHECKING:
    from .base import AsyncWrapper


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


class AsyncBrowserLease:
    """Async counterpart of :class:`fleet.browser.BrowserLease`."""

    def __init__(self, client: "AsyncWrapper", data: Dict[str, Any]):
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
        return self._raw

    async def refresh(self) -> "AsyncBrowserLease":
        response = await self._client.request(
            "GET",
            f"{_BROWSER_PATH}/{self.lease_id}",
            extra_headers=_extra_headers(self._jwt_token, self._team_id),
        )
        self._raw = response.json()
        self._apply(self._raw)
        return self

    async def wait_until_running(
        self,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
        require_stream_ready: bool = False,
    ) -> "AsyncBrowserLease":
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            await self.refresh()
            running = self.status == "running"
            if running and (not require_stream_ready or self.stream_ready):
                return self
            if loop.time() >= deadline:
                raise TimeoutError(
                    f"Browser lease {self.lease_id} not running after "
                    f"{timeout}s (status={self.status}, stream_ready={self.stream_ready})"
                )
            await asyncio.sleep(poll_interval)

    async def mcp_tools(self) -> Dict[str, Any]:
        response = await self._client.request(
            "GET",
            f"{_BROWSER_PATH}/{self.lease_id}/mcp-tools",
            extra_headers=_extra_headers(self._jwt_token, self._team_id),
        )
        return response.json()

    async def delete(self) -> None:
        from ..exceptions import FleetAPIError

        try:
            await self._client.request(
                "DELETE",
                f"{_BROWSER_PATH}/{self.lease_id}",
                extra_headers=_extra_headers(self._jwt_token, self._team_id),
            )
        except FleetAPIError as exc:
            status = getattr(exc, "status_code", None)
            if status not in (404, 410):
                raise

    async def __aenter__(self) -> "AsyncBrowserLease":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.delete()

    def __repr__(self) -> str:
        return (
            f"AsyncBrowserLease(lease_id={self.lease_id!r}, status={self.status!r}, "
            f"cdp_url={self.cdp_url!r})"
        )


async def create_browser(
    client: "AsyncWrapper",
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
) -> AsyncBrowserLease:
    payload: Dict[str, Any] = {"ttl_seconds": ttl_seconds}
    if lease_id is not None:
        payload["lease_id"] = lease_id
    if allowed_hosts is not None:
        payload["allowed_hosts"] = allowed_hosts
    if request_timestamp_ms is not None:
        payload["request_timestamp_ms"] = request_timestamp_ms
    if extra:
        payload.update(extra)

    response = await client.request(
        "POST",
        _BROWSER_PATH,
        json=payload,
        extra_headers=_extra_headers(jwt_token, team_id),
    )
    lease = AsyncBrowserLease(client, response.json())
    lease._jwt_token = jwt_token
    lease._team_id = team_id
    if wait_until_running:
        await lease.wait_until_running(timeout=wait_timeout)
    return lease


async def get_browser(
    client: "AsyncWrapper",
    lease_id: str,
    *,
    jwt_token: Optional[str] = None,
    team_id: Optional[str] = None,
) -> AsyncBrowserLease:
    response = await client.request(
        "GET",
        f"{_BROWSER_PATH}/{lease_id}",
        extra_headers=_extra_headers(jwt_token, team_id),
    )
    lease = AsyncBrowserLease(client, response.json())
    lease._jwt_token = jwt_token
    lease._team_id = team_id
    return lease


__all__ = ["AsyncBrowserLease", "create_browser", "get_browser", "host_from_url"]
