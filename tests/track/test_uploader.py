"""Unit tests for uploader.py."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import httpx

from fleet.track.uploader import (
    HttpxTransport,
    Transport,
    UploadPool,
    _read_safe,
    upload_one,
)


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #


class RecordingTransport:
    """Records every put() call. Test analog to HttpxTransport."""

    def __init__(
        self, status_for_url: Optional[dict] = None, raise_on_url: Optional[str] = None
    ) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self._statuses = status_for_url or {}
        self._raise_on = raise_on_url

    def put(self, url: str, content: bytes) -> int:
        self.calls.append((url, content))
        if self._raise_on and url == self._raise_on:
            raise httpx.RequestError("simulated network failure")
        return self._statuses.get(url, 200)


# ------------------------------------------------------------------ #
# _read_safe                                                           #
# ------------------------------------------------------------------ #


def test_read_safe_returns_full_content_for_complete_file(tmp_path: Path):
    f = tmp_path / "x.jsonl"
    f.write_text('{"a": 1}\n{"b": 2}\n')
    assert _read_safe(f) == b'{"a": 1}\n{"b": 2}\n'


def test_read_safe_trims_partial_trailing_jsonl_line(tmp_path: Path):
    f = tmp_path / "x.jsonl"
    f.write_text('{"a": 1}\n{"b":')  # partial second line — no trailing newline
    assert _read_safe(f) == b'{"a": 1}\n'


def test_read_safe_does_not_trim_non_jsonl(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("hello world without newline")
    assert _read_safe(f) == b"hello world without newline"


def test_read_safe_missing_file_returns_none(tmp_path: Path):
    assert _read_safe(tmp_path / "does-not-exist.jsonl") is None


# ------------------------------------------------------------------ #
# upload_one                                                           #
# ------------------------------------------------------------------ #


def test_upload_one_success(tmp_path: Path):
    f = tmp_path / "x.jsonl"
    f.write_text('{"hello": "world"}\n')
    transport = RecordingTransport()
    ok = upload_one(f, "https://s3/x", transport)
    assert ok is True
    assert len(transport.calls) == 1
    url, body = transport.calls[0]
    assert url == "https://s3/x"
    # Scrubber is applied: identity content here, no rules fire, body matches input.
    assert body == b'{"hello": "world"}\n'


def test_upload_one_scrubs_secrets(tmp_path: Path):
    f = tmp_path / "x.jsonl"
    f.write_text('{"key": "AKIAIOSFODNN7EXAMPLE"}\n')
    transport = RecordingTransport()
    upload_one(f, "https://s3/x", transport)
    _, body = transport.calls[0]
    assert b"AKIAIOSFODNN7EXAMPLE" not in body
    assert b"REDACTED" in body


def test_upload_one_returns_false_on_4xx(tmp_path: Path):
    f = tmp_path / "x.jsonl"
    f.write_text("hi")
    transport = RecordingTransport(status_for_url={"https://s3/x": 403})
    assert upload_one(f, "https://s3/x", transport) is False


def test_upload_one_returns_false_on_network_error(tmp_path: Path):
    f = tmp_path / "x.jsonl"
    f.write_text("hi")
    transport = RecordingTransport(raise_on_url="https://s3/x")
    assert upload_one(f, "https://s3/x", transport) is False


def test_upload_one_returns_false_when_file_unreadable(tmp_path: Path):
    transport = RecordingTransport()
    assert upload_one(tmp_path / "ghost.jsonl", "https://s3/x", transport) is False
    assert transport.calls == []


# ------------------------------------------------------------------ #
# UploadPool                                                           #
# ------------------------------------------------------------------ #


def test_pool_calls_on_done_for_success(tmp_path: Path):
    f = tmp_path / "x.jsonl"
    f.write_text("ok")

    done: list[tuple[str, str]] = []
    failed: list[tuple[str, str, str]] = []
    pool = UploadPool(
        on_done=lambda p, s: done.append((p, s)),
        on_failed=lambda p, s, e: failed.append((p, s, e)),
        transport=RecordingTransport(),
    )

    pool.submit("rel/x.jsonl", "h1", f, "https://s3/x")
    pool.drain(timeout=5)
    pool.shutdown()

    assert done == [("rel/x.jsonl", "h1")]
    assert failed == []


def test_pool_calls_on_failed_for_4xx(tmp_path: Path):
    f = tmp_path / "x.jsonl"
    f.write_text("ok")

    done: list = []
    failed: list = []
    pool = UploadPool(
        on_done=lambda p, s: done.append((p, s)),
        on_failed=lambda p, s, e: failed.append((p, s, e)),
        transport=RecordingTransport(status_for_url={"https://s3/x": 403}),
    )

    pool.submit("rel/x.jsonl", "h1", f, "https://s3/x")
    pool.drain(timeout=5)
    pool.shutdown()

    assert done == []
    assert len(failed) == 1
    assert failed[0][0] == "rel/x.jsonl"


def test_pool_in_flight_count_drops_after_completion(tmp_path: Path):
    """A barrier transport ensures we can observe in_flight > 0 before draining."""
    f = tmp_path / "x.jsonl"
    f.write_text("ok")

    release = threading.Event()

    class BlockingTransport:
        def put(self, url: str, content: bytes) -> int:
            release.wait(timeout=5)
            return 200

    pool = UploadPool(
        on_done=lambda *_: None,
        on_failed=lambda *_: None,
        transport=BlockingTransport(),
    )
    pool.submit("rel/x.jsonl", "h1", f, "https://s3/x")

    # Spin briefly waiting for the worker to claim the future.
    deadline = time.monotonic() + 1.0
    while pool.in_flight_count() == 0 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert pool.in_flight_count() >= 1
    release.set()
    pool.drain(timeout=5)
    assert pool.in_flight_count() == 0
    pool.shutdown()


def test_httpx_transport_uses_injected_client():
    """HttpxTransport with a MockTransport-backed client routes correctly."""
    captured = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append((str(req.url), req.content))
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport: Transport = HttpxTransport(client=client)
    assert transport.put("https://s3.example/path?sig=x", b"payload") == 200
    assert captured == [("https://s3.example/path?sig=x", b"payload")]
    client.close()
