"""Unit tests for QueueDrainer."""

from __future__ import annotations

from pathlib import Path

import httpx

from fleet.track.api import TrackAPIClient
from fleet.track.drainer import QueueDrainer
from fleet.track.paths import TrackPaths
from fleet.track.queue import UploadQueue


def _auth() -> str:
    return "test-api-key"


class FakePool:
    """Pool stand-in that records every submit() instead of actually uploading."""

    def __init__(self):
        self.submissions: list[tuple[str, str, Path, str]] = []

    def submit(
        self, rel_path: str, sha256: str, abs_path: Path, presigned_url: str
    ) -> None:
        self.submissions.append((rel_path, sha256, abs_path, presigned_url))


def _build(tmp_path: Path, url_handler):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()

    transport = httpx.MockTransport(url_handler)
    client = httpx.Client(transport=transport, base_url="http://test")
    api = TrackAPIClient(client=client, auth_provider=_auth)

    queue = UploadQueue(paths)
    pool = FakePool()
    drainer = QueueDrainer(paths=paths, queue=queue, api=api, pool=pool)  # type: ignore[arg-type]
    return drainer, queue, pool, paths


def test_drain_empty_queue(tmp_path: Path):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"urls": {}})

    drainer, queue, pool, _ = _build(tmp_path, handler)
    result = drainer.drain_once("dev1")
    assert result.claimed == 0
    assert result.submitted == 0
    assert pool.submissions == []
    queue.close()


def test_drain_submits_each_item_with_its_url(tmp_path: Path):
    def handler(req: httpx.Request) -> httpx.Response:
        import json as j

        body = j.loads(req.content)
        return httpx.Response(
            200,
            json={"urls": {p: f"https://s3/{p}?sig=x" for p in body["paths"]}},
        )

    drainer, queue, pool, paths = _build(tmp_path, handler)
    queue.enqueue("a.jsonl", "h1")
    queue.enqueue("b.jsonl", "h2")

    result = drainer.drain_once("dev1")
    assert result.claimed == 2
    assert result.submitted == 2
    assert result.failed == 0
    assert {s[0] for s in pool.submissions} == {"a.jsonl", "b.jsonl"}
    # Submitted abs paths are rooted at the test home.
    for rel, _sha, abs_path, _url in pool.submissions:
        assert abs_path == paths.home / rel
    queue.close()


def test_drain_marks_failed_when_no_url_returned(tmp_path: Path):
    """Server returns an empty url map → every claimed item is marked failed."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"urls": {}})

    drainer, queue, pool, _ = _build(tmp_path, handler)
    queue.enqueue("a.jsonl", "h1")

    result = drainer.drain_once("dev1")
    assert result.claimed == 1
    assert result.submitted == 0
    assert result.failed == 1
    assert pool.submissions == []
    # Item is now pending again with a backoff timer (mark_failed sets pending if attempts < MAX).
    stats = queue.stats()
    # At least one of pending/failed accounts for it.
    assert (stats.get("pending", 0) + stats.get("failed", 0)) == 1
    queue.close()


def test_drain_marks_all_failed_on_api_error(tmp_path: Path):
    """If the API itself errors, every claimed item is marked failed (will retry)."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream broken")

    drainer, queue, pool, _ = _build(tmp_path, handler)
    queue.enqueue("a.jsonl", "h1")
    queue.enqueue("b.jsonl", "h2")

    result = drainer.drain_once("dev1")
    assert result.claimed == 2
    assert result.submitted == 0
    assert result.failed == 2
    assert pool.submissions == []
    queue.close()


def test_drain_respects_batch_size(tmp_path: Path):
    """Configured batch_size caps how many items get claimed in one pass."""

    def handler(req: httpx.Request) -> httpx.Response:
        import json as j

        body = j.loads(req.content)
        return httpx.Response(
            200, json={"urls": {p: f"https://s3/{p}" for p in body["paths"]}}
        )

    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()
    transport = httpx.MockTransport(handler)
    api = TrackAPIClient(
        client=httpx.Client(transport=transport, base_url="http://test"),
        auth_provider=_auth,
    )
    queue = UploadQueue(paths)
    pool = FakePool()
    drainer = QueueDrainer(paths=paths, queue=queue, api=api, pool=pool, batch_size=3)  # type: ignore[arg-type]

    for i in range(10):
        queue.enqueue(f"f{i}.jsonl", f"h{i}")

    result = drainer.drain_once("dev1")
    assert result.claimed == 3
    queue.close()
