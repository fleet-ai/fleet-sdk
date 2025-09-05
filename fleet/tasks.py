"""Fleet SDK Task Model."""

from __future__ import annotations

import re
import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, validator

# Import the shared VerifierFunction type that works for both async and sync
from fleet.types import VerifierFunction


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
    verifier_func: Optional[str] = Field(None, description="Verifier function code")
    verifier: Optional[Any] = Field(
        None, description="Verifier function with decorator (async or sync)"
    )
    verifier_id: Optional[str] = Field(None, description="Verifier identifier")
    verifier_sha: Optional[str] = Field(None, description="Verifier SHA256 hash")
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Additional task metadata"
    )

    @validator("key")
    def validate_key_format(cls, v):
        """Validate key follows kebab-case format."""
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", v):
            raise ValueError(
                f"Invalid task key format: {v}. Must follow kebab-case format."
            )
        return v

    @validator("created_at", pre=True, always=True)
    def set_created_at(cls, v):
        """Set created_at to current time if not provided."""
        return v or datetime.now()

    @property
    def env_key(self) -> str:
        """Get the environment key combining env_id and version."""
        if self.version:
            return f"{self.env_id}:{self.version}"
        return self.env_id

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
        if self.verifier:
            import inspect

            result = self.verifier.remote(env, *args, **kwargs)

            # If the result is a coroutine, we need to run it
            if inspect.iscoroutine(result):
                # Check if we're already in an event loop
                try:
                    loop = asyncio.get_running_loop()
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

    def make_env(self, region: Optional[str] = None):
        """Create an environment instance for this task's environment.

        Uses the task's env_id (and version if present) to create the env.
        """
        if not self.env_id:
            raise ValueError("Task has no env_id defined")
        # Deferred import to avoid circular dependencies
        from .client import Fleet

        return Fleet().make(env_key=self.env_key, region=region)


def verifier_from_string(
    verifier_func: str,
    verifier_id: str,
    verifier_key: str,
    sha256: str = ""
) -> 'VerifierFunction':
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
        from .verifiers import verifier, SyncVerifierFunction, IgnoreConfig
        
        # Create a local namespace for executing the code
        local_namespace = {}
        
        # Execute the verifier code in the namespace
        exec(verifier_func, globals(), local_namespace)
        
        # Find the function that was defined
        func_obj = None
        for name, obj in local_namespace.items():
            if inspect.isfunction(obj):
                func_obj = obj
                break
        
        if func_obj is None:
            raise ValueError("No function found in verifier code")
        
        # Create an AsyncVerifierFunction instance
        verifier_instance = SyncVerifierFunction(func_obj, verifier_key, verifier_id)
        
        # Store additional metadata
        verifier_instance._verifier_code = verifier_func
        verifier_instance._sha256 = sha256
        
        return verifier_instance
        
    except Exception as e:
        raise ValueError(f"Failed to create verifier from string: {e}")


def load_tasks(
    env_key: Optional[str] = None,
    keys: Optional[List[str]] = None,
    version: Optional[str] = None,
    team_id: Optional[str] = None
) -> List[Task]:
    """Convenience function to load tasks with optional filtering.

    Args:
        env_key: Optional environment key to filter tasks by
        keys: Optional list of task keys to filter by
        version: Optional version to filter tasks by
        team_id: Optional team_id to filter by (admin only)

    Examples:
        tasks = await fleet.load_tasks(env_key="fira")
        tasks = await fleet.load_tasks(keys=["task1", "task2"])
        tasks = await fleet.load_tasks(env_key="fira", version="v1.0")
    """
    # Use the global client by default so users can pre-configure it once
    from .global_client import get_client

    client = get_client()
    return client.load_tasks(
        env_key=env_key, 
        keys=keys, 
        version=version, 
        team_id=team_id
    )
