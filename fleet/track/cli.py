"""flt track — CLI subcommands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .api import TrackAPIClient, TrackAPIError
from .daemon import main as daemon_main
from .install import install, is_installed, uninstall
from .sources import detect_sources
from .status import is_running, read_status, TRACK_DIR
from .daemon import CONFIG_FILE
from .queue import UploadQueue

import uuid

app = typer.Typer(help="Track local AI coding sessions", no_args_is_help=True)
console = Console()


@app.command()
def enable() -> None:
    """Scan this machine for AI sessions and start syncing."""
    from ..auth import get_valid_token

    token = get_valid_token()
    if not token:
        console.print("[red]Not authenticated.[/red] Run [bold]flt login[/bold] first.")
        raise typer.Exit(1)

    # Load or create machine ID
    TRACK_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        config = json.loads(CONFIG_FILE.read_text())
    else:
        config = {}
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(config, indent=2))

    if "device_id" not in config:
        import re, socket
        hostname = re.sub(r"[^a-z0-9-]", "-", socket.gethostname().lower())[:20].strip("-")
        config["device_id"] = f"{hostname}-{str(uuid.uuid4()).replace('-','')[:8]}"

    device_id = config["device_id"]

    # Provision with backend
    console.print("Provisioning with Fleet...")
    try:
        api = TrackAPIClient()
        result = api.provision(device_id)
        config["s3_prefix"] = result.get("s3_prefix", "")
        config["s3_bucket"] = result.get("s3_bucket", "fleet-track-sessions")
        config["team_id"] = result.get("team_id", "")
        config["user_id"] = result.get("user_id", "")
        CONFIG_FILE.write_text(json.dumps(config, indent=2))
    except TrackAPIError as e:
        console.print(f"[red]Provision failed:[/red] {e}")
        raise typer.Exit(1)

    # Detect sources
    sources = detect_sources()
    found = [s for s in sources if s.found and not s.name.endswith("_txt")]
    if not found:
        console.print("[yellow]No AI tool sessions found[/yellow] (~/.claude, ~/.cursor, ~/.codex)")
    else:
        for s in found:
            agent = "cursor" if s.name.startswith("cursor") else s.name
            console.print(f"  [green]✓[/green] Found {agent} at {s.root}")

    # Install and start daemon
    if is_installed() and is_running():
        console.print("[yellow]Daemon already running.[/yellow] Restarting...")
        uninstall()

    console.print("Installing daemon service...")
    try:
        install()
    except Exception as e:
        console.print(f"[red]Service install failed:[/red] {e}")
        raise typer.Exit(1)

    console.print("\n[bold green]✓ Tracking enabled.[/bold green] Syncing in background.")
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
    running = is_running()
    s = read_status()

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

    state_color = {"idle": "green", "syncing": "yellow", "error": "red"}.get(s.state, "white")
    console.print(f"[{state_color}]● {s.state.upper()}[/{state_color}]  pid={s.pid}  last sync={s.last_sync or 'never'}")

    # Queue stats
    q = UploadQueue()
    stats = q.stats()
    q.close()
    pending = stats.get("pending", 0)
    in_flight = stats.get("in_flight", 0)
    done = stats.get("done", 0)
    failed = stats.get("failed", 0)

    console.print(f"  Queue: [yellow]{pending}[/yellow] pending  [cyan]{in_flight}[/cyan] uploading  [green]{done}[/green] done  [red]{failed}[/red] failed")

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
        console.print(f"\n[red]Errors:[/red]")
        for err in s.errors[-3:]:
            console.print(f"  {err}")

    log_path = TRACK_DIR / "daemon.log"
    console.print(f"\n  Logs: {log_path}")


@app.command()
def daemon() -> None:
    """Run the sync daemon (called by launchd/systemd — not for direct use)."""
    daemon_main()


@app.command()
def logs() -> None:
    """Tail the daemon log."""
    log_path = TRACK_DIR / "daemon.log"
    if not log_path.exists():
        console.print("No log file found.")
        raise typer.Exit(1)
    import subprocess
    subprocess.run(["tail", "-f", str(log_path)])
