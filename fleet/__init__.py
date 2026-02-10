# Copyright 2025 Fleet AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Fleet Python SDK - Environment-based AI agent interactions."""

from typing import Any, Optional, List

from .exceptions import (
    FleetError,
    FleetAPIError,
    FleetTimeoutError,
    FleetRateLimitError,
    FleetInstanceLimitError,
    FleetConfigurationError,
)
from .client import Fleet, SyncEnv, Session
from ._async.client import AsyncFleet, AsyncEnv, AsyncSession
from .models import InstanceResponse, Environment, Run
from .instance.models import Resource, ResetResponse

# Import sync verifiers with explicit naming
from .verifiers import (
    verifier as verifier_sync,
    SyncVerifierFunction,
    DatabaseSnapshot,
    IgnoreConfig,
    SnapshotDiff,
    TASK_FAILED_SCORE,
    TASK_SUCCESSFUL_SCORE,
)

# Import async verifiers (default verifier is async for modern usage)
from ._async.verifiers import (
    verifier,
    AsyncVerifierFunction,
)

# Import async tasks (default tasks are async for modern usage)
from ._async.tasks import (
    Task,
    load_tasks as load_tasks_async,
    load_tasks_from_file as load_tasks_from_file_async,
    import_task as import_task_async,
    import_tasks as import_tasks_async,
    get_task as get_task_async,
)

# Import sync task functions
from .tasks import (
    load_tasks,
    load_tasks_from_file,
    import_task,
    import_tasks,
    get_task,
)

# Import shared types
from .types import VerifierFunction

# Create a module-level env attribute for convenient access
from . import env
from . import global_client as _global_client
from ._async import global_client as _async_global_client

__version__ = "0.2.107"

__all__ = [
    # Core classes
    "Fleet",
    "SyncEnv",
    "AsyncFleet",
    "AsyncEnv",
    # Models
    "InstanceResponse",
    "SyncEnv",
    "Resource",
    "ResetResponse",
    "Run",
    # Task models
    "Task",
    "VerifierFunction",
    # Exceptions
    "FleetError",
    "FleetAPIError",
    "FleetTimeoutError",
    "FleetConfigurationError",
    # Verifiers (async is default)
    "verifier",
    "verifier_sync",
    "AsyncVerifierFunction",
    "SyncVerifierFunction",
    "DatabaseSnapshot",
    "IgnoreConfig",
    "SnapshotDiff",
    "TASK_FAILED_SCORE",
    "TASK_SUCCESSFUL_SCORE",
    # Environment module
    "env",
    # Global client helpers
    "configure",
    "get_client",
    "reset_client",
    # Module-level functions (async is default)
    "load_tasks",
    "load_tasks_async",
    "load_tasks_from_file",
    "load_tasks_from_file_async",
    "import_task",
    "import_task_async",
    "import_tasks",
    "import_tasks_async",
    "get_task",
    "get_task_async",
    # Session helpers
    "session",
    "session_async",
    "Session",
    "AsyncSession",
    # Job helpers
    "job",
    "job_async",
    # Version
    "__version__",
]


def configure(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_retries: Optional[int] = None,
    timeout: Optional[float] = None,
):
    """Configure global clients (sync and async) once per process.

    Both sync and async default clients will be (re)created with the provided settings.
    """
    if max_retries is None:
        from .config import DEFAULT_MAX_RETRIES as _MR

        max_retries = _MR
    if timeout is None:
        from .config import DEFAULT_TIMEOUT as _TO

        timeout = _TO
    _global_client.configure(
        api_key=api_key, base_url=base_url, max_retries=max_retries, timeout=timeout
    )
    _async_global_client.configure(
        api_key=api_key, base_url=base_url, max_retries=max_retries, timeout=timeout
    )


def get_client() -> Fleet:
    """Get the global sync client."""
    return _global_client.get_client()


def reset_client():
    """Reset both sync and async global clients."""
    _global_client.reset_client()
    _async_global_client.reset_client()


def session(
    session_id: Optional[str] = None,
    job_id: Optional[str] = None,
    config: Optional[Any] = None,
    model: Optional[str] = None,
    task_key: Optional[str] = None,
    instance_id: Optional[str] = None,
) -> Session:
    """Start a new session for logging agent interactions (sync).

    This returns a Session object. The session is created on the backend
    when you call log() for the first time.

    Args:
        session_id: Optional existing session ID to resume
        job_id: Optional job ID to associate with the session
        config: Optional config object (e.g., GenerateContentConfig) to log
        model: Optional model name to log
        task_key: Optional Fleet task key
        instance_id: Optional Fleet instance ID

    Returns:
        Session object with log(), complete(), and fail() methods

    Example:
        session = fleet.session(config=config, model="gpt-4", task_key="task_123")
        session.log(history, response)
        session.complete()
    """
    client = _global_client.get_client()
    return client.start_session(
        session_id=session_id,
        job_id=job_id,
        config=config,
        model=model,
        task_key=task_key,
        instance_id=instance_id,
    )


def session_async(
    session_id: Optional[str] = None,
    job_id: Optional[str] = None,
    config: Optional[Any] = None,
    model: Optional[str] = None,
    task_key: Optional[str] = None,
    instance_id: Optional[str] = None,
) -> AsyncSession:
    """Start a new session for logging agent interactions (async).

    This returns an AsyncSession object. The session is created on the backend
    when you call log() for the first time.

    Args:
        session_id: Optional existing session ID to resume
        job_id: Optional job ID to associate with the session
        config: Optional config object (e.g., GenerateContentConfig) to log
        model: Optional model name to log
        task_key: Optional Fleet task key
        instance_id: Optional Fleet instance ID

    Returns:
        AsyncSession object with log(), complete(), and fail() methods

    Example:
        session = fleet.session_async(config=config, model="gpt-4", task_key="task_123")
        await session.log(history, response)
        await session.complete()
    """
    client = _async_global_client.get_client()
    return client.start_session(
        session_id=session_id,
        job_id=job_id,
        config=config,
        model=model,
        task_key=task_key,
        instance_id=instance_id,
    )


def job(name: Optional[str] = None) -> str:
    """Create a new trace job (sync).

    Args:
        name: Name of the job (generated server-side if not provided)

    Returns:
        The job_id string

    Example:
        job_id = fleet.job("my-agent-run")
        session = fleet.session(job_id=job_id, ...)
    """
    client = _global_client.get_client()
    return client.trace_job(name=name)


async def job_async(name: Optional[str] = None) -> str:
    """Create a new trace job (async).

    Args:
        name: Name of the job (generated server-side if not provided)

    Returns:
        The job_id string

    Example:
        job_id = await fleet.job_async("my-agent-run")
        session = await fleet.session_async(job_id=job_id, ...)
    """
    client = _async_global_client.get_client()
    return await client.trace_job(name=name)
