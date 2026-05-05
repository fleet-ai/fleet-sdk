"""Upload worker pool.

Scrubs file content locally, then PUTs to presigned S3 URLs.
8 concurrent workers. Reads only complete lines from active JSONL files.

`Transport` is the seam tests fake. Production uses `HttpxTransport`,
backed by an `httpx.Client`; tests use `httpx.MockTransport` or a
purpose-built `RecordingTransport`.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional, Protocol

import httpx

from .scrubber import scrub_bytes

log = logging.getLogger("fleet.track.uploader")

WORKERS = 8
# Per-phase timeouts: connect/read can be short, write is generous for
# large JSONL files on slow connections.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=300.0, pool=10.0)


# ------------------------------------------------------------------ #
# Transport seam                                                       #
# ------------------------------------------------------------------ #


class Transport(Protocol):
    """Minimum surface needed to PUT a presigned URL."""

    def put(self, url: str, content: bytes) -> int:
        """Return HTTP status. Raise httpx.RequestError on network failure."""


class HttpxTransport:
    """Production transport: a real httpx.Client.

    Wraps any caller-provided client (so tests can inject MockTransport)
    or constructs one if none is given.
    """

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._client = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
        self._owns_client = client is None

    def put(self, url: str, content: bytes) -> int:
        resp = self._client.put(
            url,
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
        return resp.status_code

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


# ------------------------------------------------------------------ #
# Read + scrub                                                         #
# ------------------------------------------------------------------ #


def _read_safe(path: Path) -> Optional[bytes]:
    """Read file content safely for active JSONL files.

    Truncates to last complete newline so a partial JSON line at EOF
    (mid-write by the agent) doesn't get uploaded as malformed JSON.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        log.warning("read failed %s: %s", path, e)
        return None

    if path.suffix == ".jsonl" and data and not data.endswith(b"\n"):
        last_nl = data.rfind(b"\n")
        if last_nl > 0:
            data = data[: last_nl + 1]

    return data


def upload_one(path: Path, presigned_url: str, transport: Transport) -> bool:
    """Scrub and upload a single file. Returns True on success."""
    ok, _bytes_uploaded = _upload_one_with_size(path, presigned_url, transport)
    return ok


def _upload_one_with_size(
    path: Path,
    presigned_url: str,
    transport: Transport,
) -> tuple[bool, int]:
    """Upload one file and return whether it succeeded plus uploaded bytes."""
    data = _read_safe(path)
    if data is None:
        return False, 0

    scrubbed = scrub_bytes(data)

    try:
        status = transport.put(presigned_url, scrubbed)
        if status not in (200, 204):
            log.warning("upload %s → HTTP %s", path.name, status)
            return False, 0
        return True, len(scrubbed)
    except httpx.RequestError as e:
        log.warning("upload %s network error: %s", path.name, e)
        return False, 0


# ------------------------------------------------------------------ #
# Worker pool                                                          #
# ------------------------------------------------------------------ #


class UploadPool:
    """Thread pool for concurrent uploads with result callbacks."""

    def __init__(
        self,
        on_done: Callable[[str, str], None],
        on_failed: Callable[[str, str, str], None],
        transport: Optional[Transport] = None,
        on_uploaded_bytes: Optional[Callable[[str, int], None]] = None,
    ) -> None:
        self._on_done = on_done
        self._on_failed = on_failed
        self._on_uploaded_bytes = on_uploaded_bytes
        self._transport: Transport = transport or HttpxTransport()
        self._pool = ThreadPoolExecutor(
            max_workers=WORKERS, thread_name_prefix="track-upload"
        )
        self._in_flight: dict[str, Future] = {}
        self._lock = threading.Lock()

    def submit(
        self, rel_path: str, sha256: str, abs_path: Path, presigned_url: str
    ) -> None:
        future = self._pool.submit(self._run, rel_path, sha256, abs_path, presigned_url)
        with self._lock:
            self._in_flight[rel_path] = future

    def _run(
        self, rel_path: str, sha256: str, abs_path: Path, presigned_url: str
    ) -> None:
        try:
            ok, bytes_uploaded = _upload_one_with_size(
                abs_path,
                presigned_url,
                self._transport,
            )
            if ok:
                log.debug("uploaded %s", rel_path)
                if self._on_uploaded_bytes is not None:
                    self._on_uploaded_bytes(rel_path, bytes_uploaded)
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
