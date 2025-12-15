"""Fleet CLI - Command line interface for Fleet SDK."""

import json
import os
import signal
import sys
import time
from typing import List, Optional

# Load .env file if present (before other imports that might need env vars)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, skip

try:
    import typer
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn
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
eval_app = typer.Typer(help="Run evaluations", no_args_is_help=True)
projects_app = typer.Typer(help="Manage projects", no_args_is_help=True)

app.add_typer(jobs_app, name="jobs")
app.add_typer(sessions_app, name="sessions")
app.add_typer(eval_app, name="eval")
app.add_typer(projects_app, name="projects")

console = Console()


CLI_DEFAULT_BASE_URL = "https://us-west-1.fleetai.com"


def colorize_score(score: float) -> str:
    """Color a score from red (0.0) to yellow (0.5) to green (1.0)."""
    if score >= 0.7:
        return f"[green]{score:.2f}[/green]"
    elif score >= 0.4:
        return f"[yellow]{score:.2f}[/yellow]"
    else:
        return f"[red]{score:.2f}[/red]"


def format_status(status: Optional[str]) -> str:
    """Format job status with color and clean text."""
    if not status:
        return "[dim]-[/dim]"
    
    status_map = {
        "completed": "[green]✓ completed[/green]",
        "in_progress": "[yellow]● running[/yellow]",
        "pending": "[dim]○ pending[/dim]",
        "load_tasks": "[blue]↻ loading[/blue]",
        "failed": "[red]✗ failed[/red]",
        "cancelled": "[dim]✗ cancelled[/dim]",
    }
    return status_map.get(status, f"[dim]{status}[/dim]")


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
            format_status(job.status),
            job.created_at or "-",
        )

    console.print(table)
    
    # Show tips with a real job ID from the results
    first_job_id = jobs[0].id
    console.print()
    console.print("[dim]Tips:[/dim]")
    console.print(f"[dim]  flt jobs get {first_job_id}[/dim]")
    console.print(f"[dim]  flt jobs sessions {first_job_id}[/dim]")
    console.print(f"[dim]  flt sessions transcript <session-id>[/dim]")


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
    harness: Optional[str] = typer.Option(None, "--harness", help="Harness identifier"),
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
        harness=harness,
    )

    if output_json:
        console.print(json.dumps(result.model_dump(), indent=2, default=str))
        return

    console.print(f"[green]Job created successfully![/green]")
    console.print(f"  Job ID: [cyan]{result.job_id}[/cyan]")
    console.print(f"  Workflow ID: {result.workflow_job_id}")
    console.print(f"  Status: {format_status(result.status)}")
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
    console.print(f"  Status: {format_status(job.status)}")
    console.print(f"  Created At: {job.created_at or '-'}")
    
    # Show tips
    console.print()
    console.print("[dim]Tips:[/dim]")
    console.print(f"[dim]  flt jobs sessions {job.id}[/dim]")
    console.print(f"[dim]  flt sessions transcript <session-id>[/dim]")


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

    first_session_id = None
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
            if first_session_id is None:
                first_session_id = session.session_id
            result_str = "-"
            if session.verifier_execution:
                if session.verifier_execution.success:
                    result_str = "[green]PASS[/green]"
                    if session.verifier_execution.score is not None:
                        score_colored = colorize_score(session.verifier_execution.score)
                        result_str += f" ({score_colored})"
                else:
                    result_str = "[red]FAIL[/red]"

            table.add_row(
                session.session_id,
                session.model,
                format_status(session.status),
                str(session.step_count),
                result_str,
            )

        console.print(table)
        console.print()

    # Show tips with a real session ID
    if first_session_id:
        console.print("[dim]Tips:[/dim]")
        console.print(f"[dim]  flt sessions transcript {first_session_id}[/dim]")


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
    if result.instance:
        console.print(f"  Status: {format_status(result.instance.status)}")
    console.print()

    # Task info
    if result.task:
        console.print(f"[bold]Task:[/bold] {result.task.key}")
        console.print(f"  Environment: {result.task.env_id}")
        if result.task.version:
            console.print(f"  Version: {result.task.version}")
        console.print()
        console.print(f"[bold]Prompt:[/bold]")
        console.print(f"  {result.task.prompt}")
        console.print()

    # Verifier result
    if result.verifier_execution:
        status = "[green]PASS[/green]" if result.verifier_execution.success else "[red]FAIL[/red]"
        console.print(f"[bold]Verifier Result:[/bold] {status}")
        if result.verifier_execution.score is not None:
            score_colored = colorize_score(result.verifier_execution.score)
            console.print(f"  Score: {score_colored}")
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


# Projects commands


@projects_app.command("list")
def list_projects(
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all active projects."""
    client = get_client()
    
    # Call the projects endpoint directly since there's no SDK method yet
    response = client.client.request("GET", "/v1/tasks/projects")
    data = response.json()
    
    if output_json:
        console.print(json.dumps(data, indent=2, default=str))
        return
    
    projects = data.get("projects", [])
    
    if not projects:
        console.print("No projects found.")
        return
    
    table = Table(title="Projects")
    table.add_column("Project Key", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Modality", style="blue")
    table.add_column("Created At", style="dim")
    
    for project in projects:
        modality = project.get("task_modality") or "-"
        # Clean up modality display
        if modality == "tool_use":
            modality = "tool-use"
        elif modality == "computer_use":
            modality = "computer-use"
        
        table.add_row(
            project.get("project_key", "-"),
            project.get("name", "-"),
            modality,
            project.get("created_at", "-"),
        )
    
    console.print(table)
    
    # Show tips
    if projects:
        first_project = projects[0].get("project_key", "my-project")
        console.print()
        console.print("[dim]Tips:[/dim]")
        console.print(f"[dim]  flt eval run -p {first_project} -m openai/gpt-4o[/dim]")


# Eval commands


@eval_app.command("run")
def eval_run(
    project_key: Optional[str] = typer.Option(None, "--project", "-p", help="Project key to evaluate (see fleetai.com/dashboard/tasks)"),
    model: List[str] = typer.Option(..., "--model", "-m", help="Model in 'provider/model' format (repeatable)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Job name"),
    pass_k: int = typer.Option(1, "--pass-k", "-k", help="Number of passes per task"),
    max_steps: Optional[int] = typer.Option(None, "--max-steps", help="Maximum agent steps"),
    max_duration: int = typer.Option(60, "--max-duration", help="Timeout in minutes"),
    max_concurrent: int = typer.Option(30, "--max-concurrent", help="Max concurrent per model"),
    no_watch: bool = typer.Option(False, "--no-watch", help="Don't watch progress, exit immediately"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """
    Run an evaluation on a project or all tasks.

    Creates a job and watches progress. If no project is specified, runs on all tasks.

    To see your projects, visit: https://www.fleetai.com/dashboard/tasks

    \b
    Examples:
      flt eval run -m openai/gpt-4o-mini
      flt eval run -p sre-tasks -m openai/gpt-5
      flt eval run -p my-project -m anthropic/claude-sonnet-4.5 -k 3
      flt eval run -p my-project -m google/gemini-2.5-pro --no-watch
    """
    client = get_client()
    base_url = os.getenv("FLEET_BASE_URL", CLI_DEFAULT_BASE_URL)
    
    # Generate a default name if not provided
    if not name:
        model_short = model[0].split("/")[-1].split("-")[0] if model else "eval"
        if project_key:
            name = f"{project_key}-{model_short}"
        else:
            name = f"all-tasks-{model_short}"
    
    # Create the job
    try:
        result = client.create_job(
            models=model,
            name=name,
            pass_k=pass_k,
            project_key=project_key if project_key else None,
            max_steps=max_steps,
            max_duration_minutes=max_duration,
            max_concurrent_per_model=max_concurrent,
        )
    except Exception as e:
        error_str = str(e)
        # Check if it's a model not found error and format nicely
        if "not found" in error_str.lower() and "available models" in error_str.lower():
            console.print(f"[red]Error:[/red] Invalid model specified")
            console.print()
            # Extract and display available models
            if "Available models:" in error_str:
                try:
                    models_part = error_str.split("Available models:")[1].strip()
                    # Parse the list string
                    import ast
                    available = ast.literal_eval(models_part)
                    console.print("[bold]Available models:[/bold]")
                    for m in sorted(available):
                        console.print(f"  [cyan]{m}[/cyan]")
                except:
                    console.print(f"[dim]{error_str}[/dim]")
        else:
            console.print(f"[red]Error creating job:[/red] {e}")
        raise typer.Exit(1)
    
    job_id = result.job_id
    
    if output_json:
        console.print(json.dumps(result.model_dump(), indent=2, default=str))
        return
    
    # Display summary
    suite_name = project_key if project_key else "all tasks"
    console.print()
    console.print("[green bold]Eval started[/green bold]")
    console.print()
    console.print(f"  [bold]Suite[/bold]     {suite_name}")
    console.print(f"  [bold]Models[/bold]    {', '.join(model)}")
    console.print(f"  [bold]Passes[/bold]    {pass_k}")
    console.print(f"  [bold]Job ID[/bold]    [cyan]{job_id}[/cyan]")
    console.print()
    
    # Show dashboard link
    dashboard_host = base_url.replace("https://", "").replace("http://", "")
    console.print(Panel(
        f"[bold]Live agent traces[/bold]\n\n  {dashboard_host}/jobs/{job_id}",
        border_style="cyan",
    ))
    console.print()
    
    # Show tips
    console.print("[dim]Tips:[/dim]")
    console.print(f"[dim]  flt jobs get {job_id}[/dim]")
    console.print(f"[dim]  flt jobs sessions {job_id}[/dim]")
    console.print(f"[dim]  flt sessions transcript <session-id>[/dim]")
    console.print()
    
    if no_watch:
        return
    
    # Watch progress
    console.print("[dim]Press Ctrl+C to detach (eval continues in background)[/dim]")
    console.print()
    
    # Terminal statuses for sessions
    TERMINAL_SESSION_STATUSES = {"completed", "timed_out", "errored", "failed"}
    TERMINAL_JOB_STATUSES = {"completed", "errored", "failed", "cancelled"}
    
    detached = False
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Starting eval...", total=None)
            
            while True:
                # Poll sessions for progress
                try:
                    sessions_response = client.list_job_sessions(job_id)
                    total = sessions_response.total_sessions
                    
                    # Count sessions in terminal state
                    completed = sum(
                        1 for tg in sessions_response.tasks 
                        for s in tg.sessions 
                        if s.status in TERMINAL_SESSION_STATUSES
                    )
                    
                    # Count passed sessions
                    passed = sum(
                        1 for tg in sessions_response.tasks 
                        for s in tg.sessions 
                        if s.verifier_execution and s.verifier_execution.success
                    )
                    
                    if total > 0:
                        progress.update(
                            task, 
                            completed=completed, 
                            total=total,
                            description=f"[cyan]Running eval ({completed}/{total}, {passed} passed)..."
                        )
                        
                        # Check if all sessions are done
                        if completed >= total:
                            break
                except:
                    # Sessions endpoint might not be ready yet
                    pass
                
                # Also check job status as fallback
                try:
                    job = client.get_job(job_id)
                    if job.status in TERMINAL_JOB_STATUSES:
                        break
                except:
                    pass
                
                time.sleep(3)  # Poll every 3 seconds
        
        # Show final status
        console.print()
        try:
            job = client.get_job(job_id)
            console.print(f"[bold]Final Status:[/bold] {format_status(job.status)}")
            
            # Show summary stats
            sessions_response = client.list_job_sessions(job_id)
            total_passed = sum(tg.passed_sessions for tg in sessions_response.tasks)
            total_sessions = sessions_response.total_sessions
            
            if total_sessions > 0:
                pass_rate = (total_passed / total_sessions) * 100
                
                # Color the pass rate
                if pass_rate >= 70:
                    rate_color = "green"
                elif pass_rate >= 40:
                    rate_color = "yellow"
                else:
                    rate_color = "red"
                
                console.print(f"[bold]Pass Rate:[/bold] [{rate_color}]{total_passed}/{total_sessions} ({pass_rate:.1f}%)[/{rate_color}]")
                
                # Show per-task breakdown if multiple tasks
                if len(sessions_response.tasks) > 1:
                    console.print()
                    console.print("[bold]Per-task results:[/bold]")
                    for tg in sessions_response.tasks:
                        task_name = tg.task.key if tg.task else tg.task_id or "Unknown"
                        task_rate = tg.pass_rate * 100
                        console.print(f"  {task_name}: {tg.passed_sessions}/{tg.total_sessions} ({task_rate:.0f}%)")
        except:
            pass
            
    except KeyboardInterrupt:
        detached = True
        console.print()
        console.print("[yellow]Detached. Eval continues running in background.[/yellow]")
        console.print(f"[dim]Check status: flt jobs get {job_id}[/dim]")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
