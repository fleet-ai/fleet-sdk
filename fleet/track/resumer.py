"""Resume orchestration: SessionStore → checkout file → native CLI.

The flow:

  1. Materialize the session's full event chain (walks `forked_from`).
  2. If the target tool matches the source, just dispatch native
     resume directly against the source's own native session — no
     conversion, no checkout. Cleanest path; no pollution.
  3. Otherwise: synthesize a fresh ephemeral session id, convert
     events to the target's native format, write to
     `~/.<target>/.../.fleet-checkouts/<ephemeral-id>.jsonl`, and
     `exec` the target's native resume command.

Checkouts are tagged with their `forked_from` lineage as a header
row; the track daemon uses this on upload to record the branch
relation server-side. Track daemon GCs the `.fleet-checkouts/`
namespace at 24h.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .compactor import Compactor, TruncationCompactor, budget_for
from .converter import _encode_claude_cwd
from .paths import TrackPaths
from .sources import ClaudeSource, CodexSource
from .store import Session, SessionStore
from .unified import Event, SessionStart

log = logging.getLogger("fleet.track.resumer")


# Tool registry — what the SDK currently knows how to resume into.
SUPPORTED_TOOLS: frozenset[str] = frozenset({"claude", "codex"})


# Compaction lives in `fleet.track.compactor` (see TruncationCompactor +
# CompactionConfig). Resumer composes a Compactor — never reaches into
# its internals.


@dataclass(frozen=True)
class CheckoutInfo:
    ephemeral_id: str
    path: Path
    target_tool: str
    forked_from: str
    fork_point: int


def resume_session(
    *,
    store: SessionStore,
    session: Session,
    target_tool: str,
    prompt: Optional[str] = None,
    paths: Optional[TrackPaths] = None,
    compactor: Optional[Compactor] = None,
    target_model: Optional[str] = None,
) -> int:
    """Resume `session` in `target_tool`. Returns the target CLI's exit code.

    If the target_tool matches the session's tool, dispatches the
    native resume command against the original session (no conversion,
    no checkout, no compaction — would be destructive of user history).

    Cross-tool: creates a checkout via the supplied `compactor` (default:
    a `TruncationCompactor` sized to the target tool/model's typical
    context window). Dispatches on the new ephemeral id.

    Future strategies (LLM summarization, recall-tool injection) plug
    in by passing a different `compactor`. The interface is the seam.

    Raises NotImplementedError if `target_tool` isn't supported yet
    (cursor / opencode).
    """
    if target_tool not in SUPPORTED_TOOLS:
        raise NotImplementedError(
            f"Resume into '{target_tool}' isn't implemented yet. "
            f"Supported: {sorted(SUPPORTED_TOOLS)}"
        )

    paths = paths or TrackPaths.default()

    if session.tool == target_tool:
        return _exec_native_resume(target_tool, session.id, prompt=prompt)

    # Cross-tool: pick a default compactor sized to the target. Pass an
    # `emission_estimator` so the compactor can verify post-serialization
    # size against the budget — per-event estimation is imprecise because
    # the cross-source synthesizer's wrapper overhead varies by target.
    if compactor is None:
        from .compactor import estimate_tokens
        target_source = _source_for(target_tool, home=paths.home)

        def _emission_tokens(evs: list[Event]) -> int:
            try:
                return estimate_tokens(target_source.serialize(evs).decode("utf-8", errors="replace"))
            except Exception:
                # If serialization fails for any reason, treat it as
                # over-budget so the compactor keeps trimming.
                return 10_000_000

        compactor = TruncationCompactor(
            budget=budget_for(target_tool, target_model),
            emission_estimator=_emission_tokens,
        )

    checkout = _create_checkout(
        store=store, session=session, target_tool=target_tool,
        paths=paths, compactor=compactor,
    )
    return _exec_native_resume(target_tool, checkout.ephemeral_id, prompt=prompt)


# ------------------------------------------------------------------ #
# Checkout creation                                                    #
# ------------------------------------------------------------------ #


def _create_checkout(
    *,
    store: SessionStore,
    session: Session,
    target_tool: str,
    paths: TrackPaths,
    compactor: Optional[Compactor] = None,
) -> CheckoutInfo:
    """Convert `session`'s events into target-tool format and write to
    `~/.<target>/.../<ephemeral-id>.jsonl` (flat, marked by `_fleet_meta`).

    `compactor` (when supplied) projects the event stream into a
    context-fitting view before serialization. None means "ship the
    full history" — useful when the source is small enough to fit.
    """
    ephemeral_id = str(uuid.uuid4())

    # Resolve cwd for the target. The session's recorded cwd is the
    # original — resolve symlinks (mac /tmp → /private/tmp) so the
    # target CLI's resume scan finds it.
    target_cwd = _resolve_cwd(session.cwd or "/tmp")

    # Walk parents, gather events; the converter then emits target-format
    # bytes. We embed `_synth` metadata so cross-source synthesizers
    # produce coherent rows (matching session id, cwd, etc.).
    events = list(store.events(session.id))
    fork_point = len(events)

    # Apply compaction BEFORE prepending SessionStart and annotating —
    # compaction operates on the source semantic events, not on the
    # serializer's helper rows.
    if compactor is not None:
        before = len(events)
        events = list(compactor.compact(events))
        log.info(
            "checkout compaction: %d → %d events (%.1f%% reduction)",
            before, len(events),
            100.0 * (1 - len(events) / max(1, before)),
        )

    # Both target tools need a "start of session" marker on output.
    #   - codex requires `session_meta` as the first row, period.
    #   - claude is forgiving but the SessionStart helps consumers.
    # If the input event stream doesn't already start with a
    # SessionStart, prepend one so the serializer emits the marker
    # row in cross-source mode.
    if not events or events[0].type != "session_start":
        synthetic_start = SessionStart(
            source=session.tool,
            id=session.id,
            cwd=target_cwd,
            agent_version=session.metadata.get("version", "0.0.0-fleet-checkout"),
            user_instructions=session.metadata.get("user_instructions"),
        )
        events = [synthetic_start] + events
        # fork_point still measures the source session's event count
        # (excluding our synthetic start), so the daemon can faithfully
        # reproduce the lineage.

    # Use the existing per-source serializer with synth metadata pre-baked.
    annotated = [_with_synth_meta(
        ev,
        session_id=ephemeral_id,
        cwd=target_cwd,
        version=session.metadata.get("version", "0.0.0-fleet-checkout"),
        git_branch=session.metadata.get("git_branch", ""),
    ) for ev in events]

    target_source = _source_for(target_tool, home=paths.home)
    target_bytes = target_source.serialize(annotated)

    # Where does it go?
    out_path = _checkout_path(target_tool, target_cwd, ephemeral_id, paths.home)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Header row first (fleet-managed metadata, ignored by the target CLI
    # because it's not a recognized row type).
    header = {
        "_fleet": "checkout-meta",
        "schema_version": 1,
        "ephemeral_id": ephemeral_id,
        "forked_from": session.id,
        "fork_point": fork_point,
        "source_tool": session.tool,
        "target_tool": target_tool,
    }
    body = b""
    if target_tool == "claude":
        # Claude's reader is permissive about extra row types; emit
        # the header as a comment-style `system` row so it's ignored.
        body = (json.dumps({"_fleet_meta": header,
                             "type": "system",
                             "content": "fleet-track checkout"}, separators=(",", ":"))
                + "\n").encode("utf-8")
    elif target_tool == "codex":
        # codex's session_meta MUST be the first row; we can't put a
        # custom header above it without breaking resume. Embed the
        # checkout meta inside the session_meta payload as a sub-key.
        # The converter already emits session_meta first; we'll
        # post-process to inject the meta there.
        target_bytes = _inject_codex_checkout_meta(target_bytes, header)

    out_path.write_bytes(body + target_bytes)

    log.info(
        "checkout created tool=%s ephemeral_id=%s forked_from=%s fork_point=%d path=%s",
        target_tool, ephemeral_id, session.id, fork_point, out_path,
    )

    return CheckoutInfo(
        ephemeral_id=ephemeral_id,
        path=out_path,
        target_tool=target_tool,
        forked_from=session.id,
        fork_point=fork_point,
    )


def _checkout_path(target_tool: str, cwd: str, ephemeral_id: str, home: Path) -> Path:
    """Where the checkout file lives in the target tool's namespace.

    Layout decision: checkouts live FLAT alongside native sessions, NOT
    in a `.fleet-checkouts/` subdir. claude's resume scanner only looks
    one level deep under `<encoded-cwd>/`, so a subdir would render the
    file invisible. Same flat layout for codex for consistency. The
    daemon distinguishes checkouts from native sessions by reading the
    first row's `_fleet_meta` marker — fast and reliable.
    """
    if target_tool == "claude":
        encoded = _encode_claude_cwd(cwd)
        return home / ".claude" / "projects" / encoded / f"{ephemeral_id}.jsonl"
    if target_tool == "codex":
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H-%M-%S")
        date = now.strftime("%Y/%m/%d")
        return (home / ".codex" / "sessions" / date
                / f"rollout-{ts}-{ephemeral_id}.jsonl")
    raise ValueError(f"Unknown target tool: {target_tool}")


def _source_for(tool: str, *, home: Path):
    if tool == "claude":
        return ClaudeSource(home=home)
    if tool == "codex":
        return CodexSource(home=home)
    raise ValueError(f"Unknown tool: {tool}")


def _with_synth_meta(ev, **synth):
    """Embed `_synth` metadata into an event's `raw` so the cross-source
    serializer can produce coherent rows. (Same logic as
    converter._with_synth_meta but local so we don't import a private name.)"""
    raw = dict(ev.raw) if ev.raw else {}
    raw["_synth"] = dict(synth)
    return ev.model_copy(update={"raw": raw})


def _resolve_cwd(cwd: str) -> str:
    """Resolve symlinks. macOS `/tmp` → `/private/tmp` etc."""
    try:
        return str(Path(cwd).resolve(strict=False))
    except (OSError, RuntimeError):
        return cwd


def _inject_codex_checkout_meta(body: bytes, meta: dict) -> bytes:
    """Add a `_fleet_meta` field inside the first session_meta row's
    payload so the daemon can read fork lineage on upload."""
    text = body.decode("utf-8")
    lines = text.splitlines(keepends=False)
    if not lines:
        return body
    try:
        first = json.loads(lines[0])
    except json.JSONDecodeError:
        return body
    if first.get("type") == "session_meta":
        payload = first.get("payload") or {}
        payload["_fleet_meta"] = meta
        first["payload"] = payload
        lines[0] = json.dumps(first, ensure_ascii=False, separators=(",", ":"))
    return ("\n".join(lines) + "\n").encode("utf-8")


# ------------------------------------------------------------------ #
# Native CLI dispatch                                                  #
# ------------------------------------------------------------------ #


def _exec_native_resume(tool: str, session_id: str, *, prompt: Optional[str]) -> int:
    """Run the tool's native resume command. Returns the exit code.

    Inherits stdio so the user can interact (TUI). For non-interactive
    use (testing), pass `--print` for claude or use `codex exec resume`
    — but those are choices for the caller of `resume_session` to
    pre-bake into the prompt argument."""
    if tool == "claude":
        cmd = ["claude", "--resume", session_id]
        if prompt:
            cmd.extend(["--print", prompt])
        return subprocess.call(cmd)
    if tool == "codex":
        cmd = ["codex"]
        if prompt:
            cmd.extend(["exec", "--skip-git-repo-check", "resume", session_id, prompt])
        else:
            cmd.extend(["resume", session_id])
        return subprocess.call(cmd)
    raise ValueError(f"Unknown tool: {tool}")


# ------------------------------------------------------------------ #
# Cleanup (called by track daemon's hourly maintenance loop)           #
# ------------------------------------------------------------------ #


def gc_checkouts(*, home: Optional[Path] = None, max_age_hours: int = 24) -> int:
    """Delete fleet-managed checkout files older than `max_age_hours`.

    A file is identified as a checkout by inspecting its first line for
    the `_fleet_meta` marker (or `payload._fleet_meta` for codex's
    session_meta layout). Native sessions never carry that key, so this
    is non-destructive on user data.

    Returns the number of files removed. Idempotent. Safe to run
    concurrently with active resumes — only files older than the
    threshold get touched, and a session in active use has a fresh
    mtime.
    """
    home = home or Path.home()
    cutoff = _seconds_now() - max_age_hours * 3600
    removed = 0
    for tool_root in (home / ".claude" / "projects", home / ".codex" / "sessions"):
        if not tool_root.is_dir():
            continue
        for f in tool_root.glob("**/*.jsonl"):
            try:
                st = f.stat()
                if st.st_mtime >= cutoff:
                    continue  # too fresh
                if not _is_fleet_checkout(f):
                    continue  # native session, leave alone
                f.unlink()
                removed += 1
            except OSError as e:
                log.warning("checkout gc: failed to inspect/remove %s: %s", f, e)
    return removed


def _is_fleet_checkout(path: Path) -> bool:
    """True if the file's first row carries fleet's checkout marker."""
    try:
        with open(path, encoding="utf-8") as f:
            line = f.readline()
        if not line:
            return False
        d = json.loads(line)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(d, dict):
        return False
    if "_fleet_meta" in d:
        return True
    payload = d.get("payload")
    if isinstance(payload, dict) and "_fleet_meta" in payload:
        return True
    return False


def _seconds_now() -> float:
    import time
    return time.time()
