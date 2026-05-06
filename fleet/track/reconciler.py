"""Full Merkle reconciliation pass.

Orchestrates: fetch remote manifest → build local merkle → diff → enqueue.
Pulled out of `Daemon` so a test can drive a single pass against a
`MockTransport` and a fixture filesystem and assert exactly which files
got enqueued, without spinning up the daemon thread.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .api import TrackAPIClient
from .blocklist import TrackBlocklist
from .merkle import HashCache, MerkleTree
from .queue import UploadQueue

log = logging.getLogger("fleet.track.reconciler")


@dataclass(frozen=True)
class ReconcileResult:
    in_sync: bool
    changed_paths: tuple[str, ...]
    pruned_paths: tuple[str, ...]
    local_map: dict[str, str]
    remote_map: dict[str, str]
    local_root: str
    remote_root: str


class Reconciler:
    """One full sync pass."""

    def __init__(
        self,
        *,
        queue: UploadQueue,
        cache: HashCache,
        tree: MerkleTree,
        api: TrackAPIClient,
    ) -> None:
        self._queue = queue
        self._cache = cache
        self._tree = tree
        self._api = api

    def reconcile(self, device_id: str) -> ReconcileResult:
        """Fetch remote manifest, build local merkle, enqueue diff.

        Idempotent: calling twice in a row when nothing has changed is a no-op
        (returns `in_sync=True` and enqueues nothing).
        """
        remote_map_raw = self._api.get_manifest(device_id)
        local_map_raw, _local_root_raw = self._tree.build()
        blocklist = TrackBlocklist.from_paths(self._cache._paths)
        local_map, pruned_local = _prune_unsupported_manifest_paths(
            local_map_raw,
            blocklist=blocklist,
        )
        remote_map, pruned_remote = _prune_unsupported_manifest_paths(
            remote_map_raw,
            blocklist=blocklist,
        )
        pruned_paths = tuple(sorted(set(pruned_local) | set(pruned_remote)))
        local_root = MerkleTree.compute_root(local_map)
        remote_root = MerkleTree.compute_root(remote_map)

        if local_root == remote_root:
            log.info("reconcile in sync (root=%s)", local_root[:12])
            return ReconcileResult(
                in_sync=True,
                changed_paths=(),
                pruned_paths=pruned_paths,
                local_map=local_map,
                remote_map=remote_map,
                local_root=local_root,
                remote_root=remote_root,
            )

        changed = self._tree.diff(local_map, remote_map)
        log.info("reconcile: %d files to upload", len(changed))
        items = [(p, local_map[p]) for p in changed]
        self._queue.enqueue_batch(items)

        return ReconcileResult(
            in_sync=False,
            changed_paths=tuple(changed),
            pruned_paths=pruned_paths,
            local_map=local_map,
            remote_map=remote_map,
            local_root=local_root,
            remote_root=remote_root,
        )

    def confirmed_seed(self, remote_map: dict[str, str]) -> dict[str, str]:
        """Initial seed for the Daemon's `confirmed_map`: every file the
        remote manifest already has is treated as confirmed-on-S3."""
        return dict(remote_map)


def _prune_unsupported_manifest_paths(
    file_map: dict[str, str],
    *,
    blocklist: TrackBlocklist | None = None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Drop paths that are no longer part of remote sync.

    Includes locally blocked paths so they are neither uploaded nor kept in the
    advertised manifest.
    """
    kept: dict[str, str] = {}
    pruned: list[str] = []
    for path, digest in file_map.items():
        if _is_unsupported_manifest_path(path) or (
            blocklist is not None and blocklist.is_blocked_path(path)
        ):
            pruned.append(path)
        else:
            kept[path] = digest
    return kept, tuple(sorted(pruned))


def _is_unsupported_manifest_path(_path: str) -> bool:
    return False
