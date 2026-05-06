"""flt track — CLI subcommands."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .api import TrackAPIClient, TrackAPIError
from .blocklist import (
    TrackBlocklist,
    add_blocked_session_ids,
    read_track_config,
    remove_blocked_session_ids,
)
from .daemon import main as daemon_main
from .install import install, is_installed, uninstall
from .paths import TrackPaths
from .query_schema import search_filter_catalog
from .queue import UploadQueue
from .sources import detect_sources
from .status import is_running, read_status

import uuid

app = typer.Typer(help="Track local AI coding sessions", no_args_is_help=True)
console = Console()

DEFAULT_SESSION_SOURCE = "remote"
LOCAL_SESSION_SOURCE = "local"
DEFAULT_SEARCH_TOP_K = 50
SOURCE_HELP = (
    "Where to read sessions from: remote (default, orchestrator) "
    "or local (manually built Fleet local index)."
)


def _write_config(paths: TrackPaths, config: dict) -> None:
    paths.ensure_track_dir()
    paths.config_file.write_text(json.dumps(config, indent=2))


@app.command()
def enable() -> None:
    """Scan this machine for AI sessions and start syncing."""
    paths = TrackPaths.default()

    from ..auth import get_valid_token

    if not os.getenv("FLEET_API_KEY") and not get_valid_token():
        console.print(
            "[red]Not authenticated.[/red] Run [bold]flt login[/bold] or set [bold]FLEET_API_KEY[/bold] first."
        )
        raise typer.Exit(1)

    # Load or create machine ID
    paths.ensure_track_dir()
    if paths.config_file.exists():
        config = json.loads(paths.config_file.read_text())
    else:
        config = {}

    if "device_id" not in config:
        import re
        import socket

        hostname = re.sub(r"[^a-z0-9-]", "-", socket.gethostname().lower())[:20].strip(
            "-"
        )
        config["device_id"] = f"{hostname}-{str(uuid.uuid4()).replace('-', '')[:8]}"
        _write_config(paths, config)

    device_id = config["device_id"]

    # Provision with backend
    console.print("Provisioning with Fleet...")
    try:
        api = TrackAPIClient()
        result = api.provision(device_id)
        config["team_id"] = result.get("team_id", "")
        config["user_id"] = result.get("user_id", "")
        import platform
        import socket

        config["hostname"] = socket.gethostname()
        config["platform"] = platform.system().lower()
        _write_config(paths, config)
    except TrackAPIError as e:
        console.print(f"[red]Provision failed:[/red] {e}")
        raise typer.Exit(1)

    # Detect sources
    sources = detect_sources()
    found = [s for s in sources if s.is_present()]
    if not found:
        console.print(
            "[yellow]No AI tool sessions found[/yellow] (~/.claude, Claude Desktop local-agent sessions, ~/.codex, ~/.cursor)"
        )
    else:
        for s in found:
            console.print(f"  [green]✓[/green] Found {s.name} at {s.root}")

    # Install and start daemon
    if is_installed() and is_running(paths):
        console.print("[yellow]Daemon already running.[/yellow] Restarting...")
        uninstall()

    console.print("Installing daemon service...")
    try:
        install(paths)
    except Exception as e:
        console.print(f"[red]Service install failed:[/red] {e}")
        raise typer.Exit(1)

    console.print(
        "\n[bold green]✓ Tracking enabled.[/bold green] Syncing in background."
    )
    console.print("  Run [bold]flt track status[/bold] to check progress.")


@app.command()
def disable() -> None:
    """Stop tracking and remove the daemon service."""
    if not is_installed():
        console.print("Track daemon is not installed.")
        return
    uninstall()
    console.print("[green]✓[/green] Track daemon removed.")


@app.command()
def status() -> None:
    """Show sync status."""
    paths = TrackPaths.default()
    running = is_running(paths)
    s = read_status(paths)
    blocklist_summary = _blocklist_summary(read_track_config(paths))

    if not running:
        console.print("[yellow]Daemon not running.[/yellow]", end=" ")
        if not is_installed():
            console.print("Run [bold]flt track enable[/bold] to start.")
        else:
            console.print("Service installed but not alive — check logs.")
        if s:
            console.print(f"  Last sync: {s.last_sync or 'never'}")
        if blocklist_summary:
            console.print(
                f"  Blocked: {blocklist_summary} [dim](run flt track blocked)[/dim]"
            )
        return

    if not s:
        console.print("[yellow]Daemon running but no status yet.[/yellow]")
        if blocklist_summary:
            console.print(
                f"  Blocked: {blocklist_summary} [dim](run flt track blocked)[/dim]"
            )
        return

    state_color = {"idle": "green", "syncing": "yellow", "error": "red"}.get(
        s.state, "white"
    )
    console.print(
        f"[{state_color}]● {s.state.upper()}[/{state_color}]  pid={s.pid}  last sync={s.last_sync or 'never'}"
    )

    # Queue stats
    q = UploadQueue(paths)
    stats = q.stats()
    q.close()
    pending = stats.get("pending", 0)
    in_flight = stats.get("in_flight", 0)
    done = stats.get("done", 0)
    failed = stats.get("failed", 0)

    console.print(
        f"  Queue: [yellow]{pending}[/yellow] pending  [cyan]{in_flight}[/cyan] uploading  [green]{done}[/green] done  [red]{failed}[/red] failed"
    )
    if blocklist_summary:
        console.print(
            f"  Blocked: {blocklist_summary} [dim](run flt track blocked)[/dim]"
        )

    # Sources table
    if s.sources:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Agent")
        table.add_column("Found", justify="center")
        table.add_column("Files", justify="right")
        for agent, info in s.sources.items():
            found_str = "[green]✓[/green]" if info.get("found") else "[dim]✗[/dim]"
            table.add_row(agent, found_str, str(info.get("files", 0)))
        console.print(table)

    if s.errors:
        console.print("\n[red]Errors:[/red]")
        for err in s.errors[-3:]:
            console.print(f"  {err}")

    console.print(f"\n  Logs: {paths.log_file}")


def _blocklist_summary(config: dict) -> str | None:
    blocklist = TrackBlocklist.from_config(config)
    parts = [
        _count_label(len(blocklist.session_ids), "session id"),
        _count_label(len(blocklist.paths), "path"),
        _count_label(len(blocklist.path_globs), "path glob"),
    ]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None


def _count_label(count: int, label: str) -> str | None:
    if count == 0:
        return None
    suffix = "" if count == 1 else "s"
    return f"{count} {label}{suffix}"


@app.command()
def daemon(
    once: bool = typer.Option(
        False,
        "--once",
        help="Run one reconcile/upload/manifest pass and exit. Useful for local E2E tests.",
    ),
) -> None:
    """Run the sync daemon (called by launchd/systemd — not for direct use)."""
    daemon_main(once=once)


@app.command()
def gc(
    max_age_hours: int = typer.Option(
        24,
        "--max-age-hours",
        help="Remove fleet-track checkout files older than this. 0 removes all.",
    ),
) -> None:
    """Remove fleet-track-managed checkout files.

    Identifies checkouts by the `_fleet_meta` marker on the first row
    (never deletes native sessions). Useful after running cross-tool
    resume tests to clean up the on-disk views.
    """
    from .resumer import gc_checkouts

    n = gc_checkouts(max_age_hours=max_age_hours)
    if n == 0:
        console.print("[dim]Nothing to clean up.[/dim]")
    else:
        unit = "files" if n != 1 else "file"
        console.print(f"[green]✓[/green] Removed {n} fleet-track checkout {unit}.")


@app.command()
def logs() -> None:
    """Tail the daemon log."""
    log_path = TrackPaths.default().log_file
    if not log_path.exists():
        console.print("No log file found.")
        raise typer.Exit(1)
    import subprocess

    subprocess.run(["tail", "-f", str(log_path)])


@app.command("block")
def block_sessions(
    session_ids: list[str] = typer.Argument(
        ...,
        help="Session id(s) to exclude from FleetTrack uploads.",
    ),
) -> None:
    """Block local session ids from upload."""
    added = add_blocked_session_ids(TrackPaths.default(), session_ids)
    if added:
        console.print(f"[green]✓[/green] Blocked {len(added)} session id(s).")
    else:
        console.print("[dim]No changes; those session ids were already blocked.[/dim]")
    console.print(
        "[dim]Blocked sessions are pruned on the next daemon reconcile.[/dim]"
    )


@app.command("unblock")
def unblock_sessions(
    session_ids: list[str] = typer.Argument(
        ...,
        help="Session id(s) to allow for FleetTrack uploads again.",
    ),
) -> None:
    """Remove local session ids from the upload blocklist."""
    removed = remove_blocked_session_ids(TrackPaths.default(), session_ids)
    if removed:
        console.print(f"[green]✓[/green] Unblocked {len(removed)} session id(s).")
    else:
        console.print("[dim]No changes; those session ids were not blocked.[/dim]")


@app.command("blocked")
def list_blocked_sessions() -> None:
    """List locally blocked upload ids and paths."""
    config = read_track_config(TrackPaths.default())
    session_ids = config.get("blocked_session_ids") or []
    paths = config.get("blocked_paths") or []
    globs = config.get("blocked_path_globs") or []
    if not session_ids and not paths and not globs:
        console.print("[dim]No FleetTrack upload blocks configured.[/dim]")
        return

    if session_ids:
        console.print("[bold]Blocked session ids[/bold]")
        for session_id in session_ids:
            console.print(f"  {session_id}")
    if paths:
        console.print("[bold]Blocked paths[/bold]")
        for path in paths:
            console.print(f"  {path}")
    if globs:
        console.print("[bold]Blocked path globs[/bold]")
        for pattern in globs:
            console.print(f"  {pattern}")


# ------------------------------------------------------------------ #
# Session listing + resume                                              #
# ------------------------------------------------------------------ #


def _resolve_session_store(source: str):
    """Build the SessionStore the CLI reads from based on `--source`.

    Modes:
      - `remote` (default): orchestrator-backed metadata/search index.
      - `local`: Fleet's prebuilt local index under ~/.fleet/track/local-store.
    """
    from .store import (
        LocalSessionStore,
        RemoteSessionStore,
    )

    source = _normalize_source(source)
    paths = TrackPaths.default()
    if source == "remote":
        return RemoteSessionStore()
    if source == LOCAL_SESSION_SOURCE:
        return LocalSessionStore(paths)
    raise typer.BadParameter(f"Unknown --source value: {source!r}")


def _normalize_source(source: str) -> str:
    normalized = (source or DEFAULT_SESSION_SOURCE).strip().lower()
    if normalized not in {DEFAULT_SESSION_SOURCE, LOCAL_SESSION_SOURCE}:
        raise typer.BadParameter(
            "Unknown --source value. Expected 'remote' or 'local'."
        )
    return normalized


def _validate_cursor_for_source(source: str, cursor: str | None) -> None:
    if not cursor or _normalize_source(source) == "remote":
        return
    from .store import _decode_cursor

    try:
        _decode_cursor(cursor)
    except ValueError as e:
        raise typer.BadParameter(str(e))


def _session_dicts(sessions) -> list[dict]:
    from dataclasses import asdict

    return [asdict(s) for s in sessions]


def _print_sessions_json(
    *,
    query: str | None,
    source: str,
    sessions,
    next_cursor: str | None,
    mode: str | None = None,
) -> None:
    payload = {
        "query": query,
        "source": _normalize_source(source),
        "items": _session_dicts(sessions),
        "next_cursor": next_cursor,
    }
    if mode is not None:
        payload["mode"] = mode
    console.print_json(json.dumps(payload))


def _read_json_argument(value: str) -> dict:
    """Read an inline JSON object, @file JSON object, or stdin JSON object."""
    raw = value
    if value == "-":
        raw = sys.stdin.read()
    elif value.startswith("@"):
        raw = Path(value[1:]).read_text()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"invalid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise typer.BadParameter("body must be a JSON object")
    return parsed


def _sessions_from_api_items(items: list[dict]):
    from .store import _session_from_api

    return [_session_from_api(item) for item in items]


def _search_filter_catalog() -> dict:
    return search_filter_catalog()


def _print_search_filter_catalog(json_out: bool) -> None:
    catalog = _search_filter_catalog()
    if json_out:
        console.print_json(json.dumps(catalog))
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Field")
    table.add_column("Type")
    table.add_column("Description")
    for field in catalog["filterable_attributes"]:
        table.add_row(field["name"], field["type"], field["description"])
    console.print(table)
    console.print()
    console.print("[bold]Operators[/bold]")
    console.print(", ".join(catalog["operators"]))
    console.print()
    console.print(
        "[bold]Logical operators[/bold] " + ", ".join(catalog["logical_operators"])
    )
    console.print()
    console.print("[bold]Time fields[/bold] " + ", ".join(catalog["time_fields"]))


def _render_sessions_table(sessions, next_cursor: str | None) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Tool")
    table.add_column("When")
    table.add_column("Project")
    table.add_column("Events", justify="right")
    table.add_column("From")

    from .picker import _human_when, _short_cwd

    for s in sessions:
        fork = (s.forked_from or "")[:8] if s.forked_from else ""
        table.add_row(
            s.id[:8],
            s.tool,
            _human_when(s.last_active or s.started_at),
            _short_cwd(s.cwd),
            str(s.event_count),
            fork,
        )
    console.print(table)
    if next_cursor:
        console.print(f"[dim]next_cursor:[/dim] {next_cursor}")


@app.command(name="ls")
def list_sessions(
    tool: str = typer.Option(
        None, "--tool", "-t", help="Filter by tool (claude/codex)"
    ),
    cwd: str = typer.Option(None, "--cwd", help="Filter by working directory"),
    since: str = typer.Option(
        None, "--since", help="Only sessions active since (ISO-8601 or natural)"
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Max rows per page (1..200)"),
    cursor: str = typer.Option(
        None,
        "--cursor",
        help="Opaque cursor from a prior `next_cursor:` line. Drives paged scripting.",
    ),
    query: str = typer.Option(
        None,
        "--query",
        "-q",
        help="Substring filter over session metadata (id/tool/cwd/title).",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON for scripting"),
    source: str = typer.Option(
        DEFAULT_SESSION_SOURCE,
        "--source",
        help=SOURCE_HELP,
    ),
) -> None:
    """List sessions across all tracked AI tools.

    Sort is fixed at recency-first (`last_active DESC, id DESC`) — same
    on every backend so cursors are interchangeable.

    Pagination is cursor-based. Pass `--cursor <token>` from a previous
    `next_cursor:` line to fetch the next page. The cursor format is
    byte-compatible with the orchestrator's `/v1/track/sessions` endpoint
    so scripting against either side uses the same opaque tokens.
    """
    store = _resolve_session_store(source)
    _validate_cursor_for_source(source, cursor)

    sessions, next_cursor = store.page(
        tool=tool,
        cwd=cwd,
        since=since,
        query=query,
        limit=limit,
        cursor=cursor,
    )

    if json_out:
        _print_sessions_json(
            query=query,
            source=source,
            sessions=sessions,
            next_cursor=next_cursor,
        )
        return

    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        console.print("  Run [bold]flt track enable[/bold] to start syncing.")
        return

    _render_sessions_table(sessions, next_cursor)


@app.command(name="search")
def search_sessions(
    body_arg: str | None = typer.Argument(
        None,
        metavar="[BODY]",
        help="JSON search body. Pass inline JSON, @file, or - for stdin.",
    ),
    json_out: bool = typer.Option(
        True,
        "--json/--table",
        help="Emit agent-friendly JSON by default; use --table for a human table.",
    ),
    show_filters: bool = typer.Option(
        False,
        "--filters",
        "--list-filters",
        help="List filterable attributes/operators and exit.",
    ),
) -> None:
    """Search tracked sessions.

    Search uses Fleet's structured session search shape. Orchestrator compiles
    filters/time into the Turbopuffer session index, injects the caller's team
    boundary, and returns hydrated Fleet session metadata. Use `flt track aggregate`
    for aggregate Postgres queries and `flt track download` before intra-session
    analysis with local tools such as `rg`, `jq`, or Python.

    Input:

    \b
      flt track search '{"query":"bugbot local index","limit":20}'
      flt track search '{"mode":"keyword","query":"schema error","filters":{"tool":"codex"}}'
      flt track search @search.json
      flt track search -
      flt track search --filters

    JSON fields:

    \b
      query    string   Natural-language search text.
      mode     string   hybrid (default), keyword, semantic, or recent.
      limit    integer  Maximum ranked results to return. Defaults to 50.
      filters  object   Mongo-style exact/range/boolean filters.
      time     object   Shared time range, e.g. {"field":"last_active","since":"7d"}.

    Filterable attributes:

    \b
      session_id, user_id, device_id, tool, cwd, repo_url, git_branch,
      model, forked_from, event_count, started_at, last_active

    `team_id` is always injected by orchestrator. Filters support direct field
    equality, Mongo-style field operators, and boolean operators:

    \b
      {"tool":"codex"}
      {"event_count":{"$gte":1000}}
      {"$or":[{"repo_url":{"$contains":"theseus"}},{"repo_url":{"$contains":"fleet-sdk"}}]}

    Example body:

    \b
      {"query":"deployment debugging",
       "filters":{"repo_url":{"$contains":"theseus"},"tool":{"$in":["codex","claude"]}},
       "time":{"field":"last_active","gte":"2026-05-01T00:00:00Z"},
       "limit":25}
    """
    if show_filters:
        _print_search_filter_catalog(json_out)
        return

    if body_arg is None:
        raise typer.BadParameter("BODY is required unless --filters is provided")

    body = _read_json_argument(body_arg)

    if "limit" not in body and "top_k" not in body:
        body["limit"] = DEFAULT_SEARCH_TOP_K
    data = TrackAPIClient().search_sessions(body)
    sessions = _sessions_from_api_items(data.get("items", []))
    next_cursor = data.get("next_cursor")

    if json_out:
        _print_sessions_json(
            query=body.get("query") if isinstance(body.get("query"), str) else None,
            source="remote",
            sessions=sessions,
            next_cursor=next_cursor,
            mode=str(body.get("mode") or "hybrid"),
        )
        return

    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return

    _render_sessions_table(sessions, next_cursor)


@app.command(name="aggregate")
def aggregate_sessions(
    body_arg: str = typer.Argument(
        ...,
        metavar="BODY",
        help="JSON aggregate body. Pass inline JSON, @file, or - for stdin.",
    ),
    json_out: bool = typer.Option(
        True,
        "--json/--table",
        help="Emit agent-friendly JSON by default; use --table for a human table.",
    ),
) -> None:
    """Aggregate tracked session metadata.

    Aggregates are Postgres-backed and use the same Mongo-style `filters` and
    `time` shapes as search. No raw SQL is accepted. The body also supports
    `time_bucket`, `order_by`, and `having` for SQL-like grouped summaries.

    \b
      flt track aggregate '{"group_by":["repo_url","tool"],"metrics":["count","sum_event_count"]}'
      flt track aggregate '{"time":{"field":"last_active","since":"30d"},"group_by":["tool"]}'
      flt track aggregate '{"group_by":["repo_url"],"time_bucket":{"field":"last_active","interval":"day"},"having":{"count":{"$gte":5}},"order_by":[{"field":"count","direction":"desc"}]}'
    """
    body = _read_json_argument(body_arg)
    data = TrackAPIClient().aggregate_sessions(body)
    if json_out:
        console.print_json(json.dumps(data))
        return

    groups = data.get("groups") or []
    if not groups:
        console.print("[dim]No aggregate rows found.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Key")
    metric_names = [k for k in groups[0].keys() if k != "key"]
    for name in metric_names:
        table.add_column(name, justify="right")
    for group in groups:
        table.add_row(
            json.dumps(group.get("key", {}), sort_keys=True),
            *[str(group.get(name, "")) for name in metric_names],
        )
    console.print(table)


@app.command(name="download")
def download_session(
    session_id: str = typer.Argument(..., help="Session id to download into cache."),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-download even if the cached metadata signature matches.",
    ),
    json_out: bool = typer.Option(
        True,
        "--json/--path",
        help="Emit JSON by default; use --path to print only the local JSONL path.",
    ),
) -> None:
    """Download a session for local intra-session analysis.

    The command asks orchestrator for an authorized presigned URL, downloads the
    session into `~/.fleet/track/cache/sessions/<id>/session.jsonl`, and
    transparently decompresses gzip-stored objects. After this, agents should use
    local tools such as `rg`, `jq`, `sed`, or Python against the returned path.
    """
    from .download import ensure_local_session

    cached = ensure_local_session(session_id, force=force)
    payload = cached.to_dict()
    if json_out:
        console.print_json(json.dumps(payload))
    else:
        console.print(payload["path"])


@app.command()
def build_local_index(
    replace: bool = typer.Option(
        True,
        "--replace/--append",
        help="Replace the existing Fleet local index before scanning native files.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON for scripting"),
) -> None:
    """Build the dev/test local index from native session files.

    This is intentionally manual: normal Track commands use the remote source.
    Local mode reads only this Fleet index and does not live-scan native files.
    """
    from .store import LocalSessionStore, NativeFilesSessionStore

    paths = TrackPaths.default()
    local_root = paths.track_dir / "local-store"
    if replace and local_root.exists():
        shutil.rmtree(local_root)

    local = LocalSessionStore(paths)
    native = NativeFilesSessionStore(home=paths.home)

    indexed = 0
    skipped = 0
    cursor = None
    while True:
        sessions, next_cursor = native.page(limit=200, cursor=cursor)
        for session in sessions:
            try:
                local.create(session, list(native.own_events(session.id)))
            except Exception:
                skipped += 1
                continue
            indexed += 1
        if next_cursor is None:
            break
        cursor = next_cursor

    payload = {
        "source": LOCAL_SESSION_SOURCE,
        "indexed": indexed,
        "skipped": skipped,
        "path": str(local_root),
        "replace": replace,
    }
    if json_out:
        console.print_json(json.dumps(payload))
        return

    console.print(
        f"[green]Indexed[/green] {indexed} sessions into {local_root}"
        + (f" [yellow]({skipped} skipped)[/yellow]" if skipped else "")
    )
    console.print("  Use [bold]--source local[/bold] to read this index.")


@app.command()
def resume(
    session_id: str = typer.Argument(
        None, help="Session id (full or unique prefix). Omit to pick interactively."
    ),
    in_tool: str = typer.Option(
        None, "--in", help="Resume in this tool (default: same as source)"
    ),
    last: bool = typer.Option(False, "--last", help="Resume the most recent session"),
    prompt: str = typer.Option(
        None, "--prompt", "-p", help="Initial prompt to send to the resumed CLI"
    ),
    source: str = typer.Option(
        DEFAULT_SESSION_SOURCE,
        "--source",
        help=SOURCE_HELP,
    ),
    compact: bool = typer.Option(
        True,
        "--compact/--no-compact",
        help="Project the source session into a context-fitting view. "
        "Default on. --no-compact ships the full history; large sessions "
        "will overflow the target model's context window.",
    ),
    target_tokens: int = typer.Option(
        0,
        "--target-tokens",
        help="Target token budget for the cross-tool checkout. 0 picks a "
        "sensible default for the target tool/model.",
    ),
    target_model: str = typer.Option(
        None,
        "--target-model",
        help="Hint the target model (e.g. claude-opus-4-7, gpt-5) so the "
        "compactor budgets correctly. Auto-detected when possible.",
    ),
    max_tool_output: int = typer.Option(
        4_000,
        "--max-tool-output",
        help="Per-tool-result output character cap. 0 disables truncation.",
    ),
    summarize: bool = typer.Option(
        True,
        "--summarize/--no-summarize",
        help="When events are dropped to fit budget, prepend a structured "
        "summary of what was dropped. Default on.",
    ),
) -> None:
    """Resume a tracked session in a (possibly different) AI tool.

    Without an id, opens an interactive Textual picker (search at top,
    table below; pgdn/pgup to page). With `--in`, the session is
    converted to the target tool's format and dropped into a quarantined
    `.fleet-checkouts/` namespace before invoking the target's native
    resume command.
    """
    store = _resolve_session_store(source)

    # Resolve which session.
    if last:
        sessions = store.list(limit=1)
        if not sessions:
            console.print("[red]No sessions found.[/red]")
            raise typer.Exit(1)
        target_session = sessions[0]
    elif session_id:
        try:
            target_session = store.get(session_id)
        except KeyError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        if target_session is None:
            console.print(f"[red]No session matches[/red] {session_id!r}")
            raise typer.Exit(1)
    else:
        # Interactive picker — two stages: session, then target tool.
        # Both stages use Textual (`textual` package); no external `fzf`
        # binary required. Page size auto-fits the terminal so the user
        # never has to scroll within a page; every keystroke re-queries
        # the store via `page(query=...)`.
        from .picker import installed_tools
        from .picker_textual import pick_session_textual, pick_tool_textual

        target_session = pick_session_textual(
            store,
            header="type to search · pgdn next · pgup prev · ⏎ open · esc cancel",
        )
        if target_session is None:
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)
        # The textual picker returns Sessions straight from `store.page()`,
        # so they're already fully populated — no synthesize-and-resolve
        # dance needed.

        # Stage 2: target tool. Skip the picker if the user already passed
        # `--in`, or if there's exactly one CLI installed (no choice to make).
        if in_tool is None:
            available = installed_tools()
            if not available:
                console.print(
                    "[red]No supported AI CLIs found on PATH.[/red] "
                    "Install one of: claude, codex."
                )
                raise typer.Exit(1)
            if len(available) == 1:
                in_tool = available[0]
            else:
                chosen_tool = pick_tool_textual(
                    target_session.tool,
                    available=available,
                    header=f"Resume {target_session.id[:8]} in which tool?",
                )
                if chosen_tool is None:
                    console.print("[dim]Cancelled.[/dim]")
                    raise typer.Exit(0)
                in_tool = chosen_tool

    target_tool = in_tool or target_session.tool
    cwd_hint = f" [dim]in {target_session.cwd}[/dim]" if target_session.cwd else ""
    console.print(
        f"[dim]Resuming[/dim] {target_session.id[:8]} "
        f"[dim]({target_session.tool} → {target_tool})[/dim]{cwd_hint}"
    )

    # The actual resume + checkout creation is implemented in resumer.py
    # (kept out of cli.py so the dispatch logic is testable).
    from .compactor import (
        TokenBudget,
        TruncationCompactor,
        TruncationConfig,
        budget_for,
    )
    from .resumer import RepoNotLocalError, resume_session

    if compact:
        budget = (
            TokenBudget(target=target_tokens)
            if target_tokens > 0
            else budget_for(target_tool, target_model)
        )
        compactor = TruncationCompactor(
            budget=budget,
            cfg=TruncationConfig(
                max_tool_output_chars=max_tool_output if max_tool_output > 0 else None,
                summarize_dropped=summarize,
            ),
        )
    else:
        compactor = None  # ship full history; will likely overflow large sessions

    try:
        resume_session(
            store=store,
            session=target_session,
            target_tool=target_tool,
            prompt=prompt,
            paths=TrackPaths.default(),
            compactor=compactor,
            target_model=target_model,
        )
    except NotImplementedError as e:
        console.print(f"[red]Not yet supported:[/red] {e}")
        raise typer.Exit(2)
    except RepoNotLocalError as e:
        # Cross-machine session whose repo we can't find on this host.
        # Multi-line message — print verbatim, no [red] wrapper.
        console.print(str(e))
        raise typer.Exit(3)
    except Exception as e:
        console.print(f"[red]Resume failed:[/red] {e}")
        raise typer.Exit(1)


# ------------------------------------------------------------------ #
# install-mcp / uninstall-mcp                                          #
# ------------------------------------------------------------------ #


_MCP_CLIENT_LABEL = {
    "claude-code": "Claude Code",
    "claude-desktop": "Claude Desktop",
    "codex": "Codex",
}


def _mcp_clients_to_target(client: Optional[str], all_clients: bool) -> list[str]:
    from .mcp_install import CLIENT_CHOICES, detect_installed_clients

    if client and all_clients:
        console.print("[red]--client and --all are mutually exclusive.[/red]")
        raise typer.Exit(2)
    if client:
        if client not in CLIENT_CHOICES:
            console.print(
                f"[red]Unknown client:[/red] {client}. "
                f"Choose from: {', '.join(CLIENT_CHOICES)}"
            )
            raise typer.Exit(2)
        return [client]
    if all_clients:
        return list(CLIENT_CHOICES)
    return detect_installed_clients()


@app.command(name="install-mcp")
def install_mcp(
    client: Optional[str] = typer.Option(
        None, "--client", help="Target one client (claude-code|claude-desktop|codex)."
    ),
    all_clients: bool = typer.Option(
        False, "--all", help="Install for every supported client, even if not detected."
    ),
    print_only: bool = typer.Option(
        False,
        "--print",
        help="Print the config snippet that would be written; do not write.",
    ),
) -> None:
    """Install the FleetCode MCP server into local agent client configs.

    By default, detects which clients have a config file present and writes
    to all of them. Uses the `flt login` auth path; no FLEET_API_KEY is set
    in the spawned environment.
    """
    from .mcp_install import (
        config_path_for,
        install_many,
        render_snippet,
        resolve_command_spec,
    )

    targets = _mcp_clients_to_target(client, all_clients)
    if not targets:
        console.print(
            "[yellow]No supported MCP client configs detected.[/yellow] "
            "Open Claude Code, Claude Desktop, or Codex once to create their "
            "config, then re-run — or use --all / --client."
        )
        raise typer.Exit(0)

    try:
        spec = resolve_command_spec()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if print_only:
        for t in targets:
            console.print(
                f"\n[bold]{_MCP_CLIENT_LABEL[t]}[/bold] "
                f"[dim]({config_path_for(t)})[/dim]"
            )
            console.print(render_snippet(t, spec), markup=False, highlight=False)
        return

    results = install_many(targets, spec=spec)
    for r in results:
        label = _MCP_CLIENT_LABEL[r.client]
        if r.action == "added":
            console.print(f"[green]✓[/green] {label}: added [dim]({r.path})[/dim]")
        elif r.action == "updated":
            console.print(f"[green]✓[/green] {label}: updated [dim]({r.path})[/dim]")
        elif r.action == "unchanged":
            console.print(f"[dim]·[/dim] {label}: already up to date")
        elif r.action == "skipped":
            console.print(f"[dim]·[/dim] {label}: skipped ({r.detail})")
    console.print(
        "\nDone. [bold]Restart[/bold] each app to pick up the new MCP server."
    )


@app.command(name="uninstall-mcp")
def uninstall_mcp(
    client: Optional[str] = typer.Option(
        None, "--client", help="Target one client (claude-code|claude-desktop|codex)."
    ),
    all_clients: bool = typer.Option(
        False, "--all", help="Uninstall from every supported client."
    ),
) -> None:
    """Remove the FleetCode MCP server entry from local agent client configs."""
    from .mcp_install import uninstall_many

    targets = _mcp_clients_to_target(client, all_clients)
    if not targets:
        # Default to all when nothing detected, since the entry might exist in
        # a config we haven't otherwise touched.
        from .mcp_install import CLIENT_CHOICES

        targets = list(CLIENT_CHOICES)

    results = uninstall_many(targets)
    for r in results:
        label = _MCP_CLIENT_LABEL[r.client]
        if r.action == "removed":
            console.print(f"[green]✓[/green] {label}: removed [dim]({r.path})[/dim]")
        else:
            console.print(f"[dim]·[/dim] {label}: skipped ({r.detail})")
