"""FSEvents (Mac) / inotify (Linux) file watcher with per-path debouncing.

Uses watchdog for cross-platform support.
Debounce window: 2.5s per path — batches rapid JSONL appends into one event.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

from .sources import WATCH_ROOTS, EXCLUDE_PATTERNS

log = logging.getLogger("fleet.track.watcher")

DEBOUNCE_SECS = 2.5
EXTENSIONS = {".jsonl", ".json", ".txt"}


class _DebounceHandler:
    """Accumulates file events and fires callback after DEBOUNCE_SECS of quiet."""

    def __init__(self, callback: Callable[[list[Path]], None]) -> None:
        self._callback = callback
        self._pending: dict[str, float] = {}  # path → last-seen time
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._thread.start()

    def touch(self, path: str) -> None:
        with self._lock:
            self._pending[path] = time.monotonic()

    def _flush_loop(self) -> None:
        while True:
            time.sleep(0.5)
            now = time.monotonic()
            ready: list[Path] = []
            with self._lock:
                expired = [p for p, t in self._pending.items() if now - t >= DEBOUNCE_SECS]
                for p in expired:
                    del self._pending[p]
                    ready.append(Path(p))
            if ready:
                try:
                    self._callback(ready)
                except Exception:
                    log.exception("debounce callback error")


class FileWatcher:
    """Watches source directories and calls callback with changed paths."""

    def __init__(self, callback: Callable[[list[Path]], None]) -> None:
        if not WATCHDOG_AVAILABLE:
            raise RuntimeError("watchdog not installed — run: pip install watchdog")

        self._debounce = _DebounceHandler(callback)
        self._observer = Observer()
        self._handler = _EventHandler(self._debounce)

    def start(self) -> None:
        for root in WATCH_ROOTS:
            if root.is_dir():
                self._observer.schedule(self._handler, str(root), recursive=True)
                log.info("watching %s", root)
            else:
                log.debug("skip watch (not found): %s", root)
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=5)


if WATCHDOG_AVAILABLE:
    class _EventHandler(FileSystemEventHandler):
        def __init__(self, debounce: _DebounceHandler) -> None:
            self._debounce = debounce

        def on_modified(self, event: FileSystemEvent) -> None:
            self._handle(event)

        def on_created(self, event: FileSystemEvent) -> None:
            self._handle(event)

        def _handle(self, event: FileSystemEvent) -> None:
            if event.is_directory:
                return
            path = Path(str(event.src_path))
            if path.suffix not in EXTENSIONS:
                return
            if any(excl in path.parts for excl in EXCLUDE_PATTERNS):
                return
            self._debounce.touch(str(path))
else:
    class _EventHandler:  # type: ignore[no-redef]
        pass
