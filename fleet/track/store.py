"""Session store: the canonical place sessions live.

Two implementations, one protocol:

  - `LocalSessionStore`  — dev stub. Stores sessions in
    `~/.fleet/track/local-store/` (separate from the CLIs' native
    directories). Lets us validate the SDK end-to-end without theseus.

  - `RemoteSessionStore` — production. Hits theseus's
    `/v1/track/sessions` endpoints. Stub today; flips on once the
    server side ships.

All higher-level SDK code (`flt track ls`, `flt track resume`) talks
to a `SessionStore`; never directly to either backend.

# Why "store" and not "client"?

Because a session has a lifecycle (create → append → fork → list →
fetch → delete) that's bigger than HTTP semantics. The protocol
captures the *operations* the SDK needs, regardless of where the
data lives. The local stub and the future remote impl satisfy the
same contract.

# Sessions are a DAG

Each session can have a `forked_from` parent — like git. When you
resume a codex session in claude, the SDK creates a derived session
with `forked_from = <codex-session-id>` and `fork_point = <event-index>`.
Resuming the derived session reconstructs the full history by
walking parents. Stored as a flat collection with parent pointers;
the DAG is implicit.

Concurrency: nothing here is atomic across processes. The local
stub uses tmpfile+rename for individual writes but doesn't take
cross-process locks. Good enough for a single-developer dev loop;
revisit if we ever ship multi-process scenarios.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional, Protocol

from .paths import TrackPaths
from .unified import Event

log = logging.getLogger("fleet.track.store")


# ------------------------------------------------------------------ #
# Pagination cursor — must stay byte-compatible with the orchestrator  #
# ------------------------------------------------------------------ #
#
# A page cursor is `base64url(json({"la": <last_active or null>, "id": <id>}))`
# with `=` padding stripped. Sort key everywhere is
# `(last_active DESC NULLS LAST, id DESC)`; the cursor walks that ordering.
#
# Both ends MUST emit and consume the same bytes — see the matching helpers
# in `theseus:orchestrator/public_api/track.py:_encode_cursor`. Any drift
# is a wire-protocol break; the round-trip golden test in
# `tests/track/test_store.py::test_cursor_format_pinned` exists to catch
# accidental edits.

# Page-size limit mirrors the orchestrator's `Query(ge=1, le=200)`.
MAX_PAGE_LIMIT: int = 200
DEFAULT_PAGE_LIMIT: int = 50


def _encode_cursor(last_active: Optional[str], id: str) -> str:
    raw = json.dumps({"la": last_active, "id": id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: Optional[str]) -> Optional[dict]:
    """Inverse of `_encode_cursor`. Returns None for empty input;
    raises `ValueError` on malformed cursors so callers can map it to
    HTTP 400 / typer.BadParameter as appropriate."""
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        decoded = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError(f"invalid cursor: {e}") from e
    if not isinstance(decoded, dict) or "id" not in decoded or "la" not in decoded:
        raise ValueError(f"invalid cursor: missing keys {decoded!r}")
    return decoded


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_PAGE_LIMIT:
        return MAX_PAGE_LIMIT
    return limit


def _sort_key(s: "Session") -> tuple[int, str, str]:
    """Sort key matching the server's ORDER BY (last_active DESC NULLS LAST,
    id DESC). Returned as a positive tuple suitable for `sorted(..., reverse=True)`:

      (la_present, la_or_empty, id)

    With reverse=True:
      - Rows with last_active sort first (la_present=1 > 0).
      - Within those, larger last_active first.
      - Tiebreak by larger id.
      - NULL last_active rows sweep to the tail (la_present=0), still
        ordered by id DESC.
    """
    la = s.last_active
    return (1 if la else 0, la or "", s.id)


def _matches_query(s: "Session", query: Optional[str]) -> bool:
    """Case-insensitive substring match across the fields a user is
    likely to type (id, tool, cwd, metadata.title). Empty/None query
    matches everything.

    Server-side this becomes ILIKE on the same columns; both sides apply
    the predicate BEFORE the cursor walk so a cursor minted with a query
    keeps walking the same filtered set.
    """
    if not query:
        return True
    needle = query.lower()
    title = ""
    if isinstance(s.metadata, dict):
        t = s.metadata.get("title")
        if isinstance(t, str):
            title = t
    haystack = " ".join((s.id, s.tool or "", s.cwd or "", title)).lower()
    return needle in haystack


def _passes_cursor(s: "Session", cursor: Optional[dict]) -> bool:
    """True if `s` comes strictly AFTER the cursor's row in the global
    ordering. Mirrors the server's WHERE predicate exactly so a cursor
    minted on one side walks the same logical rows on the other."""
    if cursor is None:
        return True
    cur_la = cursor.get("la")
    cur_id = cursor["id"]
    s_la = s.last_active

    if cur_la is None:
        # Cursor sits in the NULL tail. Only NULL-la rows with smaller
        # id are still to be emitted.
        return s_la is None and s.id < cur_id

    # Cursor is in the non-null prefix. Three cases:
    if s_la is None:
        # NULL-la rows always sort AFTER any non-null cursor — emit.
        return True
    if s_la < cur_la:
        return True
    if s_la == cur_la and s.id < cur_id:
        return True
    return False


# ------------------------------------------------------------------ #
# Session record                                                       #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class Session:
    """One session in the store.

    `id` — globally unique within the store. UUIDs are recommended; the
        store doesn't enforce a format so callers can use claude/codex's
        native ids when seeding from local files.

    `tool` — which CLI emitted *this* session's events.
        Same as the unified Event.source, lifted to the session level
        for fast filtering without parsing events.

    `cwd` — the working directory the agent was run in. Used by
        the resume flow to pick the right local target dir.

    `started_at` / `last_active` — ISO-8601 timestamps. `last_active` is
        a max over the session's events; the daemon updates it on
        every sync.

    `event_count` — cached count for quick listing without reading
        the full file.

    `forked_from` / `fork_point` — branch lineage. Set on derived
        sessions (e.g. claude resume of a codex session). The original
        sessions have both as None.

    `metadata` — open-ended bag for future extensions (model, agent
        version, git_branch, anything else). Stored verbatim, not
        validated.
    """

    id: str
    tool: str  # "claude" | "codex" | "cursor" | "opencode" | "unknown"
    cwd: Optional[str] = None
    started_at: Optional[str] = None
    last_active: Optional[str] = None
    event_count: int = 0
    forked_from: Optional[str] = None
    fork_point: Optional[int] = None
    metadata: dict = field(default_factory=dict)


# ------------------------------------------------------------------ #
# Protocol                                                             #
# ------------------------------------------------------------------ #


class SessionStore(Protocol):
    """The contract. Both LocalSessionStore and (future) RemoteSessionStore
    implement this."""

    def list(
        self,
        *,
        tool: Optional[str] = None,
        cwd: Optional[str] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterable[Session]:
        """List sessions, optionally filtered.

        `since` is ISO-8601; matched against `last_active`. Implementations
        may be lazy (returning an iterator) or eager (a list); callers
        should treat it as one-shot iterable.

        For paged consumption (e.g. scripting or chaining cursors with
        the remote backend), prefer `page()` — `list()` always materialises
        the first page only, with no cursor surface.
        """
        ...

    def page(
        self,
        *,
        tool: Optional[str] = None,
        cwd: Optional[str] = None,
        since: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: Optional[str] = None,
    ) -> tuple[list[Session], Optional[str]]:
        """Return one page of sessions, plus the cursor for the next page.

        Sort: `(last_active DESC NULLS LAST, id DESC)` — same on every
        backend so cursors are interchangeable. `limit` is clamped to
        [1, MAX_PAGE_LIMIT] (matching the orchestrator). `cursor` is an
        opaque token from a prior call; pass `None` for the first page.

        `query` is a case-insensitive substring match across id/tool/cwd/
        metadata.title — used by the picker's live-search to re-query the
        store on each keystroke.

        Returns `(items, next_cursor)`. `next_cursor is None` when this
        is the last page. The cursor format is byte-compatible with
        `theseus:orchestrator/public_api/track.py` so a cursor minted on
        either side walks the same logical rows on the other.
        """
        ...

    def get(self, id: str) -> Optional[Session]:
        """Lookup by id. Accepts full id or unique prefix; returns None
        if not found, raises KeyError if prefix is ambiguous."""
        ...

    def events(self, id: str) -> Iterator[Event]:
        """Stream the session's unified Event stream.

        For root sessions: just this session's events.
        For derived (`forked_from` is set): walks the parent chain,
        yielding events from each ancestor up to its fork_point, then
        this session's own events.
        """
        ...

    def own_events(self, id: str) -> Iterator[Event]:
        """Yield only this session's own events — no fork-chain walking.

        Composing wrappers (e.g. ChainedSessionStore) walk fork chains
        themselves to span multiple stores; they need a way to ask each
        backend for one node's events without the backend also walking
        the chain (which would double-emit parents).
        """
        ...

    def create(self, session: Session, events: Iterable[Event]) -> Session:
        """Insert a new session. `session.id` must be set by the caller.
        Returns the stored session record (potentially with normalized
        timestamps/counts the store filled in)."""
        ...

    def append(self, id: str, events: Iterable[Event]) -> int:
        """Append events to an existing session. Returns the count of
        events appended. Raises KeyError if session not found."""
        ...

    def delete(self, id: str) -> bool:
        """Remove a session and its events. Returns True if deleted,
        False if it wasn't there. Forks of this session are NOT
        cascaded (they retain `forked_from = <id>` as a dangling
        reference; lineage walks gracefully degrade)."""
        ...


# ------------------------------------------------------------------ #
# LocalSessionStore                                                    #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class LocalStorePaths:
    """Filesystem layout under the store root.

        <root>/
          index.jsonl          # one Session record per line, append-only
          sessions/
            <id>.jsonl         # one Event-as-JSON per line
    """

    root: Path

    @classmethod
    def under(cls, paths: TrackPaths, *, name: str = "local-store") -> "LocalStorePaths":
        return cls(root=paths.track_dir / name)

    @property
    def index(self) -> Path:
        return self.root / "index.jsonl"

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    def session_file(self, id: str) -> Path:
        return self.sessions_dir / f"{id}.jsonl"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)


class LocalSessionStore:
    """Filesystem-backed session store. The dev stub for the future
    remote one."""

    def __init__(self, paths: TrackPaths, *, name: str = "local-store") -> None:
        self._layout = LocalStorePaths.under(paths, name=name)
        self._layout.ensure()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def list(
        self,
        *,
        tool: Optional[str] = None,
        cwd: Optional[str] = None,
        since: Optional[str] = None,
        query: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Session]:
        # Backed by `page()` so sort+filter semantics stay identical to
        # the cursor-paginated path. `limit=None` means "first page using
        # the default limit"; callers wanting more should use `page()`.
        page_limit = limit if limit is not None else DEFAULT_PAGE_LIMIT
        items, _ = self.page(
            tool=tool, cwd=cwd, since=since, query=query, limit=page_limit,
        )
        return items

    def page(
        self,
        *,
        tool: Optional[str] = None,
        cwd: Optional[str] = None,
        since: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: Optional[str] = None,
    ) -> tuple[list[Session], Optional[str]]:
        limit = _clamp_limit(limit)
        cur = _decode_cursor(cursor)

        # Materialize-then-sort. The local stub holds at most a few
        # thousand rows in `index.jsonl`; an O(n log n) sort per call is
        # cheap and lets us mirror the server's predicate exactly.
        rows: list[Session] = []
        for s in self._read_index():
            if tool is not None and s.tool != tool:
                continue
            if cwd is not None and s.cwd != cwd:
                continue
            if since is not None and (s.last_active or "") < since:
                continue
            if not _matches_query(s, query):
                continue
            rows.append(s)
        rows.sort(key=_sort_key, reverse=True)
        rows = [s for s in rows if _passes_cursor(s, cur)]

        # Fetch limit+1 to detect "more pages exist", same trick as server.
        page = rows[: limit + 1]
        has_more = len(page) > limit
        page = page[:limit]
        next_cursor = (
            _encode_cursor(page[-1].last_active, page[-1].id)
            if has_more and page
            else None
        )
        return page, next_cursor

    def get(self, id: str) -> Optional[Session]:
        # Exact match first.
        for s in self._read_index():
            if s.id == id:
                return s
        # Prefix match.
        matches = [s for s in self._read_index() if s.id.startswith(id)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise KeyError(
                f"Ambiguous prefix {id!r}: matches {[m.id for m in matches]}"
            )
        return None

    def events(self, id: str) -> Iterator[Event]:
        s = self.get(id)
        if s is None:
            raise KeyError(id)

        # Walk parents first (full chain root → leaf), each contributing
        # events up to its fork_point.
        chain = self._build_chain(s)
        for node, max_events in chain:
            yielded = 0
            for ev in self._read_events(node.id):
                if max_events is not None and yielded >= max_events:
                    break
                yield ev
                yielded += 1

    def own_events(self, id: str) -> Iterator[Event]:
        """Yield only this session's own events — no fork-chain walk.

        Used by ChainedSessionStore, which performs the cross-store chain
        walk itself and would otherwise double-emit parent events when both
        parent and child live in the same LocalSessionStore.
        """
        if self.get(id) is None:
            raise KeyError(id)
        yield from self._read_events(id)

    def create(self, session: Session, events: Iterable[Event]) -> Session:
        if not session.id:
            raise ValueError("Session.id must be set by the caller")

        # Materialize events to count; we need event_count anyway.
        events_list = list(events)
        normalized = Session(
            id=session.id,
            tool=session.tool,
            cwd=session.cwd,
            started_at=session.started_at,
            last_active=session.last_active,
            event_count=len(events_list),
            forked_from=session.forked_from,
            fork_point=session.fork_point,
            metadata=dict(session.metadata),
        )

        # Write events file atomically.
        target = self._layout.session_file(session.id)
        self._atomic_write_jsonl(
            target,
            (ev.model_dump(mode="json") for ev in events_list),
        )

        # Append to index.
        self._append_index(normalized)
        return normalized

    def append(self, id: str, events: Iterable[Event]) -> int:
        if self.get(id) is None:
            raise KeyError(id)
        target = self._layout.session_file(id)
        n = 0
        with open(target, "a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev.model_dump(mode="json"), ensure_ascii=False))
                f.write("\n")
                n += 1
        # We don't update event_count in the index on every append; that
        # would require a rewrite. `flt track ls` shows the count from
        # the index; consumers that need exact counts call `events()`.
        return n

    def delete(self, id: str) -> bool:
        s = self.get(id)
        if s is None:
            return False
        # Remove events file.
        target = self._layout.session_file(id)
        target.unlink(missing_ok=True)
        # Rewrite index without this entry.
        kept = [r for r in self._read_index() if r.id != id]
        self._write_index(kept)
        return True

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _read_index(self) -> Iterator[Session]:
        if not self._layout.index.exists():
            return iter(())
        # Last writer wins: scan top-to-bottom and keep the most recent
        # entry per id.
        latest: dict[str, Session] = {}
        with open(self._layout.index, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Tolerate extra fields a future schema adds.
                known = {f.name for f in Session.__dataclass_fields__.values()}
                cleaned = {k: v for k, v in d.items() if k in known}
                if "id" not in cleaned:
                    continue
                latest[cleaned["id"]] = Session(**cleaned)
        return iter(latest.values())

    def _append_index(self, session: Session) -> None:
        self._layout.ensure()
        with open(self._layout.index, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(session), ensure_ascii=False))
            f.write("\n")

    def _write_index(self, sessions: list[Session]) -> None:
        self._atomic_write_jsonl(
            self._layout.index,
            (asdict(s) for s in sessions),
        )

    def _atomic_write_jsonl(self, path: Path, rows: Iterable[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False))
                    f.write("\n")
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _read_events(self, id: str) -> Iterator[Event]:
        """Read events from disk, parsed back through the unified union.

        We use pydantic's discriminated-union validation rather than
        manually dispatching on `type` — this keeps the parser logic
        in one place (the union itself).
        """
        from pydantic import TypeAdapter

        target = self._layout.session_file(id)
        if not target.exists():
            return
        adapter: TypeAdapter[Event] = TypeAdapter(Event)
        with open(target, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    yield adapter.validate_python(d)
                except Exception as e:
                    log.debug("local store: skip invalid event in %s: %s", id, e)
                    continue

    def _build_chain_from_external(self, leaf: Session, lookup) -> list[tuple[Session, Optional[int]]]:
        """Variant of `_build_chain` that resolves parents via a caller-provided
        `lookup(session_id) → Session | None` instead of `self.get`. Used by
        ChainedSessionStore so cross-store fork chains resolve correctly."""
        chain: list[Session] = []
        seen: set[str] = set()
        cur: Optional[Session] = leaf
        while cur is not None:
            if cur.id in seen:
                log.warning("session lineage cycle at %s; truncating", cur.id)
                break
            seen.add(cur.id)
            chain.append(cur)
            if cur.forked_from is None:
                break
            cur = lookup(cur.forked_from)

        chain.reverse()
        out: list[tuple[Session, Optional[int]]] = []
        for i, node in enumerate(chain):
            if i + 1 < len(chain):
                child = chain[i + 1]
                out.append((node, child.fork_point))
            else:
                out.append((node, None))
        return out

    def _build_chain(self, leaf: Session) -> list[tuple[Session, Optional[int]]]:
        """Return the chain root → ... → leaf as (session, max_events_or_none).

        For each ancestor, max_events = its child's fork_point (so we
        only replay up to the branch point). For the leaf itself,
        max_events = None (replay all).
        """
        return self._build_chain_from_external(leaf, self.get)


# ------------------------------------------------------------------ #
# NativeFilesSessionStore                                              #
# ------------------------------------------------------------------ #


class NativeFilesSessionStore:
    """Read-only `SessionStore` view of native CLI session files.

    Walks `~/.claude/projects/` and `~/.codex/sessions/` (via the same
    `Source` classes the daemon uses). Useful as a "show me what's
    actually on disk" backend for `flt track ls` / `flt track resume`
    before the remote backend exists or before LocalSessionStore has
    been seeded.

    Read-only: `create` / `append` / `delete` raise NotImplementedError.
    `events()` re-parses the native file on each call (no caching) — fine
    for interactive resume, not great for hot loops.

    Identifies sessions:
      - claude: filename `<sessionId>.jsonl` (UUID)
      - codex: filename `rollout-<ts>-<sessionId>.jsonl` (last UUID)
    """

    def __init__(self, home: Optional["Path"] = None) -> None:  # noqa: F821
        self._home = home or Path.home()

    def list(
        self,
        *,
        tool: Optional[str] = None,
        cwd: Optional[str] = None,
        since: Optional[str] = None,
        query: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Session]:
        # Same trick as LocalSessionStore.list: defer to page() so sort
        # and filter semantics are identical.
        page_limit = limit if limit is not None else DEFAULT_PAGE_LIMIT
        items, _ = self.page(
            tool=tool, cwd=cwd, since=since, query=query, limit=page_limit,
        )
        return items

    def page(
        self,
        *,
        tool: Optional[str] = None,
        cwd: Optional[str] = None,
        since: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: Optional[str] = None,
    ) -> tuple[list[Session], Optional[str]]:
        limit = _clamp_limit(limit)
        cur = _decode_cursor(cursor)

        rows: list[Session] = []
        for source, build_session in self._sources_with_session_builders():
            if tool is not None and source.name != tool:
                continue
            if not source.is_present():
                continue
            for path in source.iter_files():
                # Skip fleet checkouts; they're transient views, not
                # native sessions, and would clutter the picker.
                if _looks_like_fleet_checkout(path):
                    continue
                try:
                    s = build_session(path)
                except OSError:
                    continue
                if s is None:
                    continue
                if cwd is not None and s.cwd != cwd:
                    continue
                if since is not None and (s.last_active or "") < since:
                    continue
                if not _matches_query(s, query):
                    continue
                rows.append(s)

        rows.sort(key=_sort_key, reverse=True)
        rows = [s for s in rows if _passes_cursor(s, cur)]

        page = rows[: limit + 1]
        has_more = len(page) > limit
        page = page[:limit]
        next_cursor = (
            _encode_cursor(page[-1].last_active, page[-1].id)
            if has_more and page
            else None
        )
        return page, next_cursor

    def get(self, id: str) -> Optional[Session]:
        # Two-pass: exact match, then unique prefix.
        all_sessions = self.list()
        for s in all_sessions:
            if s.id == id:
                return s
        matches = [s for s in all_sessions if s.id.startswith(id)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise KeyError(
                f"Ambiguous prefix {id!r}: matches {[m.id for m in matches]}"
            )
        return None

    def events(self, id: str) -> Iterator[Event]:
        s = self.get(id)
        if s is None:
            raise KeyError(id)
        path = self._path_for(s)
        if path is None:
            return
        # Lazy-import to avoid circular imports at module load.
        from .sources import ClaudeSource, CodexSource

        if s.tool == "claude":
            yield from ClaudeSource(home=self._home).parse(path)
        elif s.tool == "codex":
            yield from CodexSource(home=self._home).parse(path)

    # Native session files don't carry forked_from links, so events()
    # here never walks a fork chain — own_events is the same stream.
    own_events = events

    def create(self, session: Session, events: Iterable[Event]) -> Session:
        raise NotImplementedError(
            "NativeFilesSessionStore is read-only. Use LocalSessionStore for writes."
        )

    def append(self, id: str, events: Iterable[Event]) -> int:
        raise NotImplementedError("NativeFilesSessionStore is read-only.")

    def delete(self, id: str) -> bool:
        raise NotImplementedError("NativeFilesSessionStore is read-only.")

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _sources_with_session_builders(self):
        """Each tuple is (source_instance, fn(path)→Session|None)."""
        from .sources import ClaudeSource, CodexSource
        return [
            (ClaudeSource(home=self._home), self._build_claude_session),
            (CodexSource(home=self._home), self._build_codex_session),
        ]

    def _build_claude_session(self, path) -> Optional[Session]:
        # Filename `<uuid>.jsonl` is the session id by claude convention.
        sid = path.stem
        if not _looks_like_uuid(sid):
            return None
        return _build_session_from_path(
            tool="claude", id=sid, path=path,
            cwd=_decode_claude_cwd(path),
        )

    def _build_codex_session(self, path) -> Optional[Session]:
        # Filename `rollout-<ts>-<uuid>.jsonl`; we want the trailing uuid.
        stem = path.stem
        # Split from the right: last uuid-shaped chunk wins.
        parts = stem.split("-")
        # uuids are 5 hyphen-separated chunks (8-4-4-4-12); take last 5.
        if len(parts) < 5:
            return None
        candidate = "-".join(parts[-5:])
        if not _looks_like_uuid(candidate):
            return None
        # codex stores cwd inside the file's session_meta payload; we
        # parse the first line only to keep listing fast.
        cwd = _read_codex_cwd(path)
        return _build_session_from_path(
            tool="codex", id=candidate, path=path, cwd=cwd,
        )

    def _path_for(self, session: Session) -> Optional["Path"]:  # noqa: F821
        from .sources import ClaudeSource, CodexSource
        if session.tool == "claude":
            for p in ClaudeSource(home=self._home).iter_files():
                if p.stem == session.id:
                    return p
        elif session.tool == "codex":
            for p in CodexSource(home=self._home).iter_files():
                if p.stem.endswith(session.id):
                    return p
        return None


# ------------------------------------------------------------------ #
# ChainedSessionStore                                                  #
# ------------------------------------------------------------------ #


class ChainedSessionStore:
    """Combine multiple SessionStores into one logical view.

    `list()` merges across stores, deduping by `id` (first store wins on
    duplicates). `get()` and `events()` try each store in order.

    Writes (`create`/`append`/`delete`) delegate to the FIRST writable
    store. Read-only stores in the chain are skipped for writes.

    Typical use:

        chained = ChainedSessionStore(
            LocalSessionStore(paths),       # explicitly ingested first
            NativeFilesSessionStore(home),  # native fallback
            # RemoteSessionStore(...),      # later
        )
    """

    def __init__(self, *stores) -> None:
        if not stores:
            raise ValueError("ChainedSessionStore needs at least one backing store")
        self._stores = list(stores)

    def list(self, **kwargs) -> list[Session]:
        seen: set[str] = set()
        out: list[Session] = []
        for store in self._stores:
            for s in store.list(**kwargs):
                if s.id in seen:
                    continue
                seen.add(s.id)
                out.append(s)
        out.sort(key=_sort_key, reverse=True)
        if "limit" in kwargs and kwargs["limit"] is not None:
            out = out[: kwargs["limit"]]
        return out

    def page(
        self,
        *,
        tool: Optional[str] = None,
        cwd: Optional[str] = None,
        since: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: Optional[str] = None,
    ) -> tuple[list[Session], Optional[str]]:
        # Cursor pagination across multiple stores requires a k-way
        # merge with a composite cursor (one per backing store), which
        # we don't need yet — the only paged consumer (`flt track ls
        # --cursor`) targets a single backend at a time. If you want
        # paged scripting, pick `--source native` / `stub` / `remote`
        # explicitly. The interactive picker uses `list()` (eager merge)
        # and never sees a cursor.
        raise NotImplementedError(
            "ChainedSessionStore.page() is intentionally unimplemented: "
            "use --source native|stub|remote to paginate against a single "
            "backend, or call .list() for the eager-merge view used by "
            "the picker."
        )

    def get(self, id: str) -> Optional[Session]:
        ambiguous: list[str] = []
        for store in self._stores:
            try:
                s = store.get(id)
            except KeyError as e:
                ambiguous.append(str(e))
                continue
            if s is not None:
                return s
        if ambiguous:
            raise KeyError("; ".join(ambiguous))
        return None

    def events(self, id: str) -> Iterator[Event]:
        # Find the leaf, then walk fork_from chain (parents may live in
        # different stores than the leaf).
        leaf = self.get(id)
        if leaf is None:
            raise KeyError(id)

        # Build the chain across stores using our own get() as the lookup.
        # Then for each node we ask its home store for that node's *own*
        # events only — never `events()`, which would re-walk the chain
        # internally and double-emit parents that live in the same store.
        chain = self._build_chain_across(leaf)
        for node, max_events in chain:
            home_store = self._store_for(node)
            if home_store is None:
                continue
            read_own = getattr(home_store, "own_events", home_store.events)
            yielded = 0
            for ev in read_own(node.id):
                if max_events is not None and yielded >= max_events:
                    break
                yield ev
                yielded += 1

    def create(self, session: Session, events) -> Session:
        for store in self._stores:
            try:
                return store.create(session, events)
            except NotImplementedError:
                continue
        raise NotImplementedError("No writable store in chain")

    def append(self, id: str, events) -> int:
        for store in self._stores:
            try:
                return store.append(id, events)
            except (NotImplementedError, KeyError):
                continue
        raise KeyError(id)

    def delete(self, id: str) -> bool:
        deleted_any = False
        for store in self._stores:
            try:
                if store.delete(id):
                    deleted_any = True
            except NotImplementedError:
                continue
        return deleted_any

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _store_for(self, session: Session):
        """Return the first store whose `get(session.id)` finds this session."""
        for store in self._stores:
            try:
                if store.get(session.id) is not None:
                    return store
            except KeyError:
                continue
        return None

    def _build_chain_across(self, leaf: Session) -> list[tuple[Session, Optional[int]]]:
        """Walk fork_from across all stores, the same way LocalSessionStore
        walks within itself."""
        # Borrow LocalSessionStore's helper if available, otherwise inline.
        chain: list[Session] = []
        seen: set[str] = set()
        cur: Optional[Session] = leaf
        while cur is not None:
            if cur.id in seen:
                log.warning("session lineage cycle at %s; truncating", cur.id)
                break
            seen.add(cur.id)
            chain.append(cur)
            if cur.forked_from is None:
                break
            cur = self.get(cur.forked_from)

        chain.reverse()
        out: list[tuple[Session, Optional[int]]] = []
        for i, node in enumerate(chain):
            if i + 1 < len(chain):
                out.append((node, chain[i + 1].fork_point))
            else:
                out.append((node, None))
        return out


# ------------------------------------------------------------------ #
# Native-files helpers                                                 #
# ------------------------------------------------------------------ #


_UUID_RE = None
def _looks_like_uuid(s: str) -> bool:
    global _UUID_RE
    if _UUID_RE is None:
        import re as _re
        _UUID_RE = _re.compile(r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$")
    return bool(_UUID_RE.match(s))


def _decode_claude_cwd(path) -> Optional[str]:
    """Reverse claude's cwd encoding: the parent dir name is `cwd` with
    every non-alnum/dash/underscore replaced by '-'. We can't perfectly
    recover originals (the encoding is lossy: `/foo` and `-foo` both
    encode to `-foo`), but `/<dirname>` is a safe approximation that's
    correct for the canonical macOS / linux paths."""
    try:
        encoded = path.parent.name
    except AttributeError:
        return None
    if not encoded.startswith("-"):
        return None
    # Replace `-` with `/`. Lossy when the original had literal dashes
    # but matches the common case; resume code resolves through cwd
    # anyway so this is a display-only field.
    return "/" + encoded[1:].replace("-", "/")


def _read_codex_cwd(path) -> Optional[str]:
    """Read just the first line of a codex rollout to extract `payload.cwd`.
    Avoids parsing the whole file on every list."""
    try:
        with open(path, encoding="utf-8") as f:
            first = f.readline()
    except OSError:
        return None
    if not first:
        return None
    try:
        d = json.loads(first)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    payload = d.get("payload")
    if not isinstance(payload, dict):
        return None
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) else None


def _build_session_from_path(*, tool: str, id: str, path, cwd: Optional[str]) -> Session:
    """Cheap Session record from a path's stat. event_count is approximated
    by line count (avoids parsing); fine for picker display."""
    import datetime as _dt
    stat = path.stat()
    last_active = _dt.datetime.fromtimestamp(stat.st_mtime, tz=_dt.timezone.utc).isoformat()
    started_at = _dt.datetime.fromtimestamp(stat.st_ctime, tz=_dt.timezone.utc).isoformat()
    # Line count is a fast approximation of event_count.
    line_count = 0
    try:
        with open(path, "rb") as f:
            for _ in f:
                line_count += 1
    except OSError:
        pass
    return Session(
        id=id, tool=tool, cwd=cwd,
        started_at=started_at, last_active=last_active,
        event_count=line_count,
    )


def _looks_like_fleet_checkout(path) -> bool:
    """A native-files lister should skip our own checkout files (they're
    transient views, not real sessions)."""
    try:
        with open(path, encoding="utf-8") as f:
            first = f.readline()
    except OSError:
        return False
    if not first:
        return False
    try:
        d = json.loads(first)
    except json.JSONDecodeError:
        return False
    if not isinstance(d, dict):
        return False
    if "_fleet_meta" in d:
        return True
    payload = d.get("payload")
    if isinstance(payload, dict) and "_fleet_meta" in payload:
        return True
    return False
