"""Unit tests for merkle.py."""

from __future__ import annotations

from pathlib import Path

from fleet.track.merkle import HashCache, MerkleTree
from fleet.track.paths import TrackPaths


def _paths(tmp_path: Path) -> TrackPaths:
    return TrackPaths.under(tmp_path)


def _write(home: Path, rel: str, content: str) -> Path:
    """Write a file under home and return its absolute path."""
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_compute_root_is_deterministic():
    a = {"foo": "h1", "bar": "h2"}
    b = {"bar": "h2", "foo": "h1"}  # same map, different insertion order
    assert MerkleTree.compute_root(a) == MerkleTree.compute_root(b)


def test_compute_root_changes_when_content_changes():
    r1 = MerkleTree.compute_root({"foo": "h1"})
    r2 = MerkleTree.compute_root({"foo": "h2"})
    assert r1 != r2


def test_compute_root_empty_map_is_stable():
    assert MerkleTree.compute_root({}) == MerkleTree.compute_root({})


def test_hashcache_compute_then_cache_hit(tmp_path: Path):
    paths = _paths(tmp_path)
    cache = HashCache(paths)

    f = _write(tmp_path, "test_file.txt", "hello")
    digest = cache.get_or_compute(f)
    assert digest is not None

    # Re-read should return same digest from cache (no file change).
    digest2 = cache.get_or_compute(f)
    assert digest == digest2

    cache.close()


def test_hashcache_invalidates_on_content_change(tmp_path: Path):
    """Same path, different content (and thus different mtime+size) → new digest."""
    import time

    paths = _paths(tmp_path)
    cache = HashCache(paths)

    f = _write(tmp_path, "test_file.txt", "hello")
    digest1 = cache.get_or_compute(f)

    time.sleep(0.01)  # ensure mtime ticks
    f.write_text("hello world")
    digest2 = cache.get_or_compute(f)

    assert digest1 != digest2
    cache.close()


def test_hashcache_get_stored_digest(tmp_path: Path):
    paths = _paths(tmp_path)
    cache = HashCache(paths)
    f = _write(tmp_path, "x.txt", "abc")
    cache.get_or_compute(f)
    rel = "x.txt"
    assert cache.get_stored_digest(rel) is not None
    assert cache.get_stored_digest("nope.txt") is None
    cache.close()


def test_hashcache_nonexistent_file_returns_none(tmp_path: Path):
    paths = _paths(tmp_path)
    cache = HashCache(paths)
    digest = cache.get_or_compute(tmp_path / "does-not-exist.txt")
    assert digest is None
    cache.close()


def test_merkle_build_with_custom_iterator(tmp_path: Path):
    """Inversion of control: pass a file iterator instead of calling iter_source_files."""
    paths = _paths(tmp_path)
    cache = HashCache(paths)

    f1 = _write(tmp_path, "a.jsonl", '{"x": 1}\n')
    f2 = _write(tmp_path, "b.jsonl", '{"y": 2}\n')

    tree = MerkleTree(cache, file_iter=[f1, f2])
    file_map, root = tree.build()

    # Two files in the map, paths are relative to home.
    assert len(file_map) == 2
    assert "a.jsonl" in file_map
    assert "b.jsonl" in file_map
    # Root hash matches the deterministic computation.
    assert root == MerkleTree.compute_root(file_map)
    cache.close()


def test_merkle_diff_finds_changed_and_new(tmp_path: Path):
    paths = _paths(tmp_path)
    cache = HashCache(paths)
    tree = MerkleTree(cache, file_iter=[])

    local = {"a": "h1", "b": "h2", "c": "h3"}
    remote = {"a": "h1", "b": "DIFFERENT"}  # b changed, c new, missing-on-remote
    changed = tree.diff(local, remote)
    assert set(changed) == {"b", "c"}
    cache.close()
