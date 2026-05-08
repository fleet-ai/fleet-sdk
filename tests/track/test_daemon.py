"""Tests for the v1 daemon one-shot sync path."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import httpx

from fleet.track.api import TrackAPIClient
from fleet.track.daemon import Daemon
from fleet.track.merkle import HashCache, MerkleTree
from fleet.track.paths import TrackPaths
from fleet.track.queue import UploadQueue
from fleet.track.uploader import UploadPayload


def _auth() -> str:
    return "test-api-key"


def _expand_bulk_upsert(body: dict) -> list[dict]:
    """Flatten a /v1/track/sessions/bulk request body into per-row upsert dicts
    that match the old per-row endpoint shape. Tests use this so the existing
    per-row assertions continue to work after the daemon switched to bulk."""
    device_id = body["device_id"]
    return [{"device_id": device_id, **item} for item in body["items"]]


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
        if req.method == "POST" and req.url.path.endswith("/v1/track/sessions/bulk"):
            metadata_upserts.extend(_expand_bulk_upsert(json.loads(req.content)))
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
    assert upsert["content_codec"] == "raw"
    assert upsert["raw_bytes"] == len(transport.calls[0][1])
    assert upsert["stored_bytes"] == len(transport.calls[0][1])

    queue.close()
    cache.close()


def test_run_once_uploads_cursor_transcript_and_indexes_artifact(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()

    rel_path = ".cursor/projects/p1/agent-transcripts/t1/session.jsonl"
    session_file = tmp_path / rel_path
    session_file.parent.mkdir(parents=True)
    session_file.write_text('{"role":"user","content":"cursor hi"}\n')

    queue = UploadQueue(paths)
    cache = HashCache(paths)
    tree = MerkleTree(cache, file_iter=[session_file])

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
        if req.method == "POST" and req.url.path.endswith("/v1/track/sessions/bulk"):
            metadata_upserts.extend(_expand_bulk_upsert(json.loads(req.content)))
            return httpx.Response(204)
        raise AssertionError(f"unexpected request: {req.method} {req.url}")

    api = TrackAPIClient(
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="http://test"
        ),
        auth_provider=_auth,
    )
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
    assert result.pruned_paths == ()
    assert queue.stats().get("done") == 1

    assert [url for url, _ in transport.calls] == [
        f"https://s3.test/{rel_path}",
        "https://s3.test/manifest.json",
    ]
    manifest = json.loads(transport.calls[-1][1])
    assert manifest["files"] == {rel_path: result.local_map[rel_path]}

    upload_url_paths = [body["paths"] for _, body in api_requests]
    assert upload_url_paths == [[rel_path], ["manifest.json"]]
    assert len(metadata_upserts) == 1
    upsert = metadata_upserts[0]
    assert upsert["path"] == rel_path
    assert upsert["session"]["tool"] == "cursor"
    assert upsert["session"]["id"].startswith("cursor-")
    assert upsert["content_codec"] == "raw"

    queue.close()
    cache.close()


def test_upload_done_accepts_cursor_paths(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()
    queue = UploadQueue(paths)
    cache = HashCache(paths)
    tree = MerkleTree(cache, file_iter=[])
    daemon = Daemon(paths, queue=queue, cache=cache, tree=tree)

    rel_path = ".cursor/projects/p1/agent-transcripts/t1/session.jsonl"
    queue.enqueue(rel_path, "cursor-digest")
    daemon._confirmed_map[rel_path] = "old-digest"
    metadata_calls: list[tuple[str, str]] = []

    def record_metadata(
        path: str,
        digest: str,
        *,
        upload_payload: UploadPayload | None = None,
    ) -> None:
        metadata_calls.append((path, digest))

    daemon._upsert_session_metadata = record_metadata  # type: ignore[method-assign]

    daemon._on_upload_done(rel_path, "cursor-digest")

    assert daemon._confirmed_map[rel_path] == "cursor-digest"
    assert daemon._manifest_dirty is True
    assert metadata_calls == [(rel_path, "cursor-digest")]

    queue.close()
    cache.close()


def test_upload_done_drops_blocked_path_before_manifest_or_metadata(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()
    paths.config_file.write_text('{"blocked_session_ids":["blocked-session"]}\n')
    queue = UploadQueue(paths)
    cache = HashCache(paths)
    tree = MerkleTree(cache, file_iter=[])
    daemon = Daemon(paths, queue=queue, cache=cache, tree=tree)

    rel_path = ".claude/projects/x/blocked-session.jsonl"
    queue.enqueue(rel_path, "blocked-digest")
    daemon._confirmed_map[rel_path] = "old-digest"
    metadata_calls: list[tuple[str, str]] = []

    def record_metadata(
        path: str,
        digest: str,
        *,
        upload_payload: UploadPayload | None = None,
    ) -> None:
        metadata_calls.append((path, digest))

    daemon._upsert_session_metadata = record_metadata  # type: ignore[method-assign]

    daemon._on_upload_done(rel_path, "blocked-digest")

    assert queue.stats() == {}
    assert rel_path not in daemon._confirmed_map
    assert daemon._manifest_dirty is True
    assert metadata_calls == []

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

    def record_metadata(
        path: str,
        digest: str,
        *,
        upload_payload: UploadPayload | None = None,
    ) -> None:
        metadata_calls.append((path, digest))

    daemon._upsert_session_metadata = record_metadata  # type: ignore[method-assign]

    daemon._on_upload_done(rel_path, "fresh-digest")

    assert daemon._confirmed_map[rel_path] == "fresh-digest"
    assert metadata_calls == [(rel_path, "fresh-digest")]

    queue.close()
    cache.close()


def test_upload_done_upserts_exact_uploaded_payload_metadata(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()

    rel_path = (
        ".codex/sessions/"
        "rollout-2026-05-05T00-00-00-cccccccc-cccc-cccc-cccc-cccccccccccc.jsonl"
    )
    session_file = tmp_path / rel_path
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        '{"type":"session_meta","payload":{"id":"s3","cwd":"/tmp"}}\n'
    )

    metadata_upserts: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path.endswith("/v1/track/sessions/bulk"):
            metadata_upserts.extend(_expand_bulk_upsert(json.loads(req.content)))
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
    daemon = Daemon(paths, queue=queue, cache=cache, tree=tree, api=api)
    payload = UploadPayload(
        content=b"compressed",
        content_codec="gzip",
        raw_bytes=1000,
        stored_bytes=10,
    )

    daemon._on_upload_done(rel_path, "fresh-digest", payload)
    daemon._flush_metadata_buffer()

    assert len(metadata_upserts) == 1
    upsert = metadata_upserts[0]
    assert upsert["content_codec"] == "gzip"
    assert upsert["raw_bytes"] == 1000
    assert upsert["stored_bytes"] == 10

    queue.close()
    cache.close()


def test_confirmed_existing_metadata_upsert_omits_content_metadata(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()

    rel_path = (
        ".codex/sessions/"
        "rollout-2026-05-05T00-00-00-dddddddd-dddd-dddd-dddd-dddddddddddd.jsonl"
    )
    session_file = tmp_path / rel_path
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        '{"type":"session_meta","payload":{"id":"s4","cwd":"/tmp"}}\n'
    )

    metadata_upserts: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path.endswith("/v1/track/sessions/bulk"):
            metadata_upserts.extend(_expand_bulk_upsert(json.loads(req.content)))
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
    daemon = Daemon(paths, queue=queue, cache=cache, tree=tree, api=api)

    daemon._upsert_metadata_for_paths({rel_path: "existing-digest"})
    daemon._flush_metadata_buffer()

    assert len(metadata_upserts) == 1
    upsert = metadata_upserts[0]
    assert "content_codec" not in upsert
    assert "raw_bytes" not in upsert
    assert "stored_bytes" not in upsert

    queue.close()
    cache.close()


def test_metadata_buffer_coalesces_many_uploads_into_one_bulk_request(tmp_path: Path):
    """Workers append per upload; one main-loop flush should batch them all."""
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()

    rel_paths = [
        ".codex/sessions/"
        f"rollout-2026-05-05T00-00-00-eeeeeeee-eeee-eeee-eeee-eeeeeeeeee{i:02d}.jsonl"
        for i in range(3)
    ]
    for rel in rel_paths:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('{"type":"session_meta","payload":{"id":"s","cwd":"/tmp"}}\n')

    bulk_calls: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path.endswith("/v1/track/sessions/bulk"):
            bulk_calls.append(json.loads(req.content))
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
    tree = MerkleTree(cache, file_iter=[])
    daemon = Daemon(paths, queue=queue, cache=cache, tree=tree, api=api)
    daemon._device_id = "dev1"

    for i, rel in enumerate(rel_paths):
        daemon._on_upload_done(rel, f"sha-{i}", UploadPayload(b"x", "raw", 1, 1))

    # Workers haven't done HTTP yet — only after the flush.
    assert bulk_calls == []

    daemon._flush_metadata_buffer()

    assert len(bulk_calls) == 1
    items = bulk_calls[0]["items"]
    assert {it["path"] for it in items} == set(rel_paths)

    queue.close()
    cache.close()


def test_metadata_buffer_retains_items_when_flush_fails(tmp_path: Path):
    """A 5xx on bulk upsert must leave items buffered for the next flush."""
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()

    rel_path = (
        ".codex/sessions/"
        "rollout-2026-05-05T00-00-00-ffffffff-ffff-ffff-ffff-ffffffffff01.jsonl"
    )
    session_file = tmp_path / rel_path
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        '{"type":"session_meta","payload":{"id":"s","cwd":"/tmp"}}\n'
    )

    attempts = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path.endswith("/v1/track/sessions/bulk"):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(503, text="boom")
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
    tree = MerkleTree(cache, file_iter=[])
    daemon = Daemon(paths, queue=queue, cache=cache, tree=tree, api=api)
    daemon._device_id = "dev1"

    daemon._on_upload_done(rel_path, "fresh-sha", UploadPayload(b"x", "raw", 1, 1))
    daemon._flush_metadata_buffer()  # first attempt 503s

    assert attempts["n"] == 1
    assert len(daemon._metadata_buffer) == 1  # item retained for retry
    assert daemon._metadata_indexed.get(rel_path) is None  # not yet marked

    daemon._flush_metadata_buffer()  # second attempt succeeds

    assert attempts["n"] == 2
    assert daemon._metadata_buffer == []
    assert daemon._metadata_indexed.get(rel_path) == "fresh-sha"

    queue.close()
    cache.close()


def test_drain_queue_tight_loops_until_drainer_empty(tmp_path: Path):
    """`_drain_queue` must call `drain_once` until claimed=0 in one main-loop
    iteration, instead of one drain per 10s sleep. This is the dispatch-throughput
    fix — without it, a 1000-file backlog needed ~30 main-loop sleeps to dispatch."""
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()
    queue = UploadQueue(paths)
    cache = HashCache(paths)
    tree = MerkleTree(cache, file_iter=[])
    daemon = Daemon(paths, queue=queue, cache=cache, tree=tree)
    daemon._device_id = "dev1"

    class CountingDrainer:
        """Returns claimed=N for the first 3 calls, then 0. Records each call."""

        def __init__(self):
            self.calls = 0

        def drain_once(self, device_id: str):
            from fleet.track.drainer import DrainResult

            self.calls += 1
            if self.calls <= 3:
                return DrainResult(claimed=10, submitted=10, failed=0)
            return DrainResult(claimed=0, submitted=0, failed=0)

    counter = CountingDrainer()
    daemon._drainer = counter  # type: ignore[assignment]

    daemon._drain_queue()

    assert counter.calls == 4, "drain should loop until claimed=0, then stop"

    queue.close()
    cache.close()
