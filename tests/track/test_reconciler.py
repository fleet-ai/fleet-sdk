"""Unit tests for Reconciler."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from fleet.track.api import TrackAPIClient
from fleet.track.merkle import HashCache, MerkleTree
from fleet.track.paths import TrackPaths
from fleet.track.queue import UploadQueue
from fleet.track.reconciler import Reconciler


def _auth() -> str:
    return "test-api-key"


def _seed_file(home: Path, rel: str, content: str = "data") -> Path:
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _build_reconciler(tmp_path: Path, manifest_handler):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()

    transport = httpx.MockTransport(manifest_handler)
    client = httpx.Client(transport=transport, base_url="http://test")
    api = TrackAPIClient(client=client, auth_provider=_auth)

    queue = UploadQueue(paths)
    cache = HashCache(paths)
    f1 = _seed_file(tmp_path, ".claude/projects/x/a.jsonl", '{"a":1}\n')
    f2 = _seed_file(tmp_path, ".claude/projects/x/b.jsonl", '{"b":2}\n')
    tree = MerkleTree(cache, file_iter=[f1, f2])

    return (
        Reconciler(queue=queue, cache=cache, tree=tree, api=api),
        paths,
        queue,
        [f1, f2],
    )


def test_reconcile_first_run_enqueues_everything(tmp_path: Path):
    """Empty remote manifest → all local files are 'changed' → all enqueued."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/manifest"):
            return httpx.Response(200, json={"root_hash": "", "files": {}})
        raise AssertionError(f"unexpected {req.url}")

    reconciler, _paths, queue, files = _build_reconciler(tmp_path, handler)
    result = reconciler.reconcile("dev1")

    assert result.in_sync is False
    assert len(result.changed_paths) == 2
    # Both files are now in the queue as pending.
    assert queue.stats().get("pending", 0) == 2
    queue.close()


def test_reconcile_when_in_sync_enqueues_nothing(tmp_path: Path):
    """If remote root == local root, no uploads happen."""
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()
    queue = UploadQueue(paths)
    cache = HashCache(paths)

    f1 = _seed_file(tmp_path, ".claude/projects/x/a.jsonl", "AAA")
    tree = MerkleTree(cache, file_iter=[f1])
    local_map, local_root = tree.build()

    # Mock returns the EXACT local map as the "remote" manifest.
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"root_hash": local_root, "files": local_map})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="http://test")
    api = TrackAPIClient(client=client, auth_provider=_auth)

    reconciler = Reconciler(queue=queue, cache=cache, tree=tree, api=api)
    result = reconciler.reconcile("dev1")

    assert result.in_sync is True
    assert result.changed_paths == ()
    assert queue.stats() == {}
    queue.close()


def test_reconcile_only_enqueues_changed_files(tmp_path: Path):
    """Remote already has one file; only the other gets enqueued."""
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()
    queue = UploadQueue(paths)
    cache = HashCache(paths)

    f1 = _seed_file(tmp_path, ".claude/projects/x/a.jsonl", "AAA")
    f2 = _seed_file(tmp_path, ".claude/projects/x/b.jsonl", "BBB")
    tree = MerkleTree(cache, file_iter=[f1, f2])

    # Build local first to grab a real hash for f1; pretend that's already on remote.
    local_map, _ = tree.build()
    f1_rel = next(p for p in local_map if p.endswith("a.jsonl"))
    remote_files = {f1_rel: local_map[f1_rel]}

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"root_hash": "stale", "files": remote_files})

    transport = httpx.MockTransport(handler)
    api = TrackAPIClient(
        client=httpx.Client(transport=transport, base_url="http://test"),
        auth_provider=_auth,
    )

    reconciler = Reconciler(queue=queue, cache=cache, tree=tree, api=api)
    result = reconciler.reconcile("dev1")

    assert result.in_sync is False
    assert len(result.changed_paths) == 1
    assert result.changed_paths[0].endswith("b.jsonl")
    assert queue.stats().get("pending", 0) == 1
    queue.close()
