from __future__ import annotations

from pathlib import Path

from fleet.track.download import ensure_local_session
from fleet.track.paths import TrackPaths


class FakeAPI:
    def __init__(self, info):
        self.info = info

    def get_session_content_info(self, session_id: str):
        assert session_id == "s1"
        return dict(self.info)


def test_ensure_local_session_downloads_and_caches(tmp_path: Path, monkeypatch):
    paths = TrackPaths.under(tmp_path)
    writes: list[tuple[str, str]] = []

    def fake_write_stream(url: str, codec: str, dest: Path) -> None:
        writes.append((url, codec))
        dest.write_bytes(b'{"ok": true}\n')

    monkeypatch.setattr("fleet.track.download._write_stream", fake_write_stream)

    info = {
        "url": "https://s3.test/session",
        "content_codec": "gzip",
        "raw_bytes": 1000,
        "stored_bytes": 200,
        "event_count": 10,
        "last_active": "2026-05-06T00:00:00Z",
    }
    first = ensure_local_session("s1", api=FakeAPI(info), paths=paths)
    second = ensure_local_session("s1", api=FakeAPI(info), paths=paths)

    assert first.cache_status == "downloaded"
    assert second.cache_status == "hit"
    assert writes == [("https://s3.test/session", "gzip")]
    assert Path(first.path).read_bytes() == b'{"ok": true}\n'


def test_ensure_local_session_refreshes_when_signature_changes(tmp_path: Path, monkeypatch):
    paths = TrackPaths.under(tmp_path)
    bodies = [b'{"v": 1}\n', b'{"v": 2}\n']

    def fake_write_stream(_url: str, _codec: str, dest: Path) -> None:
        dest.write_bytes(bodies.pop(0))

    monkeypatch.setattr("fleet.track.download._write_stream", fake_write_stream)

    base = {
        "url": "https://s3.test/session",
        "content_codec": "raw",
        "raw_bytes": 9,
        "stored_bytes": 9,
        "event_count": 1,
        "last_active": "2026-05-06T00:00:00Z",
    }
    ensure_local_session("s1", api=FakeAPI(base), paths=paths)
    changed = {**base, "event_count": 2}
    refreshed = ensure_local_session("s1", api=FakeAPI(changed), paths=paths)

    assert refreshed.cache_status == "refreshed"
    assert Path(refreshed.path).read_bytes() == b'{"v": 2}\n'
