"""Tests for the v1 daemon one-shot sync path."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional, Tuple

import httpx

from fleet.track.api import TrackAPIClient
from fleet.track.daemon import Daemon
from fleet.track.merkle import HashCache, MerkleTree
from fleet.track.paths import TrackPaths
from fleet.track.queue import UploadQueue


def _auth() -> Optional[Tuple[str, str]]:
    return ("jwt", "team")


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self._lock = threading.Lock()

    def put(self, url: str, content: bytes) -> int:
        with self._lock:
            self.calls.append((url, content))
        return 200


def test_run_once_reconciles_uploads_file_and_manifest(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()

    rel_path = (
        ".codex/sessions/"
        "rollout-2026-05-05T00-00-00-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
    )
    session_file = tmp_path / rel_path
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        '{"type":"session_meta","payload":{"id":"s1","cwd":"/tmp"}}\n'
    )

    api_requests: list[tuple[str, dict]] = []
    metadata_upserts: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path.endswith("/v1/track/manifest"):
            return httpx.Response(200, json={"root_hash": "", "files": {}})
        if req.method == "POST" and req.url.path.endswith("/v1/track/upload-urls"):
            body = json.loads(req.content)
            api_requests.append((req.url.path, body))
            return httpx.Response(
                200,
                json={"urls": {p: f"https://s3.test/{p}" for p in body["paths"]}},
            )
        if req.method == "POST" and "/v1/track/sessions/" in req.url.path:
            metadata_upserts.append(json.loads(req.content))
            return httpx.Response(204)
        raise AssertionError(f"unexpected request: {req.method} {req.url}")

    api = TrackAPIClient(
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="http://test"
        ),
        auth_provider=_auth,
    )
    queue = UploadQueue(paths)
    cache = HashCache(paths)
    tree = MerkleTree(cache, file_iter=[session_file])
    transport = RecordingTransport()

    daemon = Daemon(
        paths,
        queue=queue,
        cache=cache,
        tree=tree,
        api=api,
        upload_transport=transport,
    )

    result = daemon.run_once(device_id="dev1")

    assert result.in_sync is False
    assert result.changed_paths == (rel_path,)

    uploaded_urls = [url for url, _ in transport.calls]
    assert uploaded_urls == [
        f"https://s3.test/{rel_path}",
        "https://s3.test/manifest.json",
    ]

    manifest = json.loads(transport.calls[-1][1])
    assert manifest["device_id"] == "dev1"
    assert manifest["files"] == {rel_path: result.local_map[rel_path]}
    assert daemon._status.bytes_uploaded_session == len(transport.calls[0][1])

    upload_url_paths = [body["paths"] for _, body in api_requests]
    assert upload_url_paths == [[rel_path], ["manifest.json"]]
    assert len(metadata_upserts) == 1
    upsert = metadata_upserts[0]
    assert upsert["device_id"] == "dev1"
    assert upsert["path"] == rel_path
    assert upsert["session"]["id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert upsert["session"]["tool"] == "codex"
    assert upsert["session"]["cwd"] == "/tmp"
    assert upsert["session"]["event_count"] == 1
    assert upsert["session"]["metadata"]["origin_cwd"] == "/tmp"

    queue.close()
    cache.close()


def test_upload_done_uses_callback_digest_instead_of_stale_cache(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()
    queue = UploadQueue(paths)
    cache = HashCache(paths)
    tree = MerkleTree(cache, file_iter=[])
    daemon = Daemon(paths, queue=queue, cache=cache, tree=tree)

    rel_path = ".codex/sessions/2026/05/05/rollout-session.jsonl"
    cache._conn.execute(
        """
        INSERT OR REPLACE INTO file_hashes (path, mtime, size, sha256, last_seen)
        VALUES (?, ?, ?, ?, ?)
        """,
        (rel_path, 0.0, 0, "stale-digest", 0),
    )
    cache._conn.commit()
    metadata_calls: list[tuple[str, str]] = []

    def record_metadata(path: str, digest: str) -> None:
        metadata_calls.append((path, digest))

    daemon._upsert_session_metadata = record_metadata  # type: ignore[method-assign]

    daemon._on_upload_done(rel_path, "fresh-digest")

    assert daemon._confirmed_map[rel_path] == "fresh-digest"
    assert metadata_calls == [(rel_path, "fresh-digest")]

    queue.close()
    cache.close()
