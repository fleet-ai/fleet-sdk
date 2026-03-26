"""Upload worker pool.

Scrubs file content locally, then PUTs to presigned S3 URLs.
8 concurrent workers. Reads only complete lines from active JSONL files.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path
from typing import Callable, Optional

import httpx

from .scrubber import scrub_bytes

log = logging.getLogger("fleet.track.uploader")

WORKERS = 8
UPLOAD_TIMEOUT_SECS = 120


def _read_safe(path: Path) -> Optional[bytes]:
    """
    Read file content safely for active JSONL files.
    Truncates to last complete newline to avoid partial JSON lines.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        log.warning("read failed %s: %s", path, e)
        return None

    if path.suffix == ".jsonl" and data and not data.endswith(b"\n"):
        # Trim to last complete line
        last_nl = data.rfind(b"\n")
        if last_nl > 0:
            data = data[: last_nl + 1]

    return data


def upload_one(path: Path, presigned_url: str) -> bool:
    """Scrub and upload a single file. Returns True on success."""
    data = _read_safe(path)
    if data is None:
        return False

    scrubbed = scrub_bytes(data)

    try:
        resp = httpx.put(
            presigned_url,
            content=scrubbed,
            headers={"Content-Type": "application/octet-stream"},
            timeout=UPLOAD_TIMEOUT_SECS,
        )
        if resp.status_code not in (200, 204):
            log.warning("upload %s → HTTP %s", path.name, resp.status_code)
            return False
        return True
    except httpx.RequestError as e:
        log.warning("upload %s network error: %s", path.name, e)
        return False


class UploadPool:
    """Thread pool for concurrent uploads with result callbacks."""

    def __init__(
        self,
        on_done: Callable[[str, str], None],
        on_failed: Callable[[str, str, str], None],
    ) -> None:
        self._on_done = on_done
        self._on_failed = on_failed
        self._pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="track-upload")
        self._in_flight: dict[str, Future] = {}
        self._lock = threading.Lock()

    def submit(self, rel_path: str, sha256: str, abs_path: Path, presigned_url: str) -> None:
        future = self._pool.submit(self._run, rel_path, sha256, abs_path, presigned_url)
        with self._lock:
            self._in_flight[rel_path] = future

    def _run(self, rel_path: str, sha256: str, abs_path: Path, presigned_url: str) -> None:
        try:
            ok = upload_one(abs_path, presigned_url)
            if ok:
                log.debug("uploaded %s", rel_path)
                self._on_done(rel_path, sha256)
            else:
                self._on_failed(rel_path, sha256, "upload returned failure")
        except Exception as e:
            log.exception("upload error %s", rel_path)
            self._on_failed(rel_path, sha256, str(e))
        finally:
            with self._lock:
                self._in_flight.pop(rel_path, None)

    def in_flight_count(self) -> int:
        with self._lock:
            return len(self._in_flight)

    def drain(self, timeout: float = 30.0) -> None:
        """Wait for all in-flight uploads to complete."""
        with self._lock:
            futures = list(self._in_flight.values())
        for f in futures:
            try:
                f.result(timeout=timeout)
            except Exception:
                pass

    def shutdown(self) -> None:
        self.drain()
        self._pool.shutdown(wait=False)
