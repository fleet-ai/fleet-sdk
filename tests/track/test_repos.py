"""Unit tests for repo capture, registry, and discovery.

These tests don't shell to git for the URL-normalize / registry / scan
paths — they construct repos in tmp_path with a fake `.git` dir + a
file that mimics what `git remote get-url origin` would print.

For the `capture_repo` paths we DO use real git to keep the test
honest end-to-end; capture is module-cached so we reset the cache
each test to avoid bleed-through.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from fleet.track import repos as repos_mod
from fleet.track.paths import TrackPaths
from fleet.track.repos import (
    RepoRegistry,
    _walk_for_repos,
    capture_repo,
    default_scan_roots,
    normalize_repo_url,
    resolve_repo_cwd,
    scan_for_repo,
)


# ------------------------------------------------------------------ #
# Fixtures                                                              #
# ------------------------------------------------------------------ #


@pytest.fixture(autouse=True)
def _reset_capture_cache():
    """`capture_repo` memoizes per process. Reset between tests so
    fixtures created in one test don't leak into another."""
    repos_mod._capture_cache.clear()
    yield
    repos_mod._capture_cache.clear()


def _make_repo(path: Path, *, origin_url: str | None = None) -> Path:
    """Initialize a git repo at `path` with optional origin remote."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    if origin_url:
        subprocess.run(
            ["git", "remote", "add", "origin", origin_url],
            cwd=path,
            check=True,
        )
    return path


# ------------------------------------------------------------------ #
# normalize_repo_url                                                   #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "variant,expected",
    [
        ("git@github.com:fleet-ai/fleet-sdk.git", "github.com/fleet-ai/fleet-sdk"),
        ("git@github.com:fleet-ai/fleet-sdk", "github.com/fleet-ai/fleet-sdk"),
        (
            "ssh://git@github.com/fleet-ai/fleet-sdk.git",
            "github.com/fleet-ai/fleet-sdk",
        ),
        ("https://github.com/fleet-ai/fleet-sdk", "github.com/fleet-ai/fleet-sdk"),
        ("https://github.com/fleet-ai/fleet-sdk.git", "github.com/fleet-ai/fleet-sdk"),
        ("https://GITHUB.com/Fleet-AI/Fleet-SDK.git", "github.com/fleet-ai/fleet-sdk"),
    ],
)
def test_normalize_collapses_equivalent_urls(variant: str, expected: str):
    """All real-world remote-URL forms for the same repo must produce
    the same key. Drift here is an outage waiting to happen — the
    registry would split one repo into multiple keys and resume would
    silently miss checkouts."""
    assert normalize_repo_url(variant) == expected


def test_normalize_handles_empty():
    assert normalize_repo_url("") == ""


def test_normalize_passes_through_unrecognized():
    """Better to under-canonicalize than mangle. An odd URL we don't
    recognize as ssh/scp/https comes out lowercased and `.git`-stripped
    but otherwise intact."""
    assert normalize_repo_url("Some/Weird/Path.git") == "some/weird/path"


# ------------------------------------------------------------------ #
# capture_repo                                                          #
# ------------------------------------------------------------------ #


def test_capture_returns_url_and_subpath(tmp_path: Path):
    repo = _make_repo(
        tmp_path / "myrepo",
        origin_url="git@github.com:test/myrepo.git",
    )
    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)
    info = capture_repo(str(sub))
    assert info.url == "github.com/test/myrepo"
    # Resolve symlinks for both sides since git rev-parse may return
    # the resolved form on platforms where /tmp is a symlink (macOS).
    assert Path(info.root).resolve() == repo.resolve()
    assert info.subpath == "src/deep"
    assert info.origin_cwd == str(sub)


def test_capture_outside_git_repo_returns_none_url(tmp_path: Path):
    info = capture_repo(str(tmp_path))
    assert info.url is None
    assert info.root is None
    assert info.subpath == ""
    assert info.origin_cwd == str(tmp_path)


def test_capture_repo_without_origin(tmp_path: Path):
    """Repo with no `origin` remote: root is found, url is None."""
    repo = _make_repo(tmp_path / "no-origin")
    info = capture_repo(str(repo))
    assert info.url is None
    assert info.root is not None  # root IS known


def test_capture_caches_per_cwd(tmp_path: Path, monkeypatch):
    """Second call must not shell out again."""
    repo = _make_repo(tmp_path / "r", origin_url="git@github.com:t/r.git")
    cwd = str(repo)
    capture_repo(cwd)

    calls = {"n": 0}
    real = repos_mod._git

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(repos_mod, "_git", counted)

    capture_repo(cwd)
    assert calls["n"] == 0  # cached, no new git invocations


def test_capture_upserts_into_registry(tmp_path: Path):
    """Caller can pass a registry; capture stamps the (url, root) pair
    into it as a side-effect so resume lookups succeed without an
    explicit registry warm-up step."""
    paths = TrackPaths.under(tmp_path / "fleet")
    paths.ensure_track_dir()
    reg = RepoRegistry(paths=paths)
    repo = _make_repo(tmp_path / "r", origin_url="git@github.com:t/r.git")
    capture_repo(str(repo), registry=reg)
    hits = reg.lookup("github.com/t/r")
    assert len(hits) == 1
    assert hits[0].resolve() == repo.resolve()


# ------------------------------------------------------------------ #
# RepoRegistry                                                          #
# ------------------------------------------------------------------ #


def test_registry_round_trip(tmp_path: Path):
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    r = RepoRegistry(paths=paths)
    repo_dir = tmp_path / "r"
    repo_dir.mkdir()
    r.upsert("github.com/test/r", str(repo_dir))

    # New instance reads the persisted file.
    r2 = RepoRegistry(paths=paths)
    hits = r2.lookup("github.com/test/r")
    assert len(hits) == 1
    assert hits[0] == repo_dir


def test_registry_lookup_filters_missing_paths(tmp_path: Path):
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    r = RepoRegistry(paths=paths)
    real = tmp_path / "real"
    real.mkdir()
    r.upsert("k", str(real))
    r.upsert("k", str(tmp_path / "nonexistent"))
    hits = r.lookup("k")
    assert hits == [real]


def test_registry_upsert_idempotent_updates_freshness(tmp_path: Path):
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    r = RepoRegistry(paths=paths)
    p = tmp_path / "r"
    p.mkdir()
    r.upsert("k", str(p))
    first = json.loads((paths.track_dir / "repos.json").read_text())
    first_seen = first["repos"]["k"][0]["last_seen"]
    # Second upsert: must NOT add a duplicate; must update last_seen.
    r.upsert("k", str(p))
    second = json.loads((paths.track_dir / "repos.json").read_text())
    entries = second["repos"]["k"]
    assert len(entries) == 1
    assert entries[0]["last_seen"] >= first_seen


def test_registry_freshest_first(tmp_path: Path):
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    r = RepoRegistry(paths=paths)
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    r.upsert("k", str(a))
    r.upsert("k", str(b))
    # Touch `a` again so it's the freshest.
    r.upsert("k", str(a))
    hits = r.lookup("k")
    assert hits == [a, b]


def test_registry_handles_corrupt_file(tmp_path: Path):
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    (paths.track_dir / "repos.json").write_text("this is not json")
    r = RepoRegistry(paths=paths)
    # Should not crash; just acts as empty.
    assert r.lookup("anything") == []
    # And subsequent upserts work, replacing the bad file.
    p = tmp_path / "r"
    p.mkdir()
    r.upsert("k", str(p))
    assert r.lookup("k") == [p]


def test_registry_known_paths_filters_dead(tmp_path: Path):
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    r = RepoRegistry(paths=paths)
    alive = tmp_path / "alive"
    alive.mkdir()
    r.upsert("k1", str(alive))
    r.upsert("k2", str(tmp_path / "dead"))
    paths_seen = r.known_paths()
    assert paths_seen == [alive]


# ------------------------------------------------------------------ #
# Scan                                                                  #
# ------------------------------------------------------------------ #


def test_scan_finds_matching_repo(tmp_path: Path):
    a = _make_repo(tmp_path / "a", origin_url="git@github.com:t/a.git")
    b = _make_repo(tmp_path / "b", origin_url="git@github.com:t/b.git")
    hit = scan_for_repo("github.com/t/b", roots=[tmp_path])
    assert hit is not None
    assert hit.resolve() == b.resolve()
    # And explicitly: didn't return `a`.
    assert hit.resolve() != a.resolve()


def test_scan_caches_hit_in_registry(tmp_path: Path):
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    reg = RepoRegistry(paths=paths)
    repo = _make_repo(tmp_path / "r", origin_url="git@github.com:t/r.git")
    hit = scan_for_repo("github.com/t/r", registry=reg, roots=[tmp_path])
    assert hit is not None
    # Registry now knows about it — second lookup short-circuits.
    assert reg.lookup("github.com/t/r")[0].resolve() == repo.resolve()


def test_scan_returns_none_when_no_match(tmp_path: Path):
    _make_repo(tmp_path / "a", origin_url="git@github.com:t/a.git")
    assert scan_for_repo("github.com/other/repo", roots=[tmp_path]) is None


def test_scan_skips_ignored_dirs(tmp_path: Path):
    """A repo nested under `node_modules` must NOT be reachable."""
    inner = tmp_path / "outer" / "node_modules" / "buried"
    _make_repo(inner, origin_url="git@github.com:t/buried.git")
    hit = scan_for_repo("github.com/t/buried", roots=[tmp_path])
    assert hit is None


def test_scan_respects_depth_limit(tmp_path: Path):
    """`max_depth=1` should not reach a repo that lives 3 dirs deep."""
    deep = tmp_path / "a" / "b" / "c" / "deep"
    _make_repo(deep, origin_url="git@github.com:t/deep.git")
    assert scan_for_repo("github.com/t/deep", roots=[tmp_path], max_depth=1) is None
    # But with default depth (4), it's reachable.
    assert scan_for_repo("github.com/t/deep", roots=[tmp_path]) is not None


def test_walk_yields_only_repo_roots(tmp_path: Path):
    """Internal helper: must yield each repo dir once and stop at it
    (don't keep descending into a repo's subdirs)."""
    repo = _make_repo(tmp_path / "r", origin_url="git@github.com:t/r.git")
    (repo / "src").mkdir()
    (repo / "src" / "nested").mkdir()
    yielded = list(_walk_for_repos(tmp_path, max_depth=4))
    assert repo.resolve() in [p.resolve() for p in yielded]
    # Nested non-repo dirs must NOT be yielded.
    nested = repo / "src"
    assert nested.resolve() not in [p.resolve() for p in yielded]


# ------------------------------------------------------------------ #
# default_scan_roots                                                    #
# ------------------------------------------------------------------ #


def test_default_scan_roots_includes_known_parents(tmp_path: Path, monkeypatch):
    """Auto-discovers parents of registered checkouts so users with
    non-standard layouts still get covered."""
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    reg = RepoRegistry(paths=paths)
    repo = tmp_path / "weird-place" / "myrepo"
    repo.mkdir(parents=True)
    reg.upsert("k", str(repo))
    # Pretend $HOME is empty so only registry-derived roots show up.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "fakehome"))
    (tmp_path / "fakehome").mkdir()
    roots = default_scan_roots(reg)
    assert any(r.resolve() == repo.parent.resolve() for r in roots)


# ------------------------------------------------------------------ #
# resolve_repo_cwd                                                      #
# ------------------------------------------------------------------ #


def test_resolve_uses_registry_when_present(tmp_path: Path):
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    reg = RepoRegistry(paths=paths)
    repo = tmp_path / "myrepo"
    repo.mkdir()
    reg.upsert("github.com/t/myrepo", str(repo))
    out = resolve_repo_cwd(
        repo_url="github.com/t/myrepo",
        repo_subpath="",
        origin_cwd="/fake/path",
        registry=reg,
        allow_scan=False,
    )
    assert out == str(repo)


def test_resolve_appends_subpath(tmp_path: Path):
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    reg = RepoRegistry(paths=paths)
    repo = tmp_path / "myrepo"
    (repo / "src" / "deep").mkdir(parents=True)
    reg.upsert("k", str(repo))
    out = resolve_repo_cwd(
        repo_url="k",
        repo_subpath="src/deep",
        origin_cwd=None,
        registry=reg,
        allow_scan=False,
    )
    assert out == str(repo / "src" / "deep")


def test_resolve_falls_back_to_repo_root_when_subpath_missing(tmp_path: Path):
    """Subpath might not exist on a different machine (renamed dir,
    moved subdir). Landing at the repo root is still useful."""
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    reg = RepoRegistry(paths=paths)
    repo = tmp_path / "myrepo"
    repo.mkdir()
    reg.upsert("k", str(repo))
    out = resolve_repo_cwd(
        repo_url="k",
        repo_subpath="renamed/dir",
        origin_cwd=None,
        registry=reg,
        allow_scan=False,
    )
    assert out == str(repo)


def test_resolve_falls_back_to_origin_cwd(tmp_path: Path):
    """No repo_url, but origin_cwd exists locally — that's the
    same-machine resume case (legacy or non-git sessions)."""
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    reg = RepoRegistry(paths=paths)
    real = tmp_path / "place"
    real.mkdir()
    out = resolve_repo_cwd(
        repo_url=None,
        repo_subpath=None,
        origin_cwd=str(real),
        registry=reg,
        allow_scan=False,
    )
    assert out == str(real)


def test_resolve_returns_none_when_nothing_matches(tmp_path: Path):
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    reg = RepoRegistry(paths=paths)
    out = resolve_repo_cwd(
        repo_url="github.com/unknown/repo",
        repo_subpath="",
        origin_cwd="/does/not/exist",
        registry=reg,
        allow_scan=False,
    )
    assert out is None


def test_resolve_prefers_origin_match_over_freshest(tmp_path: Path):
    """Two checkouts of the same repo. The picker shows a session
    whose origin_cwd is checkout A, but checkout B is freshest in
    the registry. The resumer should pick A — the user opened the
    session in A, so resuming there preserves continuity."""
    paths = TrackPaths.under(tmp_path / "f")
    paths.ensure_track_dir()
    reg = RepoRegistry(paths=paths)
    a = tmp_path / "ck-a"
    b = tmp_path / "ck-b"
    a.mkdir()
    b.mkdir()
    reg.upsert("k", str(a))
    reg.upsert("k", str(b))  # b is freshest
    out = resolve_repo_cwd(
        repo_url="k",
        repo_subpath="",
        origin_cwd=str(a),
        registry=reg,
        allow_scan=False,
    )
    assert out == str(a)
