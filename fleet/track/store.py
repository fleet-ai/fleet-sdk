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

from pydantic import BaseModel, ConfigDict, Field

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

# Internal cap for ChainedSessionStore.page(): the maximum number of
# rows pulled from each backing store per call. Only matters when the
# total filtered row count across all stores exceeds this — for which
# later cursor pages would miss data that fell off the per-store cap.
# Tuned to comfortably exceed any single user's session count today.
_CHAINED_BUFFER_CAP: int = 2000


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


def _read_local_device_id() -> Optional[str]:
    """Pull the device_id stamped on this machine by `flt track enable`.

    Used to populate `Session.origin_device` for sessions produced
    locally. None when the user hasn't enabled tracking yet (the LocalSessionStore
    still works as a dev stub; it just won't carry origin info)."""
    try:
        cfg_path = TrackPaths.default().config_file
        if not cfg_path.exists():
            return None
        cfg = json.loads(cfg_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    did = cfg.get("device_id")
    return did if isinstance(did, str) and did else None


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


class SessionMetadata(BaseModel):
    """Canonical schema for `Session.metadata`.

    Both the SDK and the orchestrator should read/write metadata
    conforming to this model. The dict on `Session.metadata` itself
    stays a plain dict for ergonomics (existing callers do
    `s.metadata.get("title")`); `Session.metadata_typed()` parses it
    through this model when typed access is needed.

    `extra="allow"` so the model is forward-compatible — a server-side
    field we haven't pinned yet still survives round-trip.
    """

    model_config = ConfigDict(extra="allow")

    # Display
    title: Optional[str] = None

    # Repo identity (cross-machine resume key)
    # `repo_url` is the canonical key — normalized via `normalize_repo_url`
    # in `fleet.track.repos`. `repo_subpath` is the path relative to the
    # repo root. `origin_cwd` is the absolute path on the originating
    # machine, kept as a fallback for sessions outside any git repo.
    repo_url: Optional[str] = None
    repo_subpath: Optional[str] = None
    origin_cwd: Optional[str] = None

    # Source-recorded context (populated where the source format exposes it)
    model: Optional[str] = None
    agent_version: Optional[str] = None
    git_branch: Optional[str] = None

    # User-tagged labels (free-form). Reserved for future server-driven
    # workflows; ingest writes none.
    tags: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Session:
    """One session in the store.

    `id` — globally unique within the store. UUIDs are recommended; the
        store doesn't enforce a format so callers can use claude/codex's
        native ids when seeding from local files.

    `tool` — which CLI emitted *this* session's events.
        Same as the unified Event.source, lifted to the session level
        for fast filtering without parsing events.

    `cwd` — the working directory the agent was run in (originating
        machine's absolute path). Use `metadata.repo_url` +
        `metadata.repo_subpath` for cross-machine resume; cwd is only
        meaningful on the device that produced the session.

    `started_at` / `last_active` — ISO-8601 timestamps. `last_active` is
        a max over the session's events; the daemon updates it on
        every sync.

    `event_count` — cached count for quick listing without reading
        the full file.

    `forked_from` / `fork_point` — branch lineage. Set on derived
        sessions (e.g. claude resume of a codex session). The original
        sessions have both as None.

    `origin_device` — id of the machine that produced this session
        (`device_id` from `~/.fleet/track/config.json`). Top-level (not
        metadata) because it's identity, not annotation. None when
        unknown (e.g. NativeFilesSessionStore on a host that never ran
        `flt track enable`).

    `metadata` — open-ended bag conforming to `SessionMetadata`.
        Validated lazily via `metadata_typed()`; stored as dict so
        callers can read/write known keys directly.
    """

    id: str
    tool: str  # "claude" | "codex" | "cursor" | "opencode" | "unknown"
    cwd: Optional[str] = None
    started_at: Optional[str] = None
    last_active: Optional[str] = None
    event_count: int = 0
    forked_from: Optional[str] = None
    fork_point: Optional[int] = None
    origin_device: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def metadata_typed(self) -> SessionMetadata:
        """Parse `metadata` through `SessionMetadata` for typed access."""
        return SessionMetadata.model_validate(self.metadata)


# ------------------------------------------------------------------ #
# Protocol                                                             #
# ------------------------------------------------------------------ #


class SessionStore(Protocol):
    """The contract. Both LocalSessionStore and (future) RemoteSessionStore
    implement this."""

    # Optional opt-in flag for ChainedSessionStore. When True, the chain
    # delegates paging entirely to this store (it owns global ordering)
    # and overlays other stores' rows only inside the returned page's
    # (last_active, id) window. Local stores leave this False/absent so
    # the legacy eager-merge path is used. RemoteSessionStore sets it
    # True so paging scales beyond `_CHAINED_BUFFER_CAP`.
    prefers_authoritative_paging: bool = False

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
    def under(
        cls, paths: TrackPaths, *, name: str = "local-store"
    ) -> "LocalStorePaths":
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
            tool=tool,
            cwd=cwd,
            since=since,
            query=query,
            limit=page_limit,
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
        # Stamp `origin_device` from the local config when the caller
        # didn't set one. The local store is by definition the device
        # producing the session, so pinning it here gives every record
        # in the dev stub a stable origin id without callers having to
        # know about it.
        origin_device = session.origin_device or _read_local_device_id()
        normalized = Session(
            id=session.id,
            tool=session.tool,
            cwd=session.cwd,
            started_at=session.started_at,
            last_active=session.last_active,
            event_count=len(events_list),
            forked_from=session.forked_from,
            fork_point=session.fork_point,
            origin_device=origin_device,
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
        fd, tmp = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}-", suffix=".tmp"
        )
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

    def _build_chain_from_external(
        self, leaf: Session, lookup
    ) -> list[tuple[Session, Optional[int]]]:
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
# RemoteSessionStore                                                   #
# ------------------------------------------------------------------ #


class RemoteSessionStore:
    """Read-only SessionStore backed by orchestrator's metadata index.

    The daemon writes bytes through the v1 S3-direct sync path and then
    registers metadata through `/v1/track/sessions/{id}`. This store reads that
    metadata and fetches native bytes through orchestrator-issued presigned S3
    URLs when a caller needs events for resume.
    """

    prefers_authoritative_paging: bool = True

    def __init__(self, api=None) -> None:
        if api is None:
            from .api import TrackAPIClient

            api = TrackAPIClient()
        self._api = api

    def list(
        self,
        *,
        tool: Optional[str] = None,
        cwd: Optional[str] = None,
        since: Optional[str] = None,
        query: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Session]:
        page_limit = limit if limit is not None else DEFAULT_PAGE_LIMIT
        items, _ = self.page(
            tool=tool,
            cwd=cwd,
            since=since,
            query=query,
            limit=page_limit,
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
        data = self._api.list_sessions(
            tool=tool,
            cwd=cwd,
            since=since,
            query=query,
            limit=_clamp_limit(limit),
            cursor=cursor,
        )
        items = [_session_from_api(row) for row in data.get("items", [])]
        return items, data.get("next_cursor")

    def get(self, id: str) -> Optional[Session]:
        try:
            return _session_from_api(self._api.get_session(id))
        except Exception as e:
            if getattr(e, "status_code", None) == 404:
                return None
            raise

    def events(self, id: str) -> Iterator[Event]:
        leaf = self.get(id)
        if leaf is None:
            raise KeyError(id)

        chain = _build_chain(leaf, self.get)
        for node, max_events in chain:
            yielded = 0
            for ev in self.own_events(node.id):
                if max_events is not None and yielded >= max_events:
                    break
                yield ev
                yielded += 1

    def own_events(self, id: str) -> Iterator[Event]:
        session = self.get(id)
        if session is None:
            raise KeyError(id)

        raw = self._api.download_session_content(session.id)
        suffix = ".jsonl" if session.tool in {"claude", "codex"} else ""
        with tempfile.NamedTemporaryFile(suffix=suffix) as f:
            f.write(raw)
            f.flush()
            path = Path(f.name)
            if session.tool == "claude":
                from .sources import ClaudeSource

                yield from ClaudeSource().parse(path)
            elif session.tool == "codex":
                from .sources import CodexSource

                yield from CodexSource().parse(path)
            else:
                raise NotImplementedError(
                    f"Remote event replay for {session.tool!r} sessions is not supported yet"
                )

    def create(self, session: Session, events: Iterable[Event]) -> Session:
        raise NotImplementedError(
            "RemoteSessionStore is read-only; the daemon writes remote metadata"
        )

    def append(self, id: str, events: Iterable[Event]) -> int:
        raise NotImplementedError("RemoteSessionStore is read-only")

    def delete(self, id: str) -> bool:
        raise NotImplementedError("RemoteSessionStore is read-only")


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
            tool=tool,
            cwd=cwd,
            since=since,
            query=query,
            limit=page_limit,
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

        rows = list(self._iter_sessions(tool=tool, cwd=cwd, since=since, query=query))

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
        # Exact match first, then unique prefix. This must scan all native
        # sessions, not just the first list() page, because callers like
        # build-local-index replay events for every paginated row.
        matches: list[Session] = []
        for s in self._iter_sessions():
            if s.id == id:
                return s
            if s.id.startswith(id):
                matches.append(s)
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

    def _iter_sessions(
        self,
        *,
        tool: Optional[str] = None,
        cwd: Optional[str] = None,
        since: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Iterator[Session]:
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
                yield s

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
            tool="claude",
            id=sid,
            path=path,
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
            tool="codex",
            id=candidate,
            path=path,
            cwd=cwd,
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
        """Page across the chained backends.

        Two strategies:

        1. **Authoritative-paging delegation** — when one of the backing
           stores opts in via `prefers_authoritative_paging` (today: the
           future RemoteSessionStore), we delegate paging entirely to
           that store and merge other backends' rows ONLY into the
           returned page. The authoritative store owns global ordering;
           other stores contribute local-only rows that the authority
           doesn't know about (e.g. a local fork that hasn't synced yet).

           Cursors in this mode are the authority's cursors verbatim —
           pass-through, no rewrap. The local rows we overlay are
           filtered to those that fit *within* the authority page's
           (last_active, id) window, so we don't accidentally shadow
           rows from later authority pages.

        2. **Eager-merge** — when all backends are local, pull up to
           `_CHAINED_BUFFER_CAP` rows from each, dedupe by id, sort,
           cursor-walk, slice. Cheap and correct as long as the total
           fits in the buffer (typical: <2000 rows across local +
           native combined).
        """
        # Strategy 1: delegate to authoritative-paging store if any.
        for i, store in enumerate(self._stores):
            if getattr(store, "prefers_authoritative_paging", False):
                return self._authoritative_page(
                    auth_idx=i,
                    tool=tool,
                    cwd=cwd,
                    since=since,
                    query=query,
                    limit=limit,
                    cursor=cursor,
                )

        # Strategy 2: legacy eager-merge.
        cur = _decode_cursor(cursor)
        seen: set[str] = set()
        rows: list[Session] = []
        for store in self._stores:
            try:
                store_rows = list(
                    store.list(
                        tool=tool,
                        cwd=cwd,
                        since=since,
                        query=query,
                        limit=_CHAINED_BUFFER_CAP,
                    )
                )
            except TypeError:
                # Backwards-compat: a backing store that hasn't grown the
                # `query` kwarg yet — fall back to filtering ourselves.
                store_rows = list(
                    store.list(
                        tool=tool,
                        cwd=cwd,
                        since=since,
                        limit=_CHAINED_BUFFER_CAP,
                    )
                )
                if query:
                    store_rows = [s for s in store_rows if _matches_query(s, query)]
            for s in store_rows:
                if s.id in seen:
                    continue
                seen.add(s.id)
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

    def _authoritative_page(
        self,
        *,
        auth_idx: int,
        tool: Optional[str],
        cwd: Optional[str],
        since: Optional[str],
        query: Optional[str],
        limit: int,
        cursor: Optional[str],
    ) -> tuple[list[Session], Optional[str]]:
        """Delegate paging to `self._stores[auth_idx]` and overlay
        rows from the other backends into the same window."""
        auth = self._stores[auth_idx]
        auth_page, next_cursor = auth.page(
            tool=tool,
            cwd=cwd,
            since=since,
            query=query,
            limit=limit,
            cursor=cursor,
        )
        if not auth_page:
            return auth_page, next_cursor

        # Ordering window of the authority's page: (top_la, top_id) is the
        # newest row, (bot_la, bot_id) is the oldest. We let local rows
        # in only if they sort within (or below) the bottom row — pages
        # to come from the authority will pick up anything above us.
        # We compare rows by `_sort_key` and keep those whose tuple is
        # ≤ the top tuple AND ≥ the bottom tuple. (Larger sort key =
        # newer row; reverse=True sort puts them first.)
        top_key = _sort_key(auth_page[0])
        bot_key = _sort_key(auth_page[-1])

        seen: set[str] = {s.id for s in auth_page}
        local_in_window: list[Session] = []
        for j, store in enumerate(self._stores):
            if j == auth_idx:
                continue
            try:
                rows = list(
                    store.list(
                        tool=tool,
                        cwd=cwd,
                        since=since,
                        query=query,
                        limit=_CHAINED_BUFFER_CAP,
                    )
                )
            except TypeError:
                rows = list(
                    store.list(
                        tool=tool,
                        cwd=cwd,
                        since=since,
                        limit=_CHAINED_BUFFER_CAP,
                    )
                )
                if query:
                    rows = [s for s in rows if _matches_query(s, query)]
            for s in rows:
                if s.id in seen:
                    continue
                k = _sort_key(s)
                if not (bot_key <= k <= top_key):
                    continue  # outside the page's window — skip
                seen.add(s.id)
                local_in_window.append(s)

        # Merge: keep authority page rows, splice in local-window rows
        # at their proper sorted position. Tie-break: the authority's
        # row wins because it's the source of truth for ids it knows.
        merged = sorted(
            list(auth_page) + local_in_window,
            key=_sort_key,
            reverse=True,
        )
        # Trim to the requested limit so we don't return more than asked.
        merged = merged[:limit]
        return merged, next_cursor

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


def _build_chain(
    leaf: Session,
    lookup,
) -> list[tuple[Session, Optional[int]]]:
    """Build a fork chain root → leaf using `lookup(session_id)`."""
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
            out.append((node, chain[i + 1].fork_point))
        else:
            out.append((node, None))
    return out


def _session_from_api(row: dict) -> Session:
    """Map orchestrator SessionMetadata JSON to the SDK dataclass."""
    known = {f.name for f in Session.__dataclass_fields__.values()}
    cleaned = {k: v for k, v in row.items() if k in known}
    if "origin_device" not in cleaned and row.get("device_id"):
        cleaned["origin_device"] = row["device_id"]
    return Session(**cleaned)


# ------------------------------------------------------------------ #
# Native-files helpers                                                 #
# ------------------------------------------------------------------ #


_UUID_RE = None


def _looks_like_uuid(s: str) -> bool:
    global _UUID_RE
    if _UUID_RE is None:
        import re as _re

        _UUID_RE = _re.compile(
            r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$"
        )
    return bool(_UUID_RE.match(s))


def session_from_native_path(path, *, home: Optional[Path] = None) -> Optional[Session]:
    """Return a cheap Session metadata record for a native session file.

    This is the daemon's bridge from the v1 file syncer to the orchestrator
    metadata index. It deliberately supports only source formats whose session
    id and parser semantics are implemented locally.
    """
    path = Path(path)
    home = home or Path.home()
    try:
        rel = path.relative_to(home)
    except ValueError:
        return None
    if _looks_like_fleet_checkout(path):
        return None

    parts = rel.parts
    native = NativeFilesSessionStore(home=home)
    if len(parts) >= 3 and parts[0] == ".claude" and parts[1] == "projects":
        if path.suffix != ".jsonl":
            return None
        return native._build_claude_session(path)
    if (
        len(parts) >= 3
        and parts[0] == ".codex"
        and parts[1]
        in {
            "sessions",
            "archived_sessions",
        }
    ):
        if path.suffix != ".jsonl":
            return None
        return native._build_codex_session(path)
    return None


def _decode_claude_cwd(path) -> Optional[str]:
    """Recover the session's original cwd.

    Strategy: read the actual `cwd` field from the session file. Claude
    writes it verbatim on user/assistant rows; that's the ground truth.
    The directory-name encoding (`/Users/me/git/foo-bar` →
    `-Users-me-git-foo-bar`) is irreversibly lossy because both `/` and
    `-` collapse to `-`, so we only fall back to it when the file has
    no row with a `cwd` field (empty / corrupt file).

    Reads up to `_CWD_SCAN_LIMIT` rows; the early metadata rows don't
    carry `cwd` but the first user message does, so a small bound is
    enough.
    """
    cwd = _read_claude_cwd(path)
    if cwd:
        return cwd
    # Fallback: lossy decode of the encoded parent dir. Useful only when
    # the session file is empty or unreadable.
    try:
        encoded = path.parent.name
    except AttributeError:
        return None
    if not encoded.startswith("-"):
        return None
    return "/" + encoded[1:].replace("-", "/")


_CWD_SCAN_LIMIT: int = 20


def _read_claude_cwd(path) -> Optional[str]:
    """Scan the first few rows of a claude session for the `cwd` field.
    Returns None if the file is missing, empty, or no row carries cwd
    within the scan window."""
    try:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= _CWD_SCAN_LIMIT:
                    break
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(d, dict):
                    continue
                cwd = d.get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        return None
    return None


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


def _build_session_from_path(
    *, tool: str, id: str, path, cwd: Optional[str]
) -> Session:
    """Cheap Session record from a path's stat. event_count is approximated
    by line count (avoids parsing); fine for picker display.

    Also stamps `metadata.repo_url` / `repo_subpath` / `origin_cwd` so the
    resumer can locate a local checkout regardless of the absolute cwd
    matching the current machine. `capture_repo()` is module-cached, so
    repeated builds for sessions in the same cwd shell out only once.
    """
    import datetime as _dt
    from .repos import capture_repo

    stat = path.stat()
    last_active = _dt.datetime.fromtimestamp(
        stat.st_mtime, tz=_dt.timezone.utc
    ).isoformat()
    started_at = _dt.datetime.fromtimestamp(
        stat.st_ctime, tz=_dt.timezone.utc
    ).isoformat()
    # Line count is a fast approximation of event_count.
    line_count = 0
    try:
        with open(path, "rb") as f:
            for _ in f:
                line_count += 1
    except OSError:
        pass

    metadata: dict = {}
    if cwd:
        info = capture_repo(cwd)
        metadata["origin_cwd"] = info.origin_cwd
        if info.url:
            metadata["repo_url"] = info.url
            metadata["repo_subpath"] = info.subpath

    # Native files were written by this machine, so origin_device is the
    # local device id when we have one stamped on disk.
    origin_device = _read_local_device_id()

    return Session(
        id=id,
        tool=tool,
        cwd=cwd,
        started_at=started_at,
        last_active=last_active,
        event_count=line_count,
        origin_device=origin_device,
        metadata=metadata,
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
