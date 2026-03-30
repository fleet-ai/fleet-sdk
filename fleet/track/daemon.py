"""Fleet track daemon.

Main loop:
  1. FSEvents/inotify watcher → debounce → queue
  2. Upload worker pool drains queue via presigned URLs
  3. Hourly reconciliation loop: full Merkle diff → catch FSEvents gaps
  4. SIGTERM → drain in-flight uploads → exit cleanly

Invoked by launchd/systemd as: flt track daemon
"""

from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import os
import signal
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from .api import TrackAPIClient, TrackAPIError
from .merkle import HashCache, MerkleTree
from .queue import UploadQueue
from .sources import iter_source_files, relative_to_home, source_summary
from .status import (
    TRACK_DIR,
    TrackStatus,
    clear_pid,
    write_pid,
    write_status,
)
from .uploader import UploadPool
from .watcher import FileWatcher

RECONCILE_INTERVAL = 600   # full Merkle diff every 10 minutes
HOT_FILE_INTERVAL = 120     # active session files flushed every 2 min
CONFIG_FILE = TRACK_DIR / "config.json"
LOG_FILE = TRACK_DIR / "daemon.log"


def _setup_logging() -> None:
    TRACK_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3
    )
    handler.setFormatter(
        logging.Formatter('{"time":"%(asctime)s","level":"%(levelname)s","component":"%(name)s","msg":"%(message)s"}')
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


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    config = {"device_id": _make_device_id()}
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    return config


class Daemon:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._status = TrackStatus(pid=os.getpid())
        self._queue = UploadQueue()
        self._cache = HashCache()
        self._tree = MerkleTree(self._cache)
        self._api = TrackAPIClient()
        self._pool: Optional[UploadPool] = None
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
    # Public entry point                                                   #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        _setup_logging()
        write_pid()
        cfg = _load_config()
        self._device_id = cfg["device_id"]
        self._identity = {
            "user_id": cfg.get("user_id", ""),
            "email": cfg.get("email", ""),
            "team_id": cfg.get("team_id", ""),
            "team_name": cfg.get("team_name", ""),
            "device_id": self._device_id,
            "hostname": cfg.get("hostname", ""),
            "platform": cfg.get("platform", ""),
        }
        log.info("daemon starting run_id=%s pid=%s device=%s", self._run_id, os.getpid(), self._device_id)

        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigterm)

        self._pool = UploadPool(
            on_done=self._on_upload_done,
            on_failed=self._on_upload_failed,
        )

        # Start FSEvents/inotify watcher
        try:
            watcher = FileWatcher(callback=self._on_files_changed)
            watcher.start()
            log.info("file watcher started")
        except Exception as e:
            log.warning("file watcher unavailable (%s) — polling only", e)
            watcher = None

        # Initial full sync
        self._reconcile()

        # Main loop: reconcile hourly, reset failed items, write status
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
        if watcher:
            watcher.stop()
        self._queue.close()
        self._cache.close()
        clear_pid()
        log.info("daemon stopped")

    # ------------------------------------------------------------------ #
    # FSEvents callback                                                    #
    # ------------------------------------------------------------------ #

    def _on_files_changed(self, paths: list[Path]) -> None:
        items = []
        for path in paths:
            if not path.exists():
                continue
            digest = self._cache.get_or_compute(path)
            if digest:
                rel = relative_to_home(path)
                items.append((rel, digest))

        if items:
            self._queue.enqueue_batch(items)
            log.debug("queued %d changed files", len(items))
            self._drain_queue()

    # ------------------------------------------------------------------ #
    # Reconciliation (full Merkle diff)                                   #
    # ------------------------------------------------------------------ #

    def _reconcile(self) -> None:
        run_id = str(uuid.uuid4())[:8]
        log.info("reconcile start run_id=%s", run_id)
        self._status.state = "syncing"
        self._write_status()

        try:
            remote_map = self._api.get_manifest(self._device_id)
        except TrackAPIError as e:
            log.warning("reconcile: failed to fetch manifest: %s", e)
            self._status.state = "error"
            self._status.errors = [str(e)]
            return

        # Seed confirmed_map from S3 — these are files we know are safely stored.
        with self._confirmed_lock:
            for path, digest in remote_map.items():
                self._confirmed_map.setdefault(path, digest)

        local_map, local_root = self._tree.build()
        remote_root = MerkleTree.compute_root(remote_map)

        self._status.files_total = len(local_map)

        if local_root == remote_root:
            log.info("reconcile: in sync (root=%s)", local_root[:12])
            self._status.state = "idle"
            self._status.last_sync = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return

        changed = self._tree.diff(local_map, remote_map)
        log.info("reconcile: %d files to upload", len(changed))

        items = [(p, local_map[p]) for p in changed]
        self._queue.enqueue_batch(items)
        self._drain_queue()

        self._status.state = "idle"
        self._status.last_sync = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        log.info("reconcile done run_id=%s", run_id)

    def _upload_manifest(self) -> None:
        """PUT manifest.json reflecting only files confirmed uploaded to S3.

        We never write an optimistic manifest based on local state — only files
        with a confirmed S3 PUT success are included. This means a failed upload
        won't be silently skipped on the next reconcile.
        """
        with self._confirmed_lock:
            confirmed = dict(self._confirmed_map)

        root = MerkleTree.compute_root(confirmed)
        manifest = json.dumps({
            "root_hash": root,
            **self._identity,
            "files": confirmed,
        }, separators=(",", ":"))
        try:
            url_map = self._api.get_upload_urls(self._device_id, ["manifest.json"])
            url = url_map.get("manifest.json")
            if not url:
                log.warning("manifest upload: no presigned URL returned")
                return
            import httpx
            resp = httpx.put(url, content=manifest.encode(), headers={"Content-Type": "application/octet-stream"}, timeout=30)
            if resp.status_code not in (200, 204):
                log.warning("manifest upload failed: HTTP %s", resp.status_code)
            else:
                log.info("manifest uploaded root=%s files=%d", root[:12], len(confirmed))
        except Exception as e:
            log.warning("manifest upload error: %s", e)

    # ------------------------------------------------------------------ #
    # Queue draining                                                       #
    # ------------------------------------------------------------------ #

    def _drain_queue(self) -> None:
        """Claim a batch from the queue, fetch presigned URLs, submit to pool."""
        if not self._pool:
            return

        items = self._queue.claim_batch(n=32)
        if not items:
            return

        rel_paths = [item.path for item in items]

        try:
            url_map = self._api.get_upload_urls(self._device_id, rel_paths)
        except TrackAPIError as e:
            log.warning("failed to get upload URLs: %s", e)
            for item in items:
                self._queue.mark_failed(item.path, item.sha256, str(e))
            return

        home = Path.home()
        for item in items:
            url = url_map.get(item.path)
            if not url:
                self._queue.mark_failed(item.path, item.sha256, "no presigned URL returned")
                continue
            abs_path = home / item.path
            self._pool.submit(item.path, item.sha256, abs_path, url)

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
        write_status(self._status)

    # ------------------------------------------------------------------ #
    # Signal handling                                                      #
    # ------------------------------------------------------------------ #

    def _handle_sigterm(self, signum, frame) -> None:
        log.info("received signal %s — stopping", signum)
        self._stop.set()


def main() -> None:
    Daemon().run()
