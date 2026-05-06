"""Unit tests for queue.py."""

from __future__ import annotations

import time
from pathlib import Path

from fleet.track.paths import TrackPaths
from fleet.track.queue import MAX_ATTEMPTS, UploadQueue


def _q(tmp_path: Path) -> UploadQueue:
    return UploadQueue(TrackPaths.under(tmp_path))


def test_enqueue_then_claim(tmp_path: Path):
    q = _q(tmp_path)
    q.enqueue("a.jsonl", "h1")
    items = q.claim_batch(n=10)
    assert len(items) == 1
    assert items[0].path == "a.jsonl"
    assert items[0].sha256 == "h1"
    assert items[0].attempts == 0
    q.close()


def test_enqueue_idempotent_on_same_pair(tmp_path: Path):
    q = _q(tmp_path)
    q.enqueue("a.jsonl", "h1")
    q.enqueue("a.jsonl", "h1")
    q.enqueue("a.jsonl", "h1")
    items = q.claim_batch(n=10)
    assert len(items) == 1
    q.close()


def test_claim_batch_marks_in_flight(tmp_path: Path):
    q = _q(tmp_path)
    q.enqueue("a.jsonl", "h1")
    q.claim_batch(n=10)
    # Re-claim immediately must not return the same item again.
    second = q.claim_batch(n=10)
    assert second == []
    assert q.stats() == {"in_flight": 1}
    q.close()


def test_mark_done_completes(tmp_path: Path):
    q = _q(tmp_path)
    q.enqueue("a.jsonl", "h1")
    q.claim_batch(n=10)
    q.mark_done("a.jsonl", "h1")
    assert q.stats() == {"done": 1}
    q.close()


def test_mark_done_prunes_older_versions_of_same_path(tmp_path: Path):
    """When v2 succeeds, v1 still pending/failed at same path is pruned."""
    q = _q(tmp_path)
    q.enqueue("a.jsonl", "h1")
    time.sleep(0.01)  # ensure enqueued_at differs
    q.enqueue("a.jsonl", "h2")

    # Claim only h2 and mark done. h1 should be pruned because it was enqueued
    # before h2 and is for the same path.
    items = q.claim_batch(n=10)
    h2_item = next(i for i in items if i.sha256 == "h2")
    q.mark_done("a.jsonl", h2_item.sha256)

    # h1 should be gone, h2 should be done.
    stats = q.stats()
    assert stats.get("done", 0) == 1
    assert stats.get("pending", 0) == 0
    q.close()


def test_mark_done_keeps_newer_versions(tmp_path: Path):
    """When v1 succeeds and v2 was enqueued AFTER, v2 stays."""
    q = _q(tmp_path)
    q.enqueue("a.jsonl", "h1")
    items = q.claim_batch(n=10)
    time.sleep(0.01)
    q.enqueue("a.jsonl", "h2")

    q.mark_done("a.jsonl", items[0].sha256)

    # h2 should still be pending (newer enqueue).
    pending = q.claim_batch(n=10)
    assert len(pending) == 1
    assert pending[0].sha256 == "h2"
    q.close()


def test_mark_failed_retries_with_backoff(tmp_path: Path):
    q = _q(tmp_path)
    q.enqueue("a.jsonl", "h1")
    q.claim_batch(n=10)
    q.mark_failed("a.jsonl", "h1", "boom")

    # Failed once should be pending again (with future next_attempt_at).
    stats = q.stats()
    assert stats.get("pending", 0) == 1

    # Cannot be claimed yet because backoff sets next_attempt_at in the future.
    items = q.claim_batch(n=10)
    assert items == []
    q.close()


def test_mark_failed_eventually_terminal(tmp_path: Path):
    q = _q(tmp_path)
    q.enqueue("a.jsonl", "h1")
    for _ in range(MAX_ATTEMPTS):
        # Reset next_attempt_at so we can keep claiming for the test.
        q._conn.execute(
            "UPDATE queue SET status='pending', next_attempt_at=0 WHERE path=? AND sha256=?",
            ("a.jsonl", "h1"),
        )
        q._conn.commit()
        q.claim_batch(n=10)
        q.mark_failed("a.jsonl", "h1", "fail")

    stats = q.stats()
    assert stats.get("failed", 0) == 1
    q.close()


def test_reset_failed_requeues(tmp_path: Path):
    q = _q(tmp_path)
    q.enqueue("a.jsonl", "h1")
    for _ in range(MAX_ATTEMPTS):
        q._conn.execute(
            "UPDATE queue SET status='pending', next_attempt_at=0 WHERE path=? AND sha256=?",
            ("a.jsonl", "h1"),
        )
        q._conn.commit()
        q.claim_batch(n=10)
        q.mark_failed("a.jsonl", "h1", "fail")

    assert q.stats().get("failed", 0) == 1
    n = q.reset_failed()
    assert n == 1
    assert q.stats().get("failed", 0) == 0
    q.close()


def test_oldest_pending_age_when_empty(tmp_path: Path):
    q = _q(tmp_path)
    assert q.oldest_pending_age() is None
    q.close()


def test_oldest_pending_age_increases_over_time(tmp_path: Path):
    q = _q(tmp_path)
    q.enqueue("a.jsonl", "h1")
    age = q.oldest_pending_age()
    assert age is not None
    assert age >= 0
    q.close()


def test_corrupt_db_is_wiped_and_reinit(tmp_path: Path):
    paths = TrackPaths.under(tmp_path)
    paths.ensure_track_dir()

    # Make the file a non-sqlite so integrity_check fails.
    paths.state_db.write_bytes(b"this is not a valid sqlite database")

    # Should not raise; should wipe and start fresh.
    q = UploadQueue(paths)
    q.enqueue("a.jsonl", "h1")
    assert q.stats() == {"pending": 1}
    q.close()


def test_separate_paths_separate_queues(tmp_path: Path):
    """Two TrackPaths in different dirs must not share state."""
    q1 = UploadQueue(TrackPaths.under(tmp_path / "one"))
    q2 = UploadQueue(TrackPaths.under(tmp_path / "two"))

    q1.enqueue("a.jsonl", "h1")

    assert q1.stats().get("pending", 0) == 1
    assert q2.stats().get("pending", 0) == 0

    q1.close()
    q2.close()


def test_delete_paths_removes_all_versions(tmp_path: Path):
    q = _q(tmp_path)
    q.enqueue(".cursor/projects/p/session.jsonl", "h1")
    q.enqueue(".cursor/projects/p/session.jsonl", "h2")
    q.enqueue(".codex/sessions/s.jsonl", "h3")

    removed = q.delete_paths([".cursor/projects/p/session.jsonl"])

    assert removed == 2
    items = q.claim_batch(n=10)
    assert [item.path for item in items] == [".codex/sessions/s.jsonl"]
    q.close()
