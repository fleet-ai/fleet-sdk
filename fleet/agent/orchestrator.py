"""Agent Orchestrator - Coordinates running agents on Fleet tasks.

Architecture:
1. Load tasks from Fleet API
2. For each task (parallel up to max_concurrent):
   a. Create Fleet environment (cloud)
   b. Start Docker container with CUA server (Playwright + browser)
   c. Run agent on HOST, connecting to container's MCP server
   d. Collect results and run verification
   e. Clean up

Usage:
    results = await run_agent(
        project_key="my-project",
        agent="gemini_cua",
        api_keys={"GEMINI_API_KEY": "xxx"},
    )
"""

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .utils import get_agent_path
from .types import AgentConfig, AgentResult, TaskResult

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Orchestrates running agents on Fleet tasks."""
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self._port_counter = config.port_range_start
        self._vnc_port_counter = config.vnc_port_start
        self._port_lock = asyncio.Lock()
        self._docker_image: Optional[str] = None
        # Track available ports (recycled when tasks complete)
        self._available_ports: List[Tuple[int, int]] = []
    
    async def _get_next_ports(self) -> Tuple[int, int]:
        """Get next available MCP port and VNC port."""
        async with self._port_lock:
            # Reuse recycled ports first
            if self._available_ports:
                return self._available_ports.pop()
            # Otherwise allocate new ones
            port = self._port_counter
            vnc_port = self._vnc_port_counter
            self._port_counter += 1
            self._vnc_port_counter += 1
            return port, vnc_port
    
    async def _release_ports(self, port: int, vnc_port: int):
        """Return ports to the pool for reuse."""
        async with self._port_lock:
            self._available_ports.append((port, vnc_port))
    
    async def run(self) -> List[TaskResult]:
        """Run agents on all tasks."""
        from fleet._async import load_tasks
        from rich.console import Console
        from rich.live import Live
        from rich.spinner import Spinner
        
        console = Console()
        
        # Load tasks with spinner
        with Live(Spinner("dots", text=f"Loading tasks from {self.config.project_key}..."), console=console, transient=True):
            if self.config.task_keys:
                tasks = await load_tasks(keys=self.config.task_keys)
            elif self.config.project_key:
                tasks = await load_tasks(project_key=self.config.project_key)
            else:
                raise ValueError("Either project_key or task_keys required")
        
        console.print(f"[green]✓[/green] Loaded {len(tasks)} tasks")
        
        # Build Docker image
        agent_path = get_agent_path(self.config.agent)
        await self._build_docker_image(agent_path)
        
        # Run tasks with concurrency limit and progress
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
        
        semaphore = asyncio.Semaphore(self.config.max_concurrent)
        results = [None] * len(tasks)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task_progress = progress.add_task("Running tasks", total=len(tasks))
            
            async def run_with_semaphore(idx, task):
                async with semaphore:
                    result = await self._run_task(task)
                    progress.update(task_progress, advance=1)
                    return idx, result
            
            completed = await asyncio.gather(
                *[run_with_semaphore(i, t) for i, t in enumerate(tasks)],
                return_exceptions=True,
            )
        
        # Convert to ordered list
        for item in completed:
            if isinstance(item, Exception):
                # Find which task this was - shouldn't happen but handle it
                continue
            idx, result = item
            results[idx] = result
        
        # Fill any gaps with error results
        final = []
        for i, r in enumerate(results):
            if r is None:
                final.append(TaskResult(
                    task_key=tasks[i].key,
                    task_prompt=tasks[i].prompt,
                    error="Task failed unexpectedly",
                ))
            else:
                final.append(r)
        
        return final
    
    async def _build_docker_image(self, agent_path: Path):
        """Build Docker image for CUA server."""
        from rich.console import Console
        from rich.live import Live
        from rich.spinner import Spinner
        
        console = Console()
        dockerfile = agent_path / "Dockerfile"
        if not dockerfile.exists():
            raise FileNotFoundError(f"Dockerfile not found in {agent_path}")
        
        image_name = f"fleet-cua-{agent_path.name}"
        
        # Use fleet SDK root as build context (so Dockerfile can access fleet/utils)
        # agent_path is like: .../fleet-sdk/fleet/agent/gemini_cua
        # We want: .../fleet-sdk
        fleet_root = agent_path.parent.parent.parent
        
        with Live(Spinner("dots", text=f"Building Docker image {image_name}..."), console=console, transient=True):
            proc = await asyncio.create_subprocess_exec(
                "docker", "build",
                "-t", image_name,
                "-f", str(dockerfile),
                str(fleet_root),  # Build context is repo root
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            console.print(f"[red]✗[/red] Docker build failed")
            console.print(stderr.decode())
            raise RuntimeError(f"Docker build failed: {stderr.decode()}")
        
        self._docker_image = image_name
        console.print(f"[green]✓[/green] Docker image ready: {image_name}")
    
    async def _run_task(self, task) -> TaskResult:
        """Run agent on a single task."""
        from fleet.env import make_async
        
        start = time.time()
        task_key = task.key
        task_prompt = task.prompt
        short_key = task_key[:20]
        
        logger.debug(f"[{short_key}] Starting")
        
        env = None
        container_id = None
        port = None
        vnc_port = None
        
        try:
            # 1. Create Fleet environment
            logger.debug(f"[{short_key}] Creating env...")
            env = await make_async(
                env_key=task.env_key,
                data_key=task.data_key,
                env_variables=task.env_variables,
                ttl_seconds=self.config.timeout_seconds + 300,
            )
            env_url = env.urls.root
            logger.debug(f"[{short_key}] Env: {env_url}")
            
            await asyncio.sleep(3)  # Wait for env to be ready
            
            # 2. Start Docker container with CUA server
            port, vnc_port = await self._get_next_ports()
            logger.debug(f"[{short_key}] Starting container on port {port}...")
            container_id = await self._start_container(
                port=port,
                vnc_port=vnc_port,
                env_url=env_url,
                task_prompt=task_prompt,
                task_key=task_key,
            )
            logger.debug(f"[{short_key}] Container: {container_id[:12]}")
            
            # Always show instance URL
            print(f"[{short_key}] Instance: {env_url}")
            if self.config.headful:
                print(f"[{short_key}] Browser:  http://localhost:{vnc_port}/vnc.html")
            
            # Wait for server to be ready
            logger.debug(f"[{short_key}] Waiting for CUA server...")
            await self._wait_for_server(port)
            logger.debug(f"[{short_key}] CUA server ready")
            
            # 3. Run agent
            logger.debug(f"[{short_key}] Running agent...")
            agent_result = await self._run_agent(
                port=port,
                task_prompt=task_prompt,
                task_key=task_key,
            )
            logger.debug(f"[{short_key}] Agent done: completed={agent_result.completed}")
            
            # 4. Run verification
            verification_success = None
            verification_score = None
            
            if agent_result.completed and task.verifier:
                logger.info(f"[{task_key}] Running verification...")
                try:
                    v = await task.verify_detailed_async(
                        env=env,
                        final_answer=agent_result.final_answer,
                    )
                    verification_success = v.success
                    # Score is in v.result (the verifier function's return value)
                    verification_score = v.result if isinstance(v.result, (int, float)) else None
                    logger.info(f"[{task_key}] Verification: {verification_success}")
                except Exception as e:
                    logger.error(f"[{task_key}] Verification error: {e}")
            
            return TaskResult(
                task_key=task_key,
                task_prompt=task_prompt,
                agent_result=agent_result,
                verification_success=verification_success,
                verification_score=verification_score,
                execution_time_ms=int((time.time() - start) * 1000),
            )
        
        except Exception as e:
            logger.exception(f"[{short_key}] Failed: {e}")
            return TaskResult(
                task_key=task_key,
                task_prompt=task_prompt,
                error=str(e),
                execution_time_ms=int((time.time() - start) * 1000),
            )
        
        finally:
            # Cleanup
            if container_id:
                await self._stop_container(container_id)
            if port and vnc_port:
                await self._release_ports(port, vnc_port)
            if env:
                try:
                    await env.close()
                except:
                    pass
    
    async def _start_container(
        self,
        port: int,
        vnc_port: int,
        env_url: str,
        task_prompt: str,
        task_key: str,
    ) -> str:
        """Start Docker container with CUA server."""
        headless = "false" if self.config.headful else "true"
        
        cmd = [
            "docker", "run", "-d", "--rm",
            "-p", f"{port}:8765",
            "-e", f"FLEET_ENV_URL={env_url}",
            "-e", f"FLEET_TASK_PROMPT={task_prompt}",
            "-e", f"FLEET_TASK_KEY={task_key}",
            "-e", f"SCREEN_WIDTH={self.config.screen_width}",
            "-e", f"SCREEN_HEIGHT={self.config.screen_height}",
            "-e", f"HEADLESS={headless}",
        ]
        
        # Add noVNC port mapping if headful
        if self.config.headful:
            cmd.extend(["-p", f"{vnc_port}:6080"])
        
        cmd.append(self._docker_image)
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise RuntimeError(f"Container start failed: {stderr.decode()}")
        
        return stdout.decode().strip()
    
    async def _stop_container(self, container_id: str):
        """Stop Docker container and capture logs."""
        # Get logs before stopping
        log_proc = await asyncio.create_subprocess_exec(
            "docker", "logs", "--tail", "50", container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        logs, _ = await log_proc.communicate()
        if logs:
            logger.debug(f"Container {container_id[:12]} logs:\n{logs.decode()}")
        
        proc = await asyncio.create_subprocess_exec(
            "docker", "stop", container_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    
    async def _wait_for_server(self, port: int, timeout: int = 60):
        """Wait for CUA server to be ready."""
        import aiohttp
        
        url = f"http://localhost:{port}/health"
        start = time.time()
        
        while time.time() - start < timeout:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=2) as resp:
                        if resp.status == 200:
                            return
            except:
                pass
            await asyncio.sleep(1)
        
        raise TimeoutError(f"CUA server not ready after {timeout}s")
    
    async def _run_agent(
        self,
        port: int,
        task_prompt: str,
        task_key: str,
    ) -> AgentResult:
        """Run agent process."""
        agent_path = get_agent_path(self.config.agent)
        agent_script = agent_path / "agent.py"
        
        # Set up environment
        env = os.environ.copy()
        env.update({
            "FLEET_MCP_URL": f"http://localhost:{port}",
            "FLEET_TASK_PROMPT": task_prompt,
            "FLEET_TASK_KEY": task_key,
            "FLEET_MODEL": self.config.model,
            "FLEET_MAX_STEPS": str(self.config.max_steps),
            "FLEET_SCREEN_WIDTH": str(self.config.screen_width),
            "FLEET_SCREEN_HEIGHT": str(self.config.screen_height),
            "FLEET_VERBOSE": "true" if self.config.verbose else "false",
        })
        env.update(self.config.api_keys)
        
        proc = await asyncio.create_subprocess_exec(
            "python", str(agent_script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.config.timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return AgentResult(
                task_key=task_key,
                completed=False,
                error="Agent timeout",
            )
        
        # Parse result from stdout/stderr
        stdout_str = stdout.decode()
        stderr_str = stderr.decode()
        
        logger.debug(f"Agent stdout: {stdout_str[:500]}")
        if stderr_str:
            logger.debug(f"Agent stderr: {stderr_str[:500]}")
        
        result_json = None
        for line in stdout_str.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                try:
                    result_json = json.loads(line)
                except:
                    continue
        
        if result_json:
            return AgentResult(
                task_key=result_json.get("task_key", task_key),
                final_answer=result_json.get("final_answer"),
                completed=result_json.get("completed", False),
                error=result_json.get("error"),
                steps_taken=result_json.get("steps_taken", 0),
                execution_time_ms=result_json.get("execution_time_ms", 0),
                transcript=result_json.get("transcript", []),
            )
        
        # Include stderr in error message
        error_msg = f"Agent failed. stdout: {stdout_str[:300]}"
        if stderr_str:
            error_msg += f" | stderr: {stderr_str[:300]}"
        
        return AgentResult(
            task_key=task_key,
            completed=False,
            error=error_msg,
        )


async def run_agent(
    project_key: Optional[str] = None,
    task_keys: Optional[List[str]] = None,
    agent: str = "gemini_cua",
    model: str = "gemini-2.5-pro",
    max_concurrent: int = 4,
    max_steps: int = 50,
    timeout_seconds: int = 600,
    api_keys: Optional[Dict[str, str]] = None,
    headful: bool = False,
    verbose: bool = False,
) -> List[TaskResult]:
    """Run agent on Fleet tasks.
    
    Args:
        project_key: Fleet project to run on
        task_keys: Specific tasks (alternative to project_key)
        agent: Agent implementation (default: gemini_cua)
        model: Model to use
        max_concurrent: Max parallel tasks
        max_steps: Max agent steps per task
        timeout_seconds: Timeout per task
        api_keys: API keys (e.g., {"GEMINI_API_KEY": "xxx"})
        headful: Show browser via noVNC
        verbose: Enable verbose agent logging
    
    Returns:
        List of TaskResult
    """
    config = AgentConfig(
        project_key=project_key,
        task_keys=task_keys,
        agent=agent,
        headful=headful,
        verbose=verbose,
        model=model,
        max_concurrent=max_concurrent,
        max_steps=max_steps,
        timeout_seconds=timeout_seconds,
        api_keys=api_keys or {},
    )
    
    orchestrator = AgentOrchestrator(config)
    return await orchestrator.run()

