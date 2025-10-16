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

"""Fleet Python SDK - Async Environment-based AI agent interactions."""

from typing import Optional, List, Dict, Any

from ..exceptions import (
    FleetError,
    FleetAPIError,
    FleetTimeoutError,
    FleetRateLimitError,
    FleetInstanceLimitError,
    FleetConfigurationError,
)
from .client import AsyncFleet, AsyncEnv
from ..models import InstanceResponse, Environment, AccountResponse
from ..instance.models import Resource, ResetResponse

# Import async verifiers
from .verifiers import (
    verifier,
    AsyncVerifierFunction,
)

# Import async tasks
from .tasks import Task, load_tasks

# Import shared types
from ..types import VerifierFunction

# Create a module-level env attribute for convenient access
from .. import env
from . import global_client as _async_global_client

__version__ = "0.1.0"

__all__ = [
    # Core classes
    "AsyncFleet",
    "AsyncEnv",
    # Models
    "InstanceResponse",
    "Resource",
    "ResetResponse",
    # Task models
    "Task",
    "VerifierFunction",
    # Exceptions
    "FleetError",
    "FleetAPIError",
    "FleetTimeoutError",
    "FleetConfigurationError",
    # Verifiers
    "verifier",
    "AsyncVerifierFunction",
    # Environment module
    "env",
    # Global client helpers
    "configure",
    "get_client",
    "reset_client",
    # Module-level functions
    "load_tasks",
    "list_envs",
    "list_regions",
    "environment",
    "make",
    "make_for_task",
    "instances",
    "instance",
    "delete",
    "load_tasks_from_file",
    "load_task_array_from_string",
    "load_task_from_string",
    "load_task_from_json",
    "export_tasks",
    "import_task",
    "import_tasks",
    "account",
    "get_task",
    # Version
    "__version__",
]


async def list_envs() -> List[Environment]:
    """List all available environments."""
    return await _async_global_client.get_client().list_envs()


async def list_regions() -> List[str]:
    """List all available regions."""
    return await _async_global_client.get_client().list_regions()


async def environment(env_key: str) -> Environment:
    """Get environment details by key."""
    return await _async_global_client.get_client().environment(env_key)


async def make(
    env_key: str,
    data_key: Optional[str] = None,
    region: Optional[str] = None,
    env_variables: Optional[Dict[str, Any]] = None,
    image_type: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> AsyncEnv:
    """Create a new environment instance.

    Example:
        env = await fleet.make("fira")
        env_with_vars = await fleet.make("fira", env_variables={"LOGGED_IN_NAME": "Alice"})
    """
    return await _async_global_client.get_client().make(
        env_key,
        data_key=data_key,
        region=region,
        env_variables=env_variables,
        image_type=image_type,
        ttl_seconds=ttl_seconds,
    )


async def make_for_task(task: Task) -> AsyncEnv:
    """Create an environment instance for a specific task."""
    return await _async_global_client.get_client().make_for_task(task)


async def instances(
    status: Optional[str] = None, region: Optional[str] = None
) -> List[AsyncEnv]:
    """List existing environment instances."""
    return await _async_global_client.get_client().instances(status, region)


async def instance(instance_id: str) -> AsyncEnv:
    """Get an existing environment instance by ID."""
    return await _async_global_client.get_client().instance(instance_id)


async def delete(instance_id: str) -> InstanceResponse:
    """Delete an environment instance."""
    return await _async_global_client.get_client().delete(instance_id)


async def load_tasks_from_file(filename: str) -> List[Task]:
    """Load tasks from a JSON file.

    Example:
        tasks = await fleet.load_tasks_from_file("my_tasks.json")
    """
    return await _async_global_client.get_client().load_tasks_from_file(filename)


async def load_task_array_from_string(serialized_tasks: str) -> List[Task]:
    """Load tasks from a JSON string containing an array of tasks.

    Example:
        tasks = await fleet.load_task_array_from_string(json_string)
    """
    return await _async_global_client.get_client().load_task_array_from_string(
        serialized_tasks
    )


async def load_task_from_string(task_string: str) -> Task:
    """Load a single task from a JSON string.

    Example:
        task = await fleet.load_task_from_string(task_json_string)
    """
    return await _async_global_client.get_client().load_task_from_string(task_string)


async def load_task_from_json(task_json: dict) -> Task:
    """Load a single task from a dictionary.

    Example:
        task = await fleet.load_task_from_json(task_dict)
    """
    return await _async_global_client.get_client().load_task_from_json(task_json)


async def export_tasks(
    env_key: Optional[str] = None, filename: Optional[str] = None
) -> Optional[str]:
    """Export tasks to a JSON file.

    Example:
        await fleet.export_tasks("fira", "fira_tasks.json")
    """
    return await _async_global_client.get_client().export_tasks(env_key, filename)


async def import_task(task, project_key: Optional[str] = None):
    """Import a single task.

    Args:
        task: Task object to import
        project_key: Optional project key to associate with the task

    Example:
        task = fleet.Task(key="my-task", prompt="Do something", env_id="my-env")
        await fleet.import_task(task)
        await fleet.import_task(task, project_key="my-project")
    """
    return await _async_global_client.get_client().import_single_task(task, project_key)


async def import_tasks(filename: str, project_key: Optional[str] = None):
    """Import tasks from a JSON file.

    Args:
        filename: Path to the JSON file of Task objects to import
        project_key: Optional project key to associate with the tasks

    Example:
        await fleet.import_tasks("tasks.json")
        await fleet.import_tasks("tasks.json", project_key="my-project")
    """
    return await _async_global_client.get_client().import_tasks(filename, project_key)


async def account() -> AccountResponse:
    """Get account information including instance limits and usage."""
    return await _async_global_client.get_client().account()


async def get_task(task_key: str, version_id: Optional[str] = None):
    """Get a task by key and optional version.

    Args:
        task_key: The key of the task to retrieve
        version_id: Optional version ID to filter by

    Example:
        task = await fleet.get_task("my-task")
        task = await fleet.get_task("my-task", version_id="v1")
    """
    return await _async_global_client.get_client().get_task(
        task_key=task_key, version_id=version_id
    )


def configure(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_retries: Optional[int] = None,
    timeout: Optional[float] = None,
):
    """Configure global async client once per process.

    Args:
        api_key: API key for authentication
        base_url: Base URL for the API
        max_retries: Maximum number of retries
        timeout: Request timeout in seconds
    """
    if max_retries is None:
        from ..config import DEFAULT_MAX_RETRIES as _MR

        max_retries = _MR
    if timeout is None:
        from ..config import DEFAULT_TIMEOUT as _TO

        timeout = _TO
    _async_global_client.configure(
        api_key=api_key, base_url=base_url, max_retries=max_retries, timeout=timeout
    )


def get_client() -> AsyncFleet:
    """Get the global async client."""
    return _async_global_client.get_client()


def reset_client():
    """Reset the async global client."""
    _async_global_client.reset_client()
