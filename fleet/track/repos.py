"""Repo identity + local checkout discovery.

Cross-machine resume needs to map a `repo_url` (canonical key) to a
local checkout path. The local cwd a session was created in
(`/Users/trent/git/fleet-sdk`) doesn't survive crossing machines —
the same repo lives at different absolute paths on different
hosts. So we key on `repo_url` instead and resolve to a local path
at resume time.

Three pieces:

  1. **Capture** — `capture_repo(cwd)` shells to git to learn the
     remote URL and repo root for a given directory. Used by
     ingest paths (NativeFilesSessionStore, daemon) to stamp
     `metadata.repo_url` / `repo_subpath` / `origin_cwd` on
     sessions.

  2. **Registry** — `RepoRegistry` (file-backed at
     `~/.fleet/track/repos.json`) caches `repo_url → [local
     checkout paths]`. Self-warms via every `capture_repo()`
     call; self-survives across daemon restarts.

  3. **Scan** — `scan_for_repo(url)` walks default and
     auto-discovered roots looking for a local checkout when
     the registry doesn't have one cached. Last resort; cached
     on hit.

URL normalization is the load-bearing detail: `git@github.com:org/repo.git`,
`https://github.com/org/repo`, and `ssh://git@github.com/org/repo` are
all the same repo and must collapse to the same key. See
`normalize_repo_url`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .paths import TrackPaths

log = logging.getLogger("fleet.track.repos")


# ------------------------------------------------------------------ #
# Repo capture                                                         #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class RepoInfo:
    """What we learn about the git repo a cwd lives in.

    `url` — normalized canonical key (see `normalize_repo_url`). None
        when the cwd isn't in any git repo, or when the repo has no
        `origin` remote (rare for modern workflows).
    `root` — absolute path to the repo's top-level directory.
    `subpath` — cwd relative to `root`, posix-style. Empty string when
        cwd == root.
    `origin_cwd` — the absolute cwd that was passed in. Kept verbatim
        for fallback resolution and forensics.
    """

    url: Optional[str]
    root: Optional[str]
    subpath: str
    origin_cwd: str


# Module-level cache so repeated `capture_repo()` calls (one per session
# during a snapshot fetch) only shell out once per cwd.
_capture_cache: dict[str, RepoInfo] = {}
_capture_lock = threading.Lock()


def capture_repo(cwd: str, *, registry: Optional["RepoRegistry"] = None) -> RepoInfo:
    """Run `git` once on `cwd` to learn its repo identity.

    Cached per process (thread-safe). When `registry` is supplied, also
    upserts the discovered `(url, root)` pair so future resume lookups
    find this checkout without scanning.

    Never raises — git missing or not-a-git-repo just returns a
    `RepoInfo(url=None, root=None, subpath="", origin_cwd=cwd)`.
    """
    cwd = os.fspath(cwd)
    with _capture_lock:
        cached = _capture_cache.get(cwd)
    if cached is not None:
        if registry is not None and cached.url and cached.root:
            registry.upsert(cached.url, cached.root)
        return cached

    info = _capture_uncached(cwd)
    with _capture_lock:
        _capture_cache[cwd] = info
    if registry is not None and info.url and info.root:
        registry.upsert(info.url, info.root)
    return info


def _capture_uncached(cwd: str) -> RepoInfo:
    if not os.path.isdir(cwd):
        return RepoInfo(url=None, root=None, subpath="", origin_cwd=cwd)

    root = _git(["rev-parse", "--show-toplevel"], cwd=cwd)
    if not root:
        return RepoInfo(url=None, root=None, subpath="", origin_cwd=cwd)

    raw_url = _git(["remote", "get-url", "origin"], cwd=cwd)
    url = normalize_repo_url(raw_url) if raw_url else None

    try:
        subpath = os.path.relpath(cwd, root)
    except ValueError:
        subpath = ""
    if subpath in (".", ""):
        subpath_norm = ""
    else:
        subpath_norm = subpath.replace(os.sep, "/")

    return RepoInfo(url=url, root=root, subpath=subpath_norm, origin_cwd=cwd)


def _git(args: list[str], *, cwd: str) -> Optional[str]:
    """Run a git command, return stripped stdout or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


# ------------------------------------------------------------------ #
# URL normalization                                                    #
# ------------------------------------------------------------------ #


# `git@host:org/repo(.git)?` — the SCP-style ssh shorthand git uses.
_GIT_SCP_RE = re.compile(r"^(?P<user>[^@]+)@(?P<host>[^:]+):(?P<path>.+)$")


def normalize_repo_url(url: str) -> str:
    """Canonicalize a git remote URL.

    Goal: any of the three forms below should map to the same key.

      git@github.com:fleet-ai/fleet-sdk.git
      ssh://git@github.com/fleet-ai/fleet-sdk.git
      https://github.com/fleet-ai/fleet-sdk

    Output format: `<host>/<path-without-trailing-.git>`, all
    lowercase, host stripped of any `git@` prefix, scheme dropped.
    The leading `git@` user is dropped because it's host-conventional
    (always `git` on github/gitlab/bitbucket); preserving it just
    multiplies keys without adding identity.

    Returns the input verbatim (lowercased and `.git`-stripped) when
    we can't recognize a structure — better to under-canonicalize
    than to mangle a valid URL into the wrong key.
    """
    if not url:
        return ""
    s = url.strip()

    # Form 1: SCP-style (`git@host:path`).
    m = _GIT_SCP_RE.match(s)
    if m:
        host = m.group("host").lower()
        path = m.group("path")
        return f"{host}/{_strip_git_suffix(path).lower().lstrip('/')}"

    # Form 2 / 3: URI with scheme.
    if "://" in s:
        scheme, rest = s.split("://", 1)
        # Drop user-info if any (`git@host` → `host`).
        if "@" in rest.split("/", 1)[0]:
            _user, rest = rest.split("@", 1)
        # `host[:port]/path...` — split host + path.
        if "/" in rest:
            host, path = rest.split("/", 1)
        else:
            host, path = rest, ""
        return f"{host.lower()}/{_strip_git_suffix(path).lower().lstrip('/')}"

    # Plain `host/org/repo` form (rare). Lowercase + strip .git.
    return _strip_git_suffix(s).lower()


def _strip_git_suffix(s: str) -> str:
    return s[:-4] if s.endswith(".git") else s


# ------------------------------------------------------------------ #
# Registry — file-backed cache of url → list of local checkouts        #
# ------------------------------------------------------------------ #


@dataclass
class RegistryEntry:
    path: str
    last_seen: str  # ISO-8601


class RepoRegistry:
    """Persistent cache of `repo_url → [local checkout paths]`.

    Stored at `~/.fleet/track/repos.json` (or under a `TrackPaths`
    instance for tests). Self-warms via `capture_repo()` calls.

    Multiple checkouts per repo are explicitly supported (worktrees,
    side-by-side clones). `lookup()` returns them ordered by
    last_seen DESC; the resumer prefers the most recently used one
    matching origin_cwd, falling back to the most recent.

    File format (json):

        {
          "version": 1,
          "repos": {
            "github.com/fleet-ai/fleet-sdk": [
              {"path": "/Users/trent/git/fleet-sdk",
               "last_seen": "2026-05-04T17:00:00+00:00"},
              ...
            ],
            ...
          }
        }
    """

    SCHEMA_VERSION: int = 1

    def __init__(self, *, paths: Optional[TrackPaths] = None) -> None:
        self._paths = paths or TrackPaths.default()
        self._lock = threading.Lock()
        self._loaded = False
        self._data: dict[str, list[RegistryEntry]] = {}

    # -- public api -------------------------------------------------- #

    def lookup(self, url: str) -> list[Path]:
        """Return cached checkout paths for `url`, freshest first.
        Filters out entries whose path no longer exists on disk."""
        if not url:
            return []
        with self._lock:
            self._load_locked()
            entries = list(self._data.get(url, []))
        entries.sort(key=lambda e: e.last_seen, reverse=True)
        out: list[Path] = []
        for e in entries:
            p = Path(e.path)
            if p.is_dir():
                out.append(p)
        return out

    def upsert(self, url: str, path: str | Path) -> None:
        """Record (url, path) as a known checkout. Idempotent.
        Updates `last_seen` on each call so freshness ordering reflects
        actual usage."""
        if not url or not path:
            return
        path_str = os.fspath(path)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._load_locked()
            entries = self._data.setdefault(url, [])
            for e in entries:
                if e.path == path_str:
                    e.last_seen = now
                    self._save_locked()
                    return
            entries.append(RegistryEntry(path=path_str, last_seen=now))
            self._save_locked()

    def all_urls(self) -> list[str]:
        with self._lock:
            self._load_locked()
            return list(self._data.keys())

    def known_paths(self) -> list[Path]:
        """Every path the registry has ever seen, regardless of url.
        Used by `default_scan_roots` to seed the search with directories
        the user is already known to keep code in."""
        with self._lock:
            self._load_locked()
            paths: list[Path] = []
            for entries in self._data.values():
                for e in entries:
                    p = Path(e.path)
                    if p.is_dir():
                        paths.append(p)
        return paths

    # -- io ---------------------------------------------------------- #

    def _registry_path(self) -> Path:
        return self._paths.track_dir / "repos.json"

    def _load_locked(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        path = self._registry_path()
        if not path.exists():
            return
        try:
            blob = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            log.warning("repos.json unreadable, starting fresh: %s", e)
            return
        if not isinstance(blob, dict):
            return
        repos = blob.get("repos", {})
        if not isinstance(repos, dict):
            return
        for url, entries in repos.items():
            if not isinstance(entries, list):
                continue
            cleaned: list[RegistryEntry] = []
            for e in entries:
                if not isinstance(e, dict):
                    continue
                p = e.get("path")
                ls = e.get("last_seen", "")
                if isinstance(p, str) and p:
                    cleaned.append(
                        RegistryEntry(path=p, last_seen=ls if isinstance(ls, str) else "")
                    )
            if cleaned:
                self._data[url] = cleaned

    def _save_locked(self) -> None:
        path = self._registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = {
            "version": self.SCHEMA_VERSION,
            "repos": {
                url: [{"path": e.path, "last_seen": e.last_seen} for e in entries]
                for url, entries in self._data.items()
            },
        }
        # Write+rename for atomicity. Don't fail loudly if the directory
        # is unwritable — the registry is a cache, not a source of truth.
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(blob, indent=2))
            os.replace(tmp, path)
        except OSError as e:
            log.warning("failed to persist repos.json: %s", e)


# ------------------------------------------------------------------ #
# Filesystem scan                                                      #
# ------------------------------------------------------------------ #


# Roots we walk on demand. Users who keep code elsewhere will get
# auto-discovered roots prepended via `default_scan_roots()` (parents of
# anything the registry already knows about).
_DEFAULT_ROOT_NAMES: tuple[str, ...] = (
    "git", "code", "projects", "work", "dev", "src",
)

# Directory names we never descend into during a scan. Big and almost
# never contain a project root.
_SCAN_IGNORE: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",
    "node_modules", "venv", ".venv", "env", ".env",
    "target", "dist", "build", "out",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", ".cache",
    "Pods", "DerivedData",
})

_SCAN_DEPTH: int = 4
_SCAN_LIMIT_DIRS: int = 5000  # circuit breaker; never walk more than this


def default_scan_roots(registry: Optional[RepoRegistry] = None) -> list[Path]:
    """Pick scan roots intelligently.

    1. Standard names under `$HOME` (`~/git`, `~/code`, etc.) that exist.
    2. Parents of any path the registry has ever seen — picks up your
       actual layout without configuration.

    De-duped, ordered by explicit-name first then auto-discovered.
    """
    home = Path.home()
    roots: list[Path] = []
    seen: set[Path] = set()

    for name in _DEFAULT_ROOT_NAMES:
        p = home / name
        if p.is_dir() and p not in seen:
            roots.append(p)
            seen.add(p)

    if registry is not None:
        for known in registry.known_paths():
            parent = known.parent
            if parent.is_dir() and parent not in seen:
                roots.append(parent)
                seen.add(parent)

    # Fall back to $HOME itself if we found nothing — better than
    # returning an empty list and silently never finding anything.
    if not roots and home.is_dir():
        roots.append(home)

    return roots


def scan_for_repo(
    url: str,
    *,
    registry: Optional[RepoRegistry] = None,
    roots: Optional[Iterable[Path]] = None,
    max_depth: int = _SCAN_DEPTH,
) -> Optional[Path]:
    """Walk known roots looking for a checkout of `url`. Returns the
    first match (and caches it in the registry); None if nothing found.

    Each candidate dir is checked by running `git remote get-url
    origin` and normalizing the result against `url`. Depth-limited
    and ignore-listed (skips node_modules etc.) so the walk is bounded
    even on a deep filesystem.
    """
    if not url:
        return None

    if roots is None:
        roots = default_scan_roots(registry)

    walked = 0
    for root in roots:
        for candidate in _walk_for_repos(root, max_depth=max_depth):
            walked += 1
            if walked > _SCAN_LIMIT_DIRS:
                log.warning(
                    "scan_for_repo: hit dir-limit (%d) without finding %s",
                    _SCAN_LIMIT_DIRS, url,
                )
                return None
            raw = _git(["remote", "get-url", "origin"], cwd=str(candidate))
            if not raw:
                continue
            if normalize_repo_url(raw) == url:
                if registry is not None:
                    registry.upsert(url, candidate)
                return candidate
    return None


def _walk_for_repos(root: Path, *, max_depth: int):
    """Yield every directory at-or-under `root` that looks like a git
    repo (contains a `.git` entry — file or dir, the latter for
    worktrees). Skips ignored names and bounds depth."""
    if not root.is_dir():
        return

    # BFS with explicit depth so we can prune cleanly.
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue

        # If this dir IS a repo, yield it and stop descending. Nested
        # repos (submodules) will still be reached if the root walk
        # passes their parent dir without recognizing it as a repo.
        if any(e.name == ".git" for e in entries):
            yield current
            continue

        if depth >= max_depth:
            continue

        for e in entries:
            if not e.is_dir():
                continue
            if e.name.startswith(".") and e.name not in {".config"}:
                continue
            if e.name in _SCAN_IGNORE:
                continue
            stack.append((e, depth + 1))


# ------------------------------------------------------------------ #
# Resolve cwd from a Session's metadata                                #
# ------------------------------------------------------------------ #


def resolve_repo_cwd(
    *,
    repo_url: Optional[str],
    repo_subpath: Optional[str],
    origin_cwd: Optional[str],
    registry: Optional[RepoRegistry] = None,
    allow_scan: bool = True,
) -> Optional[str]:
    """Map session metadata to a local cwd we can launch a CLI in.

    Order:
      1. registry hit for `repo_url` (preferring an entry whose
         absolute path matches `origin_cwd` if multiple, else the
         most recent).
      2. filesystem scan, if allowed and no registry hit.
      3. `origin_cwd` itself, if it exists on disk.
      4. None — caller should print a clone hint.
    """
    if registry is None and repo_url:
        registry = RepoRegistry()

    subpath = (repo_subpath or "").strip("/").replace("\\", "/")

    if repo_url and registry is not None:
        candidates = registry.lookup(repo_url)
        if candidates:
            # Prefer an exact-match repo root that lines up with origin_cwd.
            preferred = _prefer_origin_match(candidates, origin_cwd)
            chosen = preferred or candidates[0]
            return _join_subpath(chosen, subpath)

    if repo_url and allow_scan:
        hit = scan_for_repo(repo_url, registry=registry)
        if hit is not None:
            return _join_subpath(hit, subpath)

    if origin_cwd and os.path.isdir(origin_cwd):
        return origin_cwd

    return None


def _prefer_origin_match(candidates: list[Path], origin_cwd: Optional[str]) -> Optional[Path]:
    """Of N checkouts of the same repo, pick the one whose root sits
    under or above `origin_cwd`. Otherwise None (caller picks freshest)."""
    if not origin_cwd:
        return None
    try:
        origin = Path(origin_cwd).resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    for c in candidates:
        try:
            cr = c.resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        if cr == origin or cr in origin.parents or origin in cr.parents:
            return c
    return None


def _join_subpath(repo_root: Path, subpath: str) -> str:
    """Combine repo root with subpath; verify the result exists, else
    fall back to repo root. Subpath may legitimately not exist on a
    different machine (rename, moved sub-dir) — landing at the repo
    root is still useful."""
    if not subpath:
        return str(repo_root)
    candidate = repo_root / subpath
    if candidate.is_dir():
        return str(candidate)
    return str(repo_root)
