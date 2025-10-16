"""Fleet SDK Task Model."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, List, TYPE_CHECKING

from pydantic import BaseModel, Field, validator, field_serializer

# Import the shared VerifierFunction type that works for both async and sync
from fleet.types import VerifierFunction

if TYPE_CHECKING:
    from fleet.models import VerifiersExecuteResponse


class Task(BaseModel):
    """A task model representing a single task in the Fleet system."""

    key: str = Field(..., description="Unique task key identifier")
    prompt: str = Field(..., description="Task prompt or instruction")
    env_id: str = Field(..., description="Environment identifier")
    env_variables: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Environment variables"
    )
    created_at: Optional[datetime] = Field(None, description="Task creation timestamp")
    version: Optional[str] = Field(None, description="Task version")
    data_id: Optional[str] = Field(None, description="Data identifier")
    data_version: Optional[str] = Field(None, description="Data version")
    verifier_func: Optional[str] = Field(None, description="Verifier function code")
    verifier: Optional[Any] = Field(
        None,
        description="Verifier function with decorator (async or sync)",
        exclude=True,
    )
    verifier_id: Optional[str] = Field(None, description="Verifier identifier")
    verifier_sha: Optional[str] = Field(None, description="Verifier SHA256 hash")
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Additional task metadata"
    )
    output_json_schema: Optional[Dict[str, Any]] = Field(
        None, description="JSON schema for expected output format"
    )

    @validator("key")
    def validate_key_format(cls, v):
        return v

    @validator("created_at", pre=True, always=True)
    def set_created_at(cls, v):
        """Set created_at to current time if not provided."""
        return v or datetime.now()

    @field_serializer("created_at")
    def serialize_created_at(self, dt: Optional[datetime], _info):
        """Serialize datetime to ISO format string."""
        return dt.isoformat() if dt else None

    @property
    def env_key(self) -> str:
        """Get the environment key combining env_id and version."""
        if self.version and self.version != "None" and ":" not in self.env_id:
            return f"{self.env_id}:{self.version}"
        return self.env_id

    @property
    def data_key(self) -> Optional[str]:
        """Get the data key combining data_id and data_version."""
        if self.data_id and self.data_version:
            return f"{self.data_id}:{self.data_version}"
        elif self.data_id:
            return self.data_id
        return None

    class Config:
        """Pydantic model configuration."""

        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
        # Allow arbitrary types for the verifier field
        arbitrary_types_allowed = True

    def verify(self, env, *args, **kwargs) -> float:
        """Verify the task using the verifier function (sync version).

        For sync environments, calls the sync verifier directly.
        For async verifiers, automatically runs them with asyncio.run().
        """
        # If verifier doesn't exist but verifier_func does, rebuild it
        if not self.verifier and self.verifier_func:
            self._rebuild_verifier()

        if self.verifier:
            import inspect

            # Check if verifier has remote method (for decorated verifiers)
            result = self.verifier.remote(env, *args, **kwargs)

            # If the result is a coroutine, we need to run it
            if inspect.iscoroutine(result):
                # Check if we're already in an event loop
                try:
                    asyncio.get_running_loop()
                    # We're in an async context, can't use asyncio.run()
                    raise RuntimeError(
                        "Cannot run async verifier in sync mode while event loop is running. "
                        "Use await task.verify_async() instead."
                    )
                except RuntimeError:
                    # No event loop running, safe to use asyncio.run()
                    return asyncio.run(result)
            else:
                return result
        else:
            raise ValueError("No verifier function found for this task")

    def verify_async(self, *args, **kwargs) -> float:
        """Verify the task using the verifier function (async version).

        For async environments, awaits the async verifier.
        Works with both sync and async verifiers in async contexts.
        """
        # If verifier doesn't exist but verifier_func does, rebuild it
        if not self.verifier and self.verifier_func:
            self._rebuild_verifier()

        if self.verifier:
            result = self.verifier.remote(*args, **kwargs)
            # If it's a coroutine, await it
            import inspect

            if inspect.iscoroutine(result):
                return result
            else:
                return result
        else:
            raise ValueError("No verifier function found for this task")

    def verify_detailed(self, env, *args, **kwargs) -> "VerifiersExecuteResponse":
        """Verify the task and return the full execute response model.

        For sync environments, calls the sync verifier directly.
        For async verifiers, automatically runs them with asyncio.run().
        """
        # If verifier doesn't exist but verifier_func does, rebuild it
        if not self.verifier and self.verifier_func:
            self._rebuild_verifier()

        if self.verifier:
            import inspect

            # Check if verifier has remote_with_response method (for decorated verifiers)
            result = self.verifier.remote_with_response(env, *args, **kwargs)

            # If the result is a coroutine, we need to run it
            if inspect.iscoroutine(result):
                # Check if we're already in an event loop
                try:
                    asyncio.get_running_loop()
                    # We're in an async context, can't use asyncio.run()
                    raise RuntimeError(
                        "Cannot run async verifier in sync mode while event loop is running. "
                        "Use await task.verify_detailed_async() instead."
                    )
                except RuntimeError:
                    # No event loop running, safe to use asyncio.run()
                    return asyncio.run(result)
            else:
                return result
        else:
            raise ValueError("No verifier function found for this task")

    def verify_detailed_async(self, *args, **kwargs) -> "VerifiersExecuteResponse":
        """Verify the task and return the full execute response model (async version).

        For async environments, returns a coroutine that when awaited returns the response.
        Works with both sync and async verifiers in async contexts.
        """
        # If verifier doesn't exist but verifier_func does, rebuild it
        if not self.verifier and self.verifier_func:
            self._rebuild_verifier()

        if self.verifier:
            result = self.verifier.remote_with_response(*args, **kwargs)
            # Return the result (could be a coroutine or a value)
            return result
        else:
            raise ValueError("No verifier function found for this task")

    def _rebuild_verifier(self):
        """Rebuild the verifier from verifier_func string if it exists."""
        if self.verifier_func:
            # Use the same logic as in verifier_from_string
            verifier_id = self.verifier_id or self.key
            verifier = verifier_from_string(
                verifier_func=self.verifier_func,
                verifier_id=verifier_id,
                verifier_key=self.key,
                sha256=self.verifier_sha or "",
            )
            self.verifier = verifier

    def make_env(self, region: Optional[str] = None):
        """Create an environment instance for this task's environment.

        Uses the task's env_id (and version if present) to create the env.
        """
        if not self.env_id:
            raise ValueError("Task has no env_id defined")
        # Deferred import to avoid circular dependencies
        from .client import Fleet

        return Fleet().make(env_key=self.env_key, region=region)

    def make(
        self,
        region: Optional[str] = None,
        image_type: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ):
        """Create an environment instance with task's configuration.

        Auto-populates environment creation with:
        - env_key (env_id + version)
        - data_key (data_id + data_version, if present)
        - env_variables (if present)

        Args:
            region: Optional AWS region for the environment
            image_type: Optional image type for the environment
            ttl_seconds: Optional TTL in seconds for the instance

        Returns:
            Environment instance configured for this task

        Example:
            task = fleet.Task(key="my-task", prompt="...", env_id="my-env",
                            data_id="my-data", data_version="v1.0")
            env = task.make(region="us-west-2")
        """
        if not self.env_id:
            raise ValueError("Task has no env_id defined")

        # Deferred import to avoid circular dependencies
        from fleet.env import make

        return make(
            env_key=self.env_key,
            data_key=self.data_key,
            region=region,
            env_variables=self.env_variables if self.env_variables else None,
            image_type=image_type,
            ttl_seconds=ttl_seconds,
        )


def verifier_from_string(
    verifier_func: str, verifier_id: str, verifier_key: str, sha256: str = ""
) -> "VerifierFunction":
    """Create a verifier function from string code.

    Args:
        verifier_func: The verifier function code as a string
        verifier_id: Unique identifier for the verifier
        verifier_key: Key/name for the verifier
        sha256: SHA256 hash of the verifier code

    Returns:
        VerifierFunction instance that can be used to verify tasks
    """
    try:
        import inspect
        from .verifiers import SyncVerifierFunction
        from .verifiers.code import TASK_SUCCESSFUL_SCORE, TASK_FAILED_SCORE
        from .verifiers.db import IgnoreConfig
        from .verifiers.parsing import parse_and_validate_verifier

        # Validate the code and extract function name
        # This ensures no arbitrary code execution during import
        func_name = parse_and_validate_verifier(verifier_func)

        # Create a globals namespace with all required imports
        exec_globals = globals().copy()
        exec_globals.update(
            {
                "TASK_SUCCESSFUL_SCORE": TASK_SUCCESSFUL_SCORE,
                "TASK_FAILED_SCORE": TASK_FAILED_SCORE,
                "IgnoreConfig": IgnoreConfig,
                "Environment": object,  # Add Environment type if needed
            }
        )

        # Create a local namespace for executing the code
        local_namespace = {}

        # Execute the verifier code in the namespace
        # This is now safe because we validated it contains only declarative code
        exec(verifier_func, exec_globals, local_namespace)

        # Find the function that was defined (not imported)
        # Functions defined via exec have co_filename == '<string>'
        # Imported functions have their actual module file path
        func_obj = None
        for name, obj in local_namespace.items():
            if inspect.isfunction(obj) and obj.__code__.co_filename == "<string>":
                func_obj = obj
                break

        if func_obj is None:
            raise ValueError("No function found in verifier code")

        # Create an SyncVerifierFunction instance with raw code
        verifier_instance = SyncVerifierFunction(
            func=func_obj,
            key=verifier_key,
            verifier_id=verifier_id,
            sha256=sha256,
            raw_code=verifier_func,
        )

        # Store additional metadata
        verifier_instance._verifier_code = verifier_func
        verifier_instance._sha256 = sha256

        return verifier_instance

    except Exception as e:
        raise ValueError(f"Failed to create verifier from string: {e}")


def load_tasks_from_file(filename: str) -> List[Task]:
    """Load tasks from a JSON file.

    Example:
        tasks = fleet.load_tasks_from_file("my_tasks.json")
    """
    from .global_client import get_client

    client = get_client()
    return client.load_tasks_from_file(filename)


def load_tasks(
    env_key: Optional[str] = None,
    keys: Optional[List[str]] = None,
    version: Optional[str] = None,
    team_id: Optional[str] = None,
    project_key: Optional[str] = None,
    task_project_key: Optional[str] = None,
    data_id: Optional[str] = None,
    data_version: Optional[str] = None,
) -> List[Task]:
    """Convenience function to load tasks with optional filtering.

    Args:
        env_key: Optional environment key to filter tasks by
        keys: Optional list of task keys to filter by
        version: Optional version to filter tasks by
        team_id: Optional team_id to filter by (admin only)
        project_key: Optional project key to filter tasks by
        task_project_key: Optional task project key to filter tasks by
        data_id: Optional data identifier to filter tasks by
        data_version: Optional data version to filter tasks by

    Examples:
        tasks = fleet.load_tasks(env_key="fira")
        tasks = fleet.load_tasks(keys=["task1", "task2"])
        tasks = fleet.load_tasks(env_key="fira", version="v1.0")
        tasks = fleet.load_tasks(data_id="my-data", data_version="v1.0")
    """
    # Use the global client by default so users can pre-configure it once
    from .global_client import get_client

    client = get_client()
    return client.load_tasks(
        env_key=env_key,
        keys=keys,
        version=version,
        team_id=team_id,
        project_key=project_key,
        task_project_key=task_project_key,
        data_id=data_id,
        data_version=data_version,
    )


def update_task(
    task_key: str, prompt: Optional[str] = None, verifier_code: Optional[str] = None
):
    """Convenience function to update an existing task.

    Args:
        task_key: The key of the task to update
        prompt: New prompt text for the task (optional)
        verifier_code: Python code for task verification (optional)

    Returns:
        TaskResponse containing the updated task details

    Examples:
        response = fleet.update_task("my-task", prompt="New prompt text")
        response = fleet.update_task("my-task", verifier_code="def verify(env): return True")
    """
    from .global_client import get_client

    client = get_client()
    return client.update_task(
        task_key=task_key, prompt=prompt, verifier_code=verifier_code
    )


def get_task(task_key: str, version_id: Optional[str] = None, team_id: Optional[str] = None):
    """Convenience function to get a task by key and optional version.

    Args:
        task_key: The key of the task to retrieve
        version_id: Optional version ID to filter by
        team_id: Optional team_id to filter by (admin only)

    Returns:
        TaskResponse containing the task details

    Examples:
        response = fleet.get_task("my-task")
        response = fleet.get_task("my-task", version_id="v1")
        response = fleet.get_task("my-task", team_id="team-123")
    """
    from .global_client import get_client

    client = get_client()
    return client.get_task(task_key=task_key, version_id=version_id, team_id=team_id)


def import_task(task: Task, project_key: Optional[str] = None):
    """Convenience function to import a single task.

    Args:
        task: Task object to import
        project_key: Optional project key to associate with the task

    Returns:
        Response from the API, or None if the import failed

    Examples:
        task = fleet.Task(key="my-task", prompt="Do something", env_id="my-env")
        response = fleet.import_task(task)
        response = fleet.import_task(task, project_key="my-project")
    """
    from .global_client import get_client

    client = get_client()
    return client.import_single_task(task, project_key=project_key)


def import_tasks(filename: str, project_key: Optional[str] = None):
    """Convenience function to import tasks from a JSON file.

    Args:
        filename: Path to the JSON file of Task objects to import
        project_key: Optional project key to associate with the tasks

    Returns:
        List of responses from the API for successfully imported tasks

    Examples:
        responses = fleet.import_tasks("tasks.json")
        responses = fleet.import_tasks("tasks.json", project_key="my-project")
    """
    from .global_client import get_client

    client = get_client()
    return client.import_tasks(filename, project_key=project_key)
