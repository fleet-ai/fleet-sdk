"""Local session content cache for agentic intra-session analysis.

The orchestrator remains the auth boundary: it returns content metadata plus a
presigned S3 URL. The SDK downloads/decompresses into a deterministic local
cache, then agents can use normal local tools (`rg`, `jq`, `sed`, Python) on the
canonical JSONL file.
"""

from __future__ import annotations

import json
import os
import time
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

from .api import TrackAPIClient
from .paths import TrackPaths


@dataclass(frozen=True)
class CachedSession:
    session_id: str
    path: str
    metadata_path: str
    cache_status: str
    content_codec: str
    raw_bytes: Optional[int]
    stored_bytes: Optional[int]
    event_count: int
    last_active: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _session_cache_dir(paths: TrackPaths, session_id: str) -> Path:
    return paths.cache_dir / "sessions" / session_id


def _signature(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "content_codec": info.get("content_codec") or "raw",
        "raw_bytes": info.get("raw_bytes"),
        "stored_bytes": info.get("stored_bytes"),
        "event_count": info.get("event_count") or 0,
        "last_active": info.get("last_active"),
    }


def _metadata_matches(metadata_path: Path, info: dict[str, Any]) -> bool:
    try:
        current = json.loads(metadata_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return current.get("signature") == _signature(info)


def _write_stream(url: str, codec: str, dest: Path) -> None:
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
    decompressor = (
        zlib.decompressobj(16 + zlib.MAX_WBITS) if codec == "gzip" else None
    )
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as out:
                for chunk in resp.iter_bytes():
                    if not chunk:
                        continue
                    if decompressor is not None:
                        out.write(decompressor.decompress(chunk))
                    else:
                        out.write(chunk)
                if decompressor is not None:
                    out.write(decompressor.flush())


def ensure_local_session(
    session_id: str,
    *,
    api: Optional[TrackAPIClient] = None,
    paths: Optional[TrackPaths] = None,
    force: bool = False,
) -> CachedSession:
    """Ensure a session's canonical JSONL exists in the local cache."""
    api = api or TrackAPIClient()
    paths = paths or TrackPaths.default()
    info = api.get_session_content_info(session_id)
    codec = str(info.get("content_codec") or "raw")
    if codec not in {"raw", "gzip"}:
        raise ValueError(f"unsupported session content codec: {codec}")

    cache_dir = _session_cache_dir(paths, session_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    session_path = cache_dir / "session.jsonl"
    metadata_path = cache_dir / "metadata.json"

    cache_status = "hit"
    if force or not session_path.exists() or not _metadata_matches(metadata_path, info):
        cache_status = "refreshed" if session_path.exists() else "downloaded"
        tmp_path = cache_dir / "session.jsonl.tmp"
        try:
            _write_stream(info["url"], codec, tmp_path)
            os.replace(tmp_path, session_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        metadata = {
            "session_id": session_id,
            "path": str(session_path),
            "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "signature": _signature(info),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True))

    return CachedSession(
        session_id=session_id,
        path=str(session_path),
        metadata_path=str(metadata_path),
        cache_status=cache_status,
        content_codec=codec,
        raw_bytes=info.get("raw_bytes"),
        stored_bytes=info.get("stored_bytes"),
        event_count=int(info.get("event_count") or 0),
        last_active=info.get("last_active"),
    )
