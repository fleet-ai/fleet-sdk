"""Queue drainer.

Pulls a batch from the upload queue, requests presigned URLs from the
track API, and hands each item to the upload pool. One pass is one
`drain_once()` call — the Daemon loop just calls this on a cadence.

Pulled out of `Daemon` so tests can:
  - assert "claim_batch was called with n ≤ 100" without timing
  - assert "items with no presigned URL got marked_failed"
  - drive the drain step against a fake pool that records submissions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .api import TrackAPIClient, TrackAPIError
from .blocklist import TrackBlocklist
from .paths import TrackPaths
from .queue import UploadQueue
from .uploader import UploadPool

log = logging.getLogger("fleet.track.drainer")

# Server caps /v1/track/upload-urls at 100 paths per request. Match it
# here to avoid a 400 if a single drain claims more.
DEFAULT_BATCH_SIZE = 32


@dataclass(frozen=True)
class DrainResult:
    claimed: int
    submitted: int
    failed: int  # items marked failed (e.g. no presigned URL returned)


class QueueDrainer:
    def __init__(
        self,
        *,
        paths: TrackPaths,
        queue: UploadQueue,
        api: TrackAPIClient,
        pool: UploadPool,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._paths = paths
        self._queue = queue
        self._api = api
        self._pool = pool
        self._batch_size = batch_size

    def drain_once(self, device_id: str) -> DrainResult:
        """Claim up to `batch_size` items and submit them to the pool.

        Network failure on the upload-urls call marks every claimed item
        failed (so they retry with backoff), then returns. We do not
        retry inside this call — the daemon's main loop will run us
        again on its next tick.
        """
        items = self._queue.claim_batch(n=self._batch_size)
        if not items:
            return DrainResult(claimed=0, submitted=0, failed=0)
        claimed_count = len(items)

        blocklist = TrackBlocklist.from_paths(self._paths)
        blocked_paths = [
            item.path for item in items if blocklist.is_blocked_path(item.path)
        ]
        if blocked_paths:
            self._queue.delete_paths(blocked_paths)
            items = [item for item in items if not blocklist.is_blocked_path(item.path)]
            if not items:
                return DrainResult(claimed=claimed_count, submitted=0, failed=0)

        rel_paths = [item.path for item in items]

        try:
            url_map = self._api.get_upload_urls(device_id, rel_paths)
        except TrackAPIError as e:
            log.warning("drain: failed to get upload URLs: %s", e)
            for item in items:
                self._queue.mark_failed(item.path, item.sha256, str(e))
            return DrainResult(claimed=claimed_count, submitted=0, failed=len(items))

        home = self._paths.home
        submitted = 0
        failed = 0
        for item in items:
            url = url_map.get(item.path)
            if not url:
                self._queue.mark_failed(
                    item.path, item.sha256, "no presigned URL returned"
                )
                failed += 1
                continue
            abs_path: Path = home / item.path
            self._pool.submit(item.path, item.sha256, abs_path, url)
            submitted += 1

        return DrainResult(claimed=claimed_count, submitted=submitted, failed=failed)
