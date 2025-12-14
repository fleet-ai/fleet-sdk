"""Fleet CLI - Command line interface for Fleet SDK."""

import json
import os
import sys
from typing import List, Optional

try:
    import typer
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print(
        "Error: CLI dependencies not installed.\n"
        "Install with: pip install 'fleet-python[cli]'",
        file=sys.stderr,
    )
    sys.exit(1)

from .client import Fleet
from .models import JobCreateRequest

app = typer.Typer(
    name="flt",
    help="Fleet CLI - Interact with Fleet jobs and sessions",
    no_args_is_help=True,
)
jobs_app = typer.Typer(help="Manage jobs", no_args_is_help=True)
sessions_app = typer.Typer(help="Manage sessions", no_args_is_help=True)

app.add_typer(jobs_app, name="jobs")
app.add_typer(sessions_app, name="sessions")

console = Console()


CLI_DEFAULT_BASE_URL = "https://us-west-1.fleetai.com"


def get_client() -> Fleet:
    """Get a Fleet client using environment variables."""
    api_key = os.getenv("FLEET_API_KEY")
    if not api_key:
        console.print(
            "[red]Error:[/red] FLEET_API_KEY environment variable not set",
            style="bold",
        )
        raise typer.Exit(1)
    base_url = os.getenv("FLEET_BASE_URL", CLI_DEFAULT_BASE_URL)
    return Fleet(api_key=api_key, base_url=base_url)


# Jobs commands


@jobs_app.command("list")
def list_jobs(
    team_id: Optional[str] = typer.Option(None, "--team-id", help="Filter by team ID (admin only)"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all jobs."""
    client = get_client()
    jobs = client.list_jobs(team_id=team_id)

    if output_json:
        console.print(json.dumps([j.model_dump() for j in jobs], indent=2, default=str))
        return

    if not jobs:
        console.print("No jobs found.")
        return

    table = Table(title="Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Created At", style="dim")

    for job in jobs:
        table.add_row(
            job.id,
            job.name or "-",
            job.status or "-",
            job.created_at or "-",
        )

    console.print(table)


@jobs_app.command("create")
def create_job(
    model: List[str] = typer.Option(..., "--model", "-m", help="Model in 'provider/model' format (repeatable)"),
    env_key: Optional[str] = typer.Option(None, "--env-key", "-e", help="Environment key"),
    project_key: Optional[str] = typer.Option(None, "--project-key", "-p", help="Project key"),
    task_keys: Optional[List[str]] = typer.Option(None, "--task-key", "-t", help="Task key (repeatable)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Job name. Supports placeholders: {id} (UUID), {sid} (short UUID), {i} (auto-increment, must be suffix)"),
    pass_k: int = typer.Option(1, "--pass-k", help="Number of passes"),
    max_steps: Optional[int] = typer.Option(None, "--max-steps", help="Maximum agent steps"),
    max_duration: int = typer.Option(60, "--max-duration", help="Timeout in minutes"),
    max_concurrent: int = typer.Option(30, "--max-concurrent", help="Max concurrent per model"),
    mode: Optional[str] = typer.Option(None, "--mode", help="Mode: 'tool-use' or 'computer-use'"),
    system_prompt: Optional[str] = typer.Option(None, "--system-prompt", help="Custom system prompt"),
    model_prompt: Optional[List[str]] = typer.Option(None, "--model-prompt", help="Per-model prompt in 'provider/model=prompt' format (repeatable)"),
    byok: Optional[List[str]] = typer.Option(None, "--byok", help="Bring Your Own Key in 'provider=key' format (repeatable)"),
    byok_ttl: Optional[int] = typer.Option(None, "--byok-ttl", help="TTL for BYOK keys in minutes"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Create a new job.

    Requires --model (repeatable) and exactly one of --env-key, --project-key, or --task-key.
    """
    # Validate mutual exclusivity
    sources = [env_key, project_key, task_keys]
    specified = sum(1 for s in sources if s)
    if specified != 1:
        console.print(
            "[red]Error:[/red] Exactly one of --env-key, --project-key, or --task-key must be specified",
            style="bold",
        )
        raise typer.Exit(1)

    # Parse model prompts
    model_prompts = None
    if model_prompt:
        model_prompts = {}
        for mp in model_prompt:
            if "=" not in mp:
                console.print(
                    f"[red]Error:[/red] Invalid --model-prompt format: {mp}. Expected 'provider/model=prompt'",
                    style="bold",
                )
                raise typer.Exit(1)
            key, value = mp.split("=", 1)
            model_prompts[key] = value

    # Parse BYOK keys
    byok_keys = None
    if byok:
        byok_keys = {}
        for b in byok:
            if "=" not in b:
                console.print(
                    f"[red]Error:[/red] Invalid --byok format: {b}. Expected 'provider=key'",
                    style="bold",
                )
                raise typer.Exit(1)
            provider, key = b.split("=", 1)
            byok_keys[provider] = key

    client = get_client()
    result = client.create_job(
        models=model,
        name=name,
        pass_k=pass_k,
        env_key=env_key,
        project_key=project_key,
        task_keys=task_keys,
        max_steps=max_steps,
        max_duration_minutes=max_duration,
        max_concurrent_per_model=max_concurrent,
        mode=mode,
        system_prompt=system_prompt,
        model_prompts=model_prompts,
        byok_keys=byok_keys,
        byok_ttl_minutes=byok_ttl,
    )

    if output_json:
        console.print(json.dumps(result.model_dump(), indent=2, default=str))
        return

    console.print(f"[green]Job created successfully![/green]")
    console.print(f"  Job ID: [cyan]{result.job_id}[/cyan]")
    console.print(f"  Workflow ID: {result.workflow_job_id}")
    console.print(f"  Status: [yellow]{result.status}[/yellow]")
    if result.name:
        console.print(f"  Name: {result.name}")


@jobs_app.command("get")
def get_job(
    job_id: str = typer.Argument(..., help="Job ID"),
    team_id: Optional[str] = typer.Option(None, "--team-id", help="Team ID (admin only)"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Get details for a specific job."""
    client = get_client()
    job = client.get_job(job_id, team_id=team_id)

    if output_json:
        console.print(json.dumps(job.model_dump(), indent=2, default=str))
        return

    console.print(f"[bold]Job Details[/bold]")
    console.print(f"  ID: [cyan]{job.id}[/cyan]")
    console.print(f"  Name: {job.name or '-'}")
    console.print(f"  Status: [yellow]{job.status or '-'}[/yellow]")
    console.print(f"  Created At: {job.created_at or '-'}")


@jobs_app.command("sessions")
def list_job_sessions(
    job_id: str = typer.Argument(..., help="Job ID"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all sessions for a job, grouped by task."""
    client = get_client()
    result = client.list_job_sessions(job_id)

    if output_json:
        console.print(json.dumps(result.model_dump(), indent=2, default=str))
        return

    console.print(f"[bold]Sessions for Job:[/bold] [cyan]{result.job_id}[/cyan]")
    console.print(f"Total Sessions: {result.total_sessions}\n")

    for task_group in result.tasks:
        task_name = task_group.task.key if task_group.task else task_group.task_id or "Unknown"
        pass_rate_pct = task_group.pass_rate * 100

        console.print(f"[bold green]Task:[/bold green] {task_name}")
        console.print(f"  Pass Rate: {task_group.passed_sessions}/{task_group.total_sessions} ({pass_rate_pct:.1f}%)")
        if task_group.average_score is not None:
            console.print(f"  Average Score: {task_group.average_score:.2f}")

        table = Table(show_header=True)
        table.add_column("Session ID", style="cyan")
        table.add_column("Model", style="blue")
        table.add_column("Status", style="yellow")
        table.add_column("Steps")
        table.add_column("Result")

        for session in task_group.sessions:
            result_str = "-"
            if session.verifier_execution:
                if session.verifier_execution.success:
                    result_str = "[green]PASS[/green]"
                    if session.verifier_execution.score is not None:
                        result_str += f" ({session.verifier_execution.score:.2f})"
                else:
                    result_str = "[red]FAIL[/red]"

            table.add_row(
                session.session_id[:8] + "...",
                session.model,
                session.status,
                str(session.step_count),
                result_str,
            )

        console.print(table)
        console.print()


# Sessions commands


@sessions_app.command("transcript")
def get_session_transcript(
    session_id: str = typer.Argument(..., help="Session ID"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Get the transcript for a session."""
    client = get_client()
    result = client.get_session_transcript(session_id)

    if output_json:
        console.print(json.dumps(result.model_dump(), indent=2, default=str))
        return

    # Header
    console.print(f"[bold]Session Transcript[/bold]")
    console.print()

    # Task info
    if result.task:
        console.print(f"[bold]Task:[/bold] {result.task.key}")
        console.print(f"  Environment: {result.task.env_id}")
        if result.task.version:
            console.print(f"  Version: {result.task.version}")
        console.print()
        console.print(f"[bold]Prompt:[/bold]")
        console.print(f"  {result.task.prompt[:200]}{'...' if len(result.task.prompt) > 200 else ''}")
        console.print()

    # Verifier result
    if result.verifier_execution:
        status = "[green]PASS[/green]" if result.verifier_execution.success else "[red]FAIL[/red]"
        console.print(f"[bold]Verifier Result:[/bold] {status}")
        if result.verifier_execution.score is not None:
            console.print(f"  Score: {result.verifier_execution.score}")
        console.print(f"  Execution Time: {result.verifier_execution.execution_time_ms}ms")
        console.print()

    # Transcript
    console.print(f"[bold]Transcript:[/bold] ({len(result.transcript)} messages)")
    console.print("-" * 60)

    for msg in result.transcript:
        role_colors = {
            "user": "green",
            "assistant": "blue",
            "tool": "yellow",
            "system": "magenta",
        }
        color = role_colors.get(msg.role, "white")
        console.print(f"[bold {color}]{msg.role.upper()}:[/bold {color}]")

        # Handle content
        if isinstance(msg.content, str):
            # Truncate long content
            content = msg.content
            if len(content) > 500:
                content = content[:500] + "..."
            console.print(f"  {content}")
        elif isinstance(msg.content, list):
            # Multimodal content
            for item in msg.content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text = item.get("text", "")
                        if len(text) > 500:
                            text = text[:500] + "..."
                        console.print(f"  {text}")
                    elif item.get("type") == "image_url":
                        console.print(f"  [dim][Image][/dim]")
                    elif item.get("type") == "tool_use":
                        console.print(f"  [dim]Tool: {item.get('name', 'unknown')}[/dim]")
                    elif item.get("type") == "tool_result":
                        console.print(f"  [dim]Tool Result[/dim]")
                else:
                    console.print(f"  {item}")
        else:
            console.print(f"  {msg.content}")

        # Tool calls
        if msg.tool_calls:
            for tc in msg.tool_calls:
                if isinstance(tc, dict):
                    name = tc.get("function", {}).get("name", tc.get("name", "unknown"))
                    console.print(f"  [dim]-> Tool call: {name}[/dim]")

        console.print()


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
