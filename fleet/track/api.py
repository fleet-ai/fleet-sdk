"""Theseus track API client.

Upload endpoints:
  POST /v1/track/provision     → register machine, get S3 prefix
  GET  /v1/track/manifest      → fetch remote Merkle state
  POST /v1/track/upload-urls   → get presigned S3 PUT URLs for a list of paths

Metadata endpoints:
  POST /v1/track/sessions/{id}         → upsert one session metadata row
  GET  /v1/track/sessions              → list/search remote sessions
  POST /v1/track/sessions/search       → raw Turbopuffer-shaped search
  GET  /v1/track/sessions/{id}         → fetch one session metadata row
  GET  /v1/track/sessions/{id}/content → get a presigned S3 GET URL

Tests inject an `httpx.Client` built on `httpx.MockTransport` plus a fake
auth provider, so no network and no creds file ever touch a unit test.
"""

from __future__ import annotations

import logging
import os
import platform
import socket
import gzip
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable, Mapping, Optional, Tuple, Union

import httpx

from ..config import GLOBAL_BASE_URL

log = logging.getLogger("fleet.track.api")

DEFAULT_TIMEOUT = 30.0
SERVER_UPLOAD_URL_BATCH_CAP = 100  # /v1/track/upload-urls returns 400 above this.
SERVER_BULK_UPSERT_BATCH_CAP = 100  # /v1/track/sessions/bulk; chunk to match.


AuthInfo = Union[str, Tuple[str, str]]
AuthProvider = Callable[[], Optional[AuthInfo]]
SearchMode = str
TextMatchOperator = str


@dataclass(frozen=True)
class TrackTextMatch:
    """Full-text match filter for indexed FleetCode session text.

    Operators mirror orchestrator's Turbopuffer-backed search API:
    `all_tokens`, `any_token`, `phrase`, `prefix`, `glob`, `iglob`, and `regex`.
    """

    query: str
    operator: TextMatchOperator = "all_tokens"
    field: str = "search_text"
    negate: bool = False


@dataclass(frozen=True)
class BulkSessionUpsert:
    """One item in a /v1/track/sessions/bulk request.

    Mirrors the per-arg shape of `upsert_session`. `content_codec`,
    `raw_bytes`, `stored_bytes` are only sent when this row carries
    a fresh upload (i.e. include_content_metadata=True equivalent).
    """

    path: str
    session: Any
    content_codec: Optional[str] = None
    raw_bytes: Optional[int] = None
    stored_bytes: Optional[int] = None


@dataclass(frozen=True)
class TrackSessionSearchRequest:
    """Structured body for `POST /v1/track/sessions/search`."""

    query: Optional[str] = None
    mode: SearchMode = "hybrid"
    last_as_prefix: bool = False
    text_match: Optional[TrackTextMatch] = None
    rank_by: Optional[list[Any]] = None
    filters: Optional[Any] = None
    time: Optional[Mapping[str, Any]] = None
    limit: Optional[int] = None
    top_k: int = 50


class TrackAPIError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class BulkUpsertPartialFailure(TrackAPIError):
    """Raised when one chunk of `upsert_sessions_bulk` fails after earlier
    chunks succeeded. `unsent_items` is the failing chunk plus everything
    after it; everything before it is already committed server-side. Lets
    the caller re-enqueue only what hasn't been sent, avoiding repeat
    sends of already-committed rows on the next flush.
    """

    def __init__(
        self,
        message: str,
        *,
        unsent_items: list["BulkSessionUpsert"],
        status_code: Optional[int] = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message, status_code=status_code, detail=detail)
        self.unsent_items = unsent_items


def _default_auth_provider() -> Optional[AuthInfo]:
    """Production auth: prefer stored `flt login` creds, then FLEET_API_KEY.

    `flt login` is the canonical user-bound auth path for Track. FLEET_API_KEY
    remains a fallback for non-interactive hosts (CI, headless connectors)
    and will be removed in a future release.
    """
    from ..auth import get_valid_token

    if token := get_valid_token():
        return token

    if api_key := os.getenv("FLEET_API_KEY"):
        return api_key

    return None


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

    def upsert_session(
        self,
        *,
        device_id: str,
        path: str,
        session: Any,
        content_codec: str = "raw",
        raw_bytes: Optional[int] = None,
        stored_bytes: Optional[int] = None,
        include_content_metadata: bool = True,
    ) -> None:
        """Register metadata for a session file already uploaded to S3.

        `path` is the source file path relative to the tracked home. The
        orchestrator owns translation from that relative path to the final S3
        key, so the SDK never has to construct team/user/device storage paths.
        """
        body = {
            "device_id": device_id,
            "path": path,
            "session": _session_payload(session),
        }
        if include_content_metadata:
            body.update(
                {
                    "content_codec": content_codec,
                    "raw_bytes": raw_bytes,
                    "stored_bytes": stored_bytes,
                }
            )
        resp = self._client.post(
            f"/v1/track/sessions/{_session_id(session)}",
            json=body,
            headers=self._headers(),
        )
        _raise(resp)

    def upsert_sessions_bulk(
        self,
        *,
        device_id: str,
        items: list["BulkSessionUpsert"],
    ) -> None:
        """Bulk-register metadata for many sessions in one request.

        Server reuses the single-row upsert translation logic per item, so
        path → s3_key conversion and validation behave identically. Empty
        list is a no-op. Chunks at SERVER_BULK_UPSERT_BATCH_CAP to match
        the server cap.

        On partial failure (some chunk succeeds, a later one doesn't),
        raises `BulkUpsertPartialFailure` carrying the unsent tail —
        already-committed earlier chunks are left server-side and the
        caller should only retry the unsent portion.
        """
        if not items:
            return
        for chunk_start in range(0, len(items), SERVER_BULK_UPSERT_BATCH_CAP):
            chunk = items[chunk_start : chunk_start + SERVER_BULK_UPSERT_BATCH_CAP]
            body = {
                "device_id": device_id,
                "items": [_bulk_item_payload(item) for item in chunk],
            }
            try:
                resp = self._client.post(
                    "/v1/track/sessions/bulk",
                    json=body,
                    headers=self._headers(),
                )
                _raise(resp)
            except TrackAPIError as e:
                unsent = items[chunk_start:]
                raise BulkUpsertPartialFailure(
                    str(e),
                    unsent_items=unsent,
                    status_code=e.status_code,
                    detail=e.detail,
                ) from e
            except Exception as e:
                # Network errors etc. — same partial-failure semantics: this
                # chunk and everything after it didn't reach the server.
                unsent = items[chunk_start:]
                raise BulkUpsertPartialFailure(
                    str(e),
                    unsent_items=unsent,
                ) from e

    def list_sessions(
        self,
        *,
        tool: Optional[str] = None,
        cwd: Optional[str] = None,
        since: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict:
        params = _clean_params(
            {
                "tool": tool,
                "cwd": cwd,
                "since": since,
                "query": query,
                "limit": limit,
                "cursor": cursor,
            }
        )
        resp = self._client.get(
            "/v1/track/sessions",
            params=params,
            headers=self._headers(),
        )
        _raise(resp)
        return resp.json()

    def _post_session_search(self, body: Any) -> dict:
        resp = self._client.post(
            "/v1/track/sessions/search",
            json=_json_body(body),
            headers=self._headers(),
        )
        _raise(resp)
        return resp.json()

    def search_sessions_raw(self, body: Any) -> dict:
        """Run legacy/debug raw Turbopuffer-shaped session search.

        The body is forwarded to orchestrator's
        `POST /v1/track/sessions/search`. Orchestrator owns auth, team-scope
        wrapping, server-side embeddings for `query`, and hydration back to
        Fleet session metadata. New CLI/MCP code should use `search_sessions`
        with structured filters instead.
        """
        return self._post_session_search(body)

    def search_sessions(self, body: Any) -> dict:
        """Run structured session search.

        This posts the stable Fleet search shape to the same orchestrator route
        as the legacy raw Turbopuffer body. Prefer this for agents and CLI use:
        filters are objects, `time` is shared with aggregate queries,
        `text_match` exposes Turbopuffer token/phrase/prefix/glob/regex
        filtering, and the server compiles the request to Turbopuffer.
        """
        return self._post_session_search(body)

    def aggregate_sessions(self, body: Mapping[str, Any]) -> dict:
        """Run structured Postgres aggregates over session metadata."""
        resp = self._client.post(
            "/v1/track/sessions/aggregate",
            json=dict(body),
            headers=self._headers(),
        )
        _raise(resp)
        return resp.json()

    def search_fabric(self, body: Mapping[str, Any]) -> dict:
        """Run structured Fabric entry search."""
        resp = self._client.post(
            "/v1/fabric/entries/search",
            json=dict(body),
            headers=self._headers(),
        )
        _raise(resp)
        return resp.json()

    def aggregate_fabric(self, body: Mapping[str, Any]) -> dict:
        """Run structured Fabric entry aggregates."""
        resp = self._client.post(
            "/v1/fabric/entries/aggregate",
            json=dict(body),
            headers=self._headers(),
        )
        _raise(resp)
        return resp.json()

    def get_session(self, session_id: str) -> dict:
        resp = self._client.get(
            f"/v1/track/sessions/{session_id}",
            headers=self._headers(),
        )
        _raise(resp)
        return resp.json()

    def get_session_content_info(self, session_id: str) -> dict:
        resp = self._client.get(
            f"/v1/track/sessions/{session_id}/content",
            headers=self._headers(),
        )
        _raise(resp)
        data = resp.json()
        url = data.get("url")
        if not url:
            raise TrackAPIError("Session content response did not include a URL")
        data["url"] = str(url)
        data.setdefault("content_codec", "raw")
        return data

    def get_session_content_url(self, session_id: str) -> str:
        return str(self.get_session_content_info(session_id)["url"])

    def download_session_content(self, session_id: str) -> bytes:
        """Fetch native session bytes via the orchestrator-issued S3 URL."""
        info = self.get_session_content_info(session_id)
        resp = self._client.get(info["url"])
        _raise(resp)
        content = resp.content
        if info.get("content_codec") == "gzip":
            return gzip.decompress(content)
        return content

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _headers(self, device_id: Optional[str] = None) -> dict[str, str]:
        auth_info = self._auth()
        if not auth_info:
            raise TrackAPIError(
                "Not authenticated — run `flt login` or set FLEET_API_KEY"
            )
        if isinstance(auth_info, str):
            headers = {"Authorization": f"Bearer {auth_info}"}
        else:
            access_token, team_id = auth_info
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
        raise TrackAPIError(
            f"HTTP {resp.status_code}: {detail}",
            status_code=resp.status_code,
            detail=detail,
        )


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None}


def _session_payload(session: Any) -> dict[str, Any]:
    if is_dataclass(session):
        return asdict(session)
    if isinstance(session, Mapping):
        return dict(session)
    raise TypeError(f"Unsupported session payload type: {type(session)!r}")


def _bulk_item_payload(item: "BulkSessionUpsert") -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": item.path,
        "session": _session_payload(item.session),
    }
    if item.content_codec is not None:
        out["content_codec"] = item.content_codec
    if item.raw_bytes is not None:
        out["raw_bytes"] = item.raw_bytes
    if item.stored_bytes is not None:
        out["stored_bytes"] = item.stored_bytes
    return out


def _json_body(body: Any) -> dict[str, Any]:
    if is_dataclass(body):
        return asdict(body)
    if isinstance(body, Mapping):
        return dict(body)
    raise TypeError(f"Unsupported JSON body type: {type(body)!r}")


def _session_id(session: Any) -> str:
    if isinstance(session, Mapping):
        sid = session.get("id")
    else:
        sid = getattr(session, "id", None)
    if not sid:
        raise ValueError("session.id is required")
    return str(sid)
