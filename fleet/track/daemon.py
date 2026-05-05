"""Fleet track daemon.

V1 is intentionally simple: periodic full reconciliation is the source of truth.
The daemon scans local session files, diffs them against the remote manifest,
uploads whole changed files, then uploads a new manifest after successful PUTs.

Main loop:
  1. Initial full reconcile on startup.
  2. Upload worker pool drains queue via presigned URLs.
  3. Reconciliation loop: full Merkle diff every RECONCILE_INTERVAL.
  4. SIGTERM → drain in-flight uploads → exit cleanly.

Invoked by launchd/systemd as: flt track daemon
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import signal
import threading
import time
import uuid
from typing import TYPE_CHECKING, Optional

from .api import TrackAPIClient, TrackAPIError
from .drainer import QueueDrainer
from .merkle import HashCache, MerkleTree
from .paths import TrackPaths
from .queue import UploadQueue
from .reconciler import Reconciler
from .sources import source_summary
from .status import (
    TrackStatus,
    clear_pid,
    write_pid,
    write_status,
)
from .uploader import HttpxTransport, Transport, UploadPool

if TYPE_CHECKING:
    from .reconciler import ReconcileResult

RECONCILE_INTERVAL = 600  # full Merkle diff every 10 minutes


def _setup_logging(paths: TrackPaths) -> None:
    paths.ensure_track_dir()
    handler = logging.handlers.RotatingFileHandler(
        paths.log_file, maxBytes=10 * 1024 * 1024, backupCount=3
    )
    handler.setFormatter(
        logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s","component":"%(name)s","msg":"%(message)s"}'
        )
    )
    root = logging.getLogger()
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler())
    root.setLevel(logging.INFO)


log = logging.getLogger("fleet.track.daemon")


def _make_device_id() -> str:
    """
    Stable human-readable device ID: {hostname}-{uuid8}.
    e.g. "macbook-pro-a1b2c3d4"
    """
    import re
    import socket

    hostname = re.sub(r"[^a-z0-9-]", "-", socket.gethostname().lower())[:20].strip("-")
    suffix = str(uuid.uuid4()).replace("-", "")[:8]
    return f"{hostname}-{suffix}"


def _load_config(paths: TrackPaths) -> dict:
    if paths.config_file.exists():
        return json.loads(paths.config_file.read_text())
    config = {"device_id": _make_device_id()}
    paths.ensure_track_dir()
    paths.config_file.write_text(json.dumps(config, indent=2))
    return config


def _identity_from_config(cfg: dict, device_id: str) -> dict:
    return {
        "user_id": cfg.get("user_id", ""),
        "email": cfg.get("email", ""),
        "team_id": cfg.get("team_id", ""),
        "team_name": cfg.get("team_name", ""),
        "device_id": device_id,
        "hostname": cfg.get("hostname", ""),
        "platform": cfg.get("platform", ""),
    }


class Daemon:
    def __init__(
        self,
        paths: Optional[TrackPaths] = None,
        *,
        queue: Optional[UploadQueue] = None,
        cache: Optional[HashCache] = None,
        tree: Optional[MerkleTree] = None,
        api: Optional[TrackAPIClient] = None,
        upload_transport: Optional[Transport] = None,
    ) -> None:
        self._paths = paths or TrackPaths.default()
        self._stop = threading.Event()
        self._status = TrackStatus(pid=os.getpid())
        self._queue = queue or UploadQueue(self._paths)
        self._cache = cache or HashCache(self._paths)
        self._tree = tree or MerkleTree(self._cache)
        self._api = api or TrackAPIClient()
        self._upload_transport = upload_transport
        self._pool: Optional[UploadPool] = None
        self._reconciler = Reconciler(
            queue=self._queue, cache=self._cache, tree=self._tree, api=self._api
        )
        self._drainer: Optional[QueueDrainer] = None  # built once pool exists
        self._bytes_uploaded = 0
        self._run_id = str(uuid.uuid4())[:8]
        self._device_id: str = ""
        self._identity: dict = {}
        # confirmed_map: path → sha256 for every file we KNOW is on S3.
        # Populated from the remote manifest at startup and updated only on
        # successful upload callbacks. Used to build an honest manifest.json.
        self._confirmed_map: dict[str, str] = {}
        self._confirmed_lock = threading.Lock()
        self._manifest_dirty = False  # set when confirmed_map gains new entries

    # ------------------------------------------------------------------ #
    # Public entry points                                                  #
    # ------------------------------------------------------------------ #

    def run_once(self, *, device_id: Optional[str] = None) -> "ReconcileResult":  # type: ignore[name-defined]
        """One reconcile pass + drain. Test seam and `flt track daemon --once`.

        Sets up a pool inline, runs Reconciler.reconcile, then Drainer.drain_once
        until the queue is empty, waits for in-flight uploads, then uploads the
        manifest if any files were confirmed. Does NOT install signal handlers.
        """
        if device_id is None:
            cfg = _load_config(self._paths)
            device_id = cfg["device_id"]
            self._identity = _identity_from_config(cfg, device_id)
        elif not self._identity:
            self._identity = {"device_id": device_id}

        if self._pool is None:
            self._pool = UploadPool(
                on_done=self._on_upload_done,
                on_failed=self._on_upload_failed,
                transport=self._upload_transport,
            )
            self._drainer = QueueDrainer(
                paths=self._paths,
                queue=self._queue,
                api=self._api,
                pool=self._pool,
            )

        self._device_id = device_id
        result: ReconcileResult = self._reconciler.reconcile(device_id)

        # Drain until queue empty (or one drain returns claimed=0).
        assert self._drainer is not None
        while True:
            drain = self._drainer.drain_once(device_id)
            if drain.claimed == 0:
                break

        # Wait for in-flight uploads.
        self._pool.drain(timeout=60)
        if self._manifest_dirty:
            self._upload_manifest()
            self._manifest_dirty = False
        self._pool.shutdown()
        self._pool = None
        self._drainer = None
        return result

    def run(self) -> None:
        _setup_logging(self._paths)
        write_pid(self._paths)
        cfg = _load_config(self._paths)
        self._device_id = cfg["device_id"]
        self._identity = _identity_from_config(cfg, self._device_id)
        log.info(
            "daemon starting run_id=%s pid=%s device=%s",
            self._run_id,
            os.getpid(),
            self._device_id,
        )

        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigterm)

        self._pool = UploadPool(
            on_done=self._on_upload_done,
            on_failed=self._on_upload_failed,
            transport=self._upload_transport,
        )
        self._drainer = QueueDrainer(
            paths=self._paths,
            queue=self._queue,
            api=self._api,
            pool=self._pool,
        )

        # Initial full sync
        self._reconcile()

        # Main loop: reconcile periodically, reset failed items, write status.
        # V1 intentionally avoids watcher-driven whole-file uploads; changed
        # files are discovered by reconciliation.
        last_reconcile = time.monotonic()
        last_queue_reset = time.monotonic()

        while not self._stop.is_set():
            now = time.monotonic()

            if now - last_reconcile >= RECONCILE_INTERVAL:
                self._reconcile()
                last_reconcile = now

            if now - last_queue_reset >= RECONCILE_INTERVAL:
                reset = self._queue.reset_failed()
                if reset:
                    log.info("re-queued %d permanently failed items", reset)
                self._queue.remove_done()
                last_queue_reset = now

            self._drain_queue()
            # Write manifest once all pending uploads have drained.
            if self._manifest_dirty:
                stats = self._queue.stats()
                if stats.get("pending", 0) == 0 and stats.get("in_flight", 0) == 0:
                    self._upload_manifest()
                    self._manifest_dirty = False
            self._write_status()
            self._stop.wait(timeout=10)

        # Graceful shutdown
        log.info("shutting down — draining uploads")
        if self._pool:
            self._pool.drain(timeout=60)
            self._pool.shutdown()
        if self._manifest_dirty:
            self._upload_manifest()
        self._queue.close()
        self._cache.close()
        clear_pid(self._paths)
        log.info("daemon stopped")

    # ------------------------------------------------------------------ #
    # Reconciliation (full Merkle diff)                                   #
    # ------------------------------------------------------------------ #

    def _reconcile(self) -> None:
        run_id = str(uuid.uuid4())[:8]
        log.info("reconcile start run_id=%s", run_id)
        self._status.state = "syncing"
        self._write_status()

        try:
            result = self._reconciler.reconcile(self._device_id)
        except TrackAPIError as e:
            log.warning("reconcile: %s", e)
            self._status.state = "error"
            self._status.errors = [str(e)]
            return

        # Seed confirmed_map from S3 — these are files we know are safely stored.
        with self._confirmed_lock:
            for path, digest in result.remote_map.items():
                self._confirmed_map.setdefault(path, digest)

        self._status.files_total = len(result.local_map)
        self._status.last_sync = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._status.state = "idle"

        if not result.in_sync:
            self._drain_queue()

        log.info(
            "reconcile done run_id=%s changed=%d", run_id, len(result.changed_paths)
        )

    def _upload_manifest(self) -> None:
        """PUT manifest.json reflecting only files confirmed uploaded to S3.

        We never write an optimistic manifest based on local state — only files
        with a confirmed S3 PUT success are included. This means a failed upload
        won't be silently skipped on the next reconcile.
        """
        with self._confirmed_lock:
            confirmed = dict(self._confirmed_map)

        root = MerkleTree.compute_root(confirmed)
        manifest = json.dumps(
            {
                "root_hash": root,
                **self._identity,
                "files": confirmed,
            },
            separators=(",", ":"),
        )
        try:
            url_map = self._api.get_upload_urls(self._device_id, ["manifest.json"])
            url = url_map.get("manifest.json")
            if not url:
                log.warning("manifest upload: no presigned URL returned")
                return
            owned_transport = None
            transport = self._upload_transport
            if transport is None:
                owned_transport = HttpxTransport()
                transport = owned_transport
            try:
                status = transport.put(url, manifest.encode())
            finally:
                if owned_transport is not None:
                    owned_transport.close()
            if status not in (200, 204):
                log.warning("manifest upload failed: HTTP %s", status)
            else:
                log.info(
                    "manifest uploaded root=%s files=%d", root[:12], len(confirmed)
                )
        except Exception as e:
            log.warning("manifest upload error: %s", e)

    # ------------------------------------------------------------------ #
    # Queue draining                                                       #
    # ------------------------------------------------------------------ #

    def _drain_queue(self) -> None:
        """Delegate to QueueDrainer; one pass."""
        if self._drainer is None:
            return
        self._drainer.drain_once(self._device_id)

    # ------------------------------------------------------------------ #
    # Upload callbacks                                                     #
    # ------------------------------------------------------------------ #

    def _on_upload_done(self, rel_path: str, sha256: str) -> None:
        self._queue.mark_done(rel_path, sha256)
        self._status.files_synced += 1
        # Record this file as confirmed on S3 using the hash we originally computed.
        digest = self._cache.get_stored_digest(rel_path)
        if digest:
            with self._confirmed_lock:
                self._confirmed_map[rel_path] = digest
            self._manifest_dirty = True

    def _on_upload_failed(self, rel_path: str, sha256: str, error: str) -> None:
        self._queue.mark_failed(rel_path, sha256, error)
        log.warning("upload failed %s: %s", rel_path, error)

    # ------------------------------------------------------------------ #
    # Status                                                               #
    # ------------------------------------------------------------------ #

    def _write_status(self) -> None:
        stats = self._queue.stats()
        self._status.pid = os.getpid()
        self._status.queue_depth = stats.get("pending", 0) + stats.get("in_flight", 0)
        self._status.bytes_uploaded_session = self._bytes_uploaded
        self._status.sources = source_summary()
        write_status(self._paths, self._status)

    # ------------------------------------------------------------------ #
    # Signal handling                                                      #
    # ------------------------------------------------------------------ #

    def _handle_sigterm(self, signum, frame) -> None:
        log.info("received signal %s — stopping", signum)
        self._stop.set()


def main(*, once: bool = False) -> None:
    daemon = Daemon()
    if once:
        daemon.run_once()
        return
    daemon.run()
