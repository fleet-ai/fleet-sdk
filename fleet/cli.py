"""Fleet CLI - Command line interface for Fleet SDK."""

import json
import os
import random
import signal
import sys
import threading
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
from .exceptions import FleetConflictError

# Word lists for random job name prefixes
_ADJECTIVES = [
    "happy", "sunny", "swift", "bright", "calm", "brave", "clever", "cosmic",
    "crystal", "dancing", "daring", "eager", "electric", "epic", "fancy",
    "fierce", "flying", "friendly", "fuzzy", "gentle", "glowing", "golden",
    "grand", "hidden", "humble", "icy", "jolly", "jumping", "kind", "lively",
    "lucky", "magic", "mighty", "misty", "noble", "peaceful", "proud", "quick",
    "quiet", "racing", "radiant", "rapid", "royal", "shiny", "silent", "smooth",
    "snappy", "sneaky", "solar", "speedy", "starry", "steady", "stellar", "stormy",
    "super", "swift", "turbo", "vibrant", "vivid", "wild", "witty", "zesty",
]
_NOUNS = [
    "falcon", "tiger", "phoenix", "dragon", "panther", "wolf", "eagle", "hawk",
    "bear", "lion", "fox", "owl", "raven", "dolphin", "whale", "shark",
    "comet", "nebula", "galaxy", "quasar", "pulsar", "nova", "meteor", "cosmos",
    "rocket", "shuttle", "orbit", "laser", "photon", "prism", "crystal", "spark",
    "thunder", "storm", "blaze", "frost", "wave", "breeze", "flame", "aurora",
    "summit", "peak", "canyon", "river", "ocean", "forest", "meadow", "garden",
    "castle", "tower", "bridge", "beacon", "compass", "anchor", "helm", "voyage",
]


def _generate_random_prefix() -> str:
    """Generate a random two-word prefix like 'sunny_falcon'."""
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    return f"{adj}_{noun}"


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
    console.print(f"[dim]  Job details:       flt jobs get {first_job_id}[/dim]")
    console.print(f"[dim]  Job sessions:      flt jobs sessions {first_job_id}[/dim]")
    console.print(f"[dim]  Session transcript: flt sessions transcript <session-id>[/dim]")


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
    
    # Create job with retry on name collision
    result = None
    original_name = name
    max_retries = 5
    
    for attempt in range(max_retries + 1):
        try:
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
            break  # Success
        except FleetConflictError:
            # Name collision - retry with random prefix
            if attempt < max_retries:
                prefix = _generate_random_prefix()
                if original_name:
                    name = f"{prefix}-{original_name}"
                else:
                    name = prefix
                continue
            console.print(f"[red]Error:[/red] Job name collision after {max_retries} retries")
            raise typer.Exit(1)
        except Exception as e:
            error_str = str(e)
            
            # Fallback: check for name collision via string matching
            if "already exists" in error_str.lower() and attempt < max_retries:
                prefix = _generate_random_prefix()
                if original_name:
                    name = f"{prefix}-{original_name}"
                else:
                    name = prefix
                continue
            
            console.print(f"[red]Error creating job:[/red] {e}")
            raise typer.Exit(1)
    
    if result is None:
        console.print(f"[red]Error:[/red] Failed to create job after {max_retries} retries")
        raise typer.Exit(1)

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
    console.print(f"[dim]  Job sessions:      flt jobs sessions {job.id}[/dim]")
    console.print(f"[dim]  Session transcript: flt sessions transcript <session-id>[/dim]")


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
        console.print(f"[dim]  Session transcript: flt sessions transcript {first_session_id}[/dim]")


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
    table.add_column("Project Key", style="cyan", no_wrap=True)
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
            modality,
            project.get("created_at", "-"),
        )
    
    console.print(table)
    
    # Show tips
    if projects:
        first_project = projects[0].get("project_key", "my-project")
        console.print()
        console.print("[dim]Tips:[/dim]")
        console.print(f"[dim]  Run eval: flt eval run -p {first_project} -m openai/gpt-4o-mini[/dim]")


# Eval commands


def _run_local_agent(
    project_key: Optional[str],
    task_keys: Optional[List[str]],
    model: str,
    agent: str,
    max_steps: int,
    max_duration: int,
    max_concurrent: int,
    byok: Optional[List[str]],
    output_json: bool,
    verbose: bool = False,
    headful: bool = False,
):
    """Run agent locally with Docker-based browser control."""
    import asyncio
    import logging
    
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')
    
    # Parse API keys
    api_keys = {}
    if os.getenv("GEMINI_API_KEY"):
        api_keys["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY")
    if os.getenv("OPENAI_API_KEY"):
        api_keys["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("ANTHROPIC_API_KEY"):
        api_keys["ANTHROPIC_API_KEY"] = os.getenv("ANTHROPIC_API_KEY")
    
    # Parse BYOK and add to api_keys
    if byok:
        provider_to_env = {"google": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
        for b in byok:
            if "=" not in b:
                console.print(f"[red]Error:[/red] Invalid --byok format: {b}")
                raise typer.Exit(1)
            provider, key = b.split("=", 1)
            api_keys[provider_to_env.get(provider.lower(), f"{provider.upper()}_API_KEY")] = key
    
    # Check for required API key based on agent
    if "gemini" in agent.lower() and "GEMINI_API_KEY" not in api_keys:
        console.print("[red]Error:[/red] GEMINI_API_KEY required for gemini_cua agent")
        console.print()
        console.print("Set it via environment:")
        console.print("  [cyan]export GEMINI_API_KEY=your-key[/cyan]")
        console.print()
        console.print("Or pass via --byok:")
        console.print("  [cyan]flt eval run ... --byok google=your-key[/cyan]")
        raise typer.Exit(1)
    
    if verbose:
        console.print(f"[dim]API keys configured: {list(api_keys.keys())}[/dim]")
    
    # Display config
    console.print()
    console.print("[green bold]Running Agent[/green bold]")
    console.print()
    if task_keys:
        console.print(f"  [bold]Tasks[/bold]       {', '.join(task_keys)}")
    else:
        console.print(f"  [bold]Project[/bold]     {project_key or 'all tasks'}")
    console.print(f"  [bold]Agent[/bold]       {agent}")
    console.print(f"  [bold]Model[/bold]       {model}")
    console.print(f"  [bold]Max Steps[/bold]   {max_steps}")
    console.print(f"  [bold]Concurrent[/bold]  {max_concurrent}")
    if headful:
        console.print(f"  [bold]Headful[/bold]     [green]Yes[/green] (browser visible via noVNC)")
    console.print()
    
    async def run():
        from fleet.agent import run_agent
        return await run_agent(
            project_key=project_key,
            task_keys=task_keys,
            agent=agent,
            model=model,
            max_concurrent=max_concurrent,
            max_steps=max_steps,
            timeout_seconds=max_duration * 60,
            api_keys=api_keys,
            headful=headful,
            verbose=verbose,
        )
    
    console.print("[dim]Starting agent...[/dim]")
    console.print()
    
    try:
        results = asyncio.run(run())
    except KeyboardInterrupt:
        console.print()
        console.print("[yellow]Cancelled.[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    
    # Display results
    if output_json:
        output = []
        for r in results:
            output.append({
                "task_key": r.task_key,
                "task_prompt": r.task_prompt,
                "completed": r.agent_result.completed if r.agent_result else False,
                "final_answer": r.agent_result.final_answer if r.agent_result else None,
                "verification_success": r.verification_success,
                "verification_score": r.verification_score,
                "error": r.error or (r.agent_result.error if r.agent_result else None),
                "steps_taken": r.agent_result.steps_taken if r.agent_result else 0,
                "execution_time_ms": r.execution_time_ms,
            })
        console.print(json.dumps(output, indent=2))
        return
    
    # Summary
    console.print()
    console.print("[bold]Results[/bold]")
    console.print("-" * 60)
    
    passed = failed = errors = 0
    
    for r in results:
        if r.error:
            status = "[red]ERROR[/red]"
            errors += 1
        elif r.verification_success:
            status = "[green]PASS[/green]"
            passed += 1
        elif r.verification_success is False:
            status = "[red]FAIL[/red]"
            failed += 1
        elif r.agent_result and r.agent_result.completed:
            status = "[yellow]DONE[/yellow]"
            passed += 1
        else:
            status = "[red]INCOMPLETE[/red]"
            failed += 1
        
        key = r.task_key[:40] + "..." if len(r.task_key) > 40 else r.task_key
        score = f" ({r.verification_score:.2f})" if r.verification_score is not None else ""
        console.print(f"  {status}{score}  {key}")
        
        if r.error:
            # Show first 100 chars of error
            err = r.error.replace('\n', ' ')[:100]
            console.print(f"         [dim]{err}[/dim]")
    
    console.print("-" * 60)
    
    total = len(results)
    if total > 0:
        rate = (passed / total) * 100
        color = "green" if rate >= 70 else "yellow" if rate >= 40 else "red"
        console.print(f"[bold]Pass Rate:[/bold] [{color}]{passed}/{total} ({rate:.1f}%)[/{color}]")
        if errors:
            console.print(f"[bold]Errors:[/bold] [red]{errors}[/red]")


def _listen_for_detach_key(stop_event: threading.Event):
    """Listen for Ctrl+B in a background thread to signal detachment."""
    try:
        # Platform-specific keyboard input handling
        if sys.platform == 'win32':
            import msvcrt
            while not stop_event.is_set():
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch == b'\x02':  # Ctrl+B
                        stop_event.set()
                        break
                time.sleep(0.1)
        else:
            # Unix-like systems
            import select
            import tty
            import termios

            old_settings = termios.tcgetattr(sys.stdin)
            try:
                tty.setcbreak(sys.stdin.fileno())
                while not stop_event.is_set():
                    # Check if input is available with timeout
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        ch = sys.stdin.read(1)
                        if ch == '\x02':  # Ctrl+B
                            stop_event.set()
                            break
            finally:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
    except Exception:
        # If we can't set up keyboard listening, just exit gracefully
        pass


@eval_app.command("run")
def eval_run(
    project_key: Optional[str] = typer.Option(None, "--project", "-p", help="Project key to evaluate"),
    task_keys: Optional[List[str]] = typer.Option(None, "--task", "-t", help="Specific task key(s) to run (repeatable)"),
    model: List[str] = typer.Option(..., "--model", "-m", help="Model (e.g., google/gemini-2.5-pro)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Job name"),
    pass_k: int = typer.Option(1, "--pass-k", "-k", help="Number of passes per task"),
    max_steps: Optional[int] = typer.Option(None, "--max-steps", help="Maximum agent steps"),
    max_duration: int = typer.Option(60, "--max-duration", help="Timeout in minutes"),
    max_concurrent: int = typer.Option(30, "--max-concurrent", help="Max concurrent per model"),
    byok: Optional[List[str]] = typer.Option(None, "--byok", help="Bring Your Own Key: 'provider=key'"),
    no_watch: bool = typer.Option(False, "--no-watch", help="Don't watch progress"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    # Local execution
    local: Optional[str] = typer.Option(None, "--local", "-l", help="Run locally. Use 'gemini_cua' for built-in or path for custom agent"),
    headful: bool = typer.Option(False, "--headful", help="Show browser via noVNC (local mode)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug output"),
):
    """
    Run an evaluation on a project or specific tasks.

    \b
    Examples:
      # Cloud execution (default)
      flt eval run -p my-project -m google/gemini-2.5-pro
      
      # Run specific task(s)
      flt eval run -t task_abc123 -m google/gemini-2.5-pro --local gemini_cua
      
      # Local with built-in agent
      flt eval run -p my-project -m google/gemini-2.5-pro --local gemini_cua
      
      # Local with headful mode (watch the browser)
      flt eval run -p my-project -m google/gemini-2.5-pro --local gemini_cua --headful
      
      # Local with custom agent
      flt eval run -p my-project -m google/gemini-2.5-pro --local ./my-agent
    """
    # Validate: need either project or task keys
    if not project_key and not task_keys:
        console.print("[red]Error:[/red] Either --project (-p) or --task (-t) must be specified")
        raise typer.Exit(1)
    
    # Local mode
    if local is not None:
        _run_local_agent(
            project_key=project_key,
            task_keys=task_keys,
            model=model[0] if model else "gemini-2.5-pro",
            agent=local if local else "gemini_cua",
            max_steps=max_steps or 100,
            max_duration=max_duration,
            max_concurrent=max_concurrent,
            byok=byok,
            output_json=output_json,
            verbose=verbose,
            headful=headful,
        )
        return
    
    client = get_client()
    base_url = os.getenv("FLEET_BASE_URL", CLI_DEFAULT_BASE_URL)
    
    # Generate a default name if not provided
    if not name:
        model_short = model[0].split("/")[-1].split("-")[0] if model else "eval"
        if project_key:
            name = f"{project_key}-{model_short}"
        else:
            name = f"all-tasks-{model_short}"
    
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
    
    # Create the job with retry on name collision
    result = None
    original_name = name
    max_retries = 5
    
    for attempt in range(max_retries + 1):
        try:
            result = client.create_job(
                models=model,
                name=name,
                pass_k=pass_k,
                project_key=project_key if project_key else None,
                max_steps=max_steps,
                max_duration_minutes=max_duration,
                max_concurrent_per_model=max_concurrent,
                byok_keys=byok_keys,
            )
            break  # Success
        except FleetConflictError:
            # Name collision - retry with random prefix
            if attempt < max_retries:
                prefix = _generate_random_prefix()
                name = f"{prefix}-{original_name}"
                continue
            console.print(f"[red]Error:[/red] Job name collision after {max_retries} retries")
            raise typer.Exit(1)
        except Exception as e:
            error_str = str(e)
            
            # Fallback: check for name collision via string matching
            if "already exists" in error_str.lower() and attempt < max_retries:
                prefix = _generate_random_prefix()
                name = f"{prefix}-{original_name}"
                continue
            
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
    
    if result is None:
        console.print(f"[red]Error:[/red] Failed to create job after {max_retries} retries")
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
    console.print(Panel(
        f"[bold]Live agent traces[/bold]\n\n  https://www.fleetai.com/dashboard/jobs/{job_id}",
        border_style="cyan",
    ))
    console.print()
    
    # Show tips
    console.print("[dim]Tips:[/dim]")
    console.print(f"[dim]  Job details:       flt jobs get {job_id}[/dim]")
    console.print(f"[dim]  Job sessions:      flt jobs sessions {job_id}[/dim]")
    console.print(f"[dim]  Session transcript: flt sessions transcript <session-id>[/dim]")
    console.print()
    
    if no_watch:
        return
    
    # Watch progress
    console.print("[dim]Watching progress... (Press Ctrl+B to detach, job continues running)[/dim]")
    console.print()

    # Terminal statuses for sessions
    TERMINAL_SESSION_STATUSES = {"completed", "timed_out", "errored", "failed"}
    TERMINAL_JOB_STATUSES = {"completed", "errored", "failed", "cancelled"}

    detached = False
    detach_event = threading.Event()

    # Start keyboard listener thread
    listener_thread = threading.Thread(target=_listen_for_detach_key, args=(detach_event,), daemon=True)
    listener_thread.start()

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
                    
                    # Count passed sessions and collect scores
                    passed = 0
                    scores = []
                    for tg in sessions_response.tasks:
                        for s in tg.sessions:
                            if s.verifier_execution:
                                if s.verifier_execution.success:
                                    passed += 1
                                if s.verifier_execution.score is not None:
                                    scores.append(s.verifier_execution.score)
                    
                    # Calculate average score
                    avg_score = sum(scores) / len(scores) if scores else None
                    
                    if total > 0:
                        # Build description with score if available
                        if avg_score is not None:
                            desc = f"[cyan]Running ({completed}/{total}) | {passed} passed | avg: {avg_score:.2f}[/cyan]"
                        else:
                            desc = f"[cyan]Running ({completed}/{total}) | {passed} passed[/cyan]"
                        
                        progress.update(
                            task, 
                            completed=completed, 
                            total=total,
                            description=desc
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

                # Check if user pressed Ctrl+B to detach
                if detach_event.is_set():
                    detached = True
                    break

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

    finally:
        # Signal the keyboard listener thread to stop
        detach_event.set()

        # Show detached message if user pressed Ctrl+B
        if detached:
            console.print()
            console.print("[yellow]Detached. Eval continues running in background.[/yellow]")
            console.print(f"[dim]Check status: flt jobs get {job_id}[/dim]")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
