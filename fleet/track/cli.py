"""flt track — CLI subcommands."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .api import TrackAPIClient, TrackAPIError
from .daemon import main as daemon_main
from .install import install, is_installed, uninstall
from .paths import TrackPaths
from .queue import UploadQueue
from .sources import detect_sources
from .status import is_running, read_status

import uuid

app = typer.Typer(help="Track local AI coding sessions", no_args_is_help=True)
console = Console()

DEFAULT_SESSION_SOURCE = "remote"
LOCAL_SESSION_SOURCE = "local"
SOURCE_HELP = (
    "Where to read sessions from: remote (default, orchestrator/Turbopuffer) "
    "or local (manually built Fleet local index)."
)


def _write_config(paths: TrackPaths, config: dict) -> None:
    paths.ensure_track_dir()
    paths.config_file.write_text(json.dumps(config, indent=2))


@app.command()
def enable() -> None:
    """Scan this machine for AI sessions and start syncing."""
    paths = TrackPaths.default()

    if not os.getenv("FLEET_API_KEY"):
        console.print(
            "[red]Not authenticated.[/red] Set [bold]FLEET_API_KEY[/bold] first."
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
            "[yellow]No AI tool sessions found[/yellow] (~/.claude, ~/.cursor, ~/.codex)"
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

    if not running:
        console.print("[yellow]Daemon not running.[/yellow]", end=" ")
        if not is_installed():
            console.print("Run [bold]flt track enable[/bold] to start.")
        else:
            console.print("Service installed but not alive — check logs.")
        if s:
            console.print(f"  Last sync: {s.last_sync or 'never'}")
        return

    if not s:
        console.print("[yellow]Daemon running but no status yet.[/yellow]")
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
        raise typer.BadParameter("--tpuf must be a JSON object")
    return parsed


def _sessions_from_api_items(items: list[dict]):
    from .store import _session_from_api

    return [_session_from_api(item) for item in items]


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
        None, "--tool", "-t", help="Filter by tool (claude/codex/cursor/opencode)"
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
        help="Search remote sessions. With --source remote, forwards the query to the server search index.",
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
    query: str | None = typer.Argument(
        None,
        help="Natural-language query to send to the session index. Omit when using --tpuf.",
    ),
    tool: str = typer.Option(
        None, "--tool", "-t", help="Filter by tool (claude/codex/cursor/opencode)"
    ),
    cwd: str = typer.Option(None, "--cwd", help="Filter by working directory"),
    since: str = typer.Option(
        None, "--since", help="Only sessions active since (ISO-8601)"
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Max rows per page (1..200)"),
    cursor: str = typer.Option(
        None,
        "--cursor",
        help="Opaque cursor from a prior search response.",
    ),
    tpuf: str = typer.Option(
        None,
        "--tpuf",
        "--raw-tpuf",
        help=(
            "Agent mode: POST Turbopuffer-shaped JSON to orchestrator. "
            "Pass inline JSON, @file, or - for stdin. Supports query, rank_by, "
            "filters, top_k."
        ),
    ),
    json_out: bool = typer.Option(
        True,
        "--json/--table",
        help="Emit agent-friendly JSON by default; use --table for a human table.",
    ),
    source: str = typer.Option(
        DEFAULT_SESSION_SOURCE,
        "--source",
        help=SOURCE_HELP,
    ),
) -> None:
    """Search tracked sessions.

    With the default remote source, the query is forwarded to the orchestrator
    search endpoint, which uses Turbopuffer. Use `--source local` only after
    manually building the dev/test local index.

    \b
    Agent raw mode:

      flt track search --tpuf '{"query":"bugbot local index","top_k":20}'
      flt track search --tpuf @search.json
      flt track search --tpuf -

    Raw mode sends a JSON object to `POST /v1/track/sessions/search`.
    Supported fields are `query`, `rank_by`, `filters`, and `top_k`.
    `query` runs orchestrator-managed hybrid search: BM25 over `search_text`
    plus ANN over `vector`. `rank_by` and `filters` are forwarded in
    Turbopuffer shape. The server always injects the caller's team boundary
    and returns hydrated Fleet session metadata.

    \b
    Example raw filter body:

      {"query":"deployment debugging",
       "filters":["And",[["repo_url","Eq","git@github.com:fleet-ai/theseus.git"],
                         ["tool","Eq","codex"]]],
       "top_k":25}
    """
    if tpuf is not None:
        if _normalize_source(source) != "remote":
            raise typer.BadParameter("--tpuf requires --source remote")
        if cursor:
            raise typer.BadParameter("--cursor is not supported with --tpuf")
        if any(value is not None for value in (tool, cwd, since)):
            raise typer.BadParameter(
                "--tool, --cwd, and --since are not applied with --tpuf; "
                "put structured filters in the JSON body"
            )

        body = _read_json_argument(tpuf)
        body.setdefault("top_k", limit)
        if query is not None and "query" not in body and "rank_by" not in body:
            body["query"] = query

        data = TrackAPIClient().search_sessions_raw(body)
        sessions = _sessions_from_api_items(data.get("items", []))
        next_cursor = data.get("next_cursor")
        if json_out:
            _print_sessions_json(
                query=body.get("query") if isinstance(body.get("query"), str) else None,
                source=source,
                sessions=sessions,
                next_cursor=next_cursor,
                mode="tpuf",
            )
            return
        if not sessions:
            console.print("[dim]No sessions found.[/dim]")
            return
        _render_sessions_table(sessions, next_cursor)
        return

    if query is None or not query.strip():
        raise typer.BadParameter("query must not be empty")

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
        return

    _render_sessions_table(sessions, next_cursor)


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
                    "Install one of: claude, codex, cursor, opencode."
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
