"""Fleet SDK Task Model."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, Dict, Optional, List

from pydantic import BaseModel, Field, validator

# Import the shared VerifierFunction type that works for both async and sync
from fleet.types import VerifierFunction


def verifier_from_string(
    verifier_func: str,
    verifier_id: Optional[str] = None,
    verifier_key: Optional[str] = None,
    sha256: Optional[str] = None,
) -> VerifierFunction:
    """Create a verifier function from a string of Python code.
    
    This function creates either a SyncVerifierFunction or AsyncVerifierFunction
    based on whether the code contains async function definitions.
    
    Args:
        verifier_func: String containing the verifier function code
        verifier_id: Optional verifier ID to use
        verifier_key: Optional verifier key to use (defaults to function name)
        sha256: Optional SHA256 hash of existing server-side bundle
        
    Returns:
        VerifierFunction: Either SyncVerifierFunction or AsyncVerifierFunction
        
    Raises:
        ValueError: If function name cannot be extracted from the code
    """
    from fleet.verifiers.parse import extract_function_name, convert_new_to_old_verifier
    from fleet.verifiers.verifier import SyncVerifierFunction
    from fleet._async.verifiers.verifier import AsyncVerifierFunction
    from fleet.verifiers.db import IgnoreConfig, DatabaseSnapshot
    
    # Determine if this is an async verifier
    is_async = "async def" in verifier_func
    
    # Store original code for later
    original_code = verifier_func
    
    # Check if this is a new format verifier (has before/after parameters)
    if (
        "before: DatabaseSnapshot" in verifier_func
        and "after: DatabaseSnapshot" in verifier_func
    ):
        # Convert new format to old format
        verifier_func = convert_new_to_old_verifier(verifier_func)
        # Update function name since wrapper adds _wrapper suffix
        original_name = extract_function_name(verifier_func.split("\n")[0])
        if original_name and original_name.endswith("_wrapper"):
            function_name = original_name
        else:
            function_name = extract_function_name(verifier_func)
    else:
        # Extract function name from code
        function_name = extract_function_name(verifier_func)
    
    if not function_name:
        raise ValueError("Could not extract function name from verifier code")
    
    # Create a namespace for the function
    namespace = {
        "__builtins__": __builtins__,
        "Environment": object,  # Placeholder, will be provided at runtime
        "IgnoreConfig": IgnoreConfig,
        "DatabaseSnapshot": DatabaseSnapshot,
        "TASK_FAILED_SCORE": 0,
        "TASK_SUCCESSFUL_SCORE": 1,
    }
    
    # Execute the code to create the function
    exec(verifier_func, namespace)
    
    # Get the function from the namespace
    if function_name not in namespace:
        raise ValueError(f"Function {function_name} not found after execution")
    
    func = namespace[function_name]
    
    # Use provided key or default to function name
    key = verifier_key or function_name
    
    # Create appropriate verifier function
    if is_async:
        # Create AsyncVerifierFunction
        return AsyncVerifierFunction(
            func=func,
            key=key,
            verifier_id=verifier_id,
            sha256=sha256,
            raw_code=original_code,
            extra_requirements=None,
        )
    else:
        # For sync verifiers, we need to handle the case where the original was async
        # but got converted during unasync processing
        if "async def" in original_code and "await " in original_code:
            # Convert async code to sync for SyncVerifierFunction
            sync_code = original_code.replace("async def", "def")
            sync_code = sync_code.replace("await ", "")
            
            # Re-execute with sync code
            namespace = {
                "__builtins__": __builtins__,
                "Environment": object,
                "IgnoreConfig": IgnoreConfig,
                "DatabaseSnapshot": DatabaseSnapshot,
                "TASK_FAILED_SCORE": 0,
                "TASK_SUCCESSFUL_SCORE": 1,
            }
            exec(sync_code, namespace)
            func = namespace[function_name]
            
            return SyncVerifierFunction(
                func=func,
                key=key,
                verifier_id=verifier_id,
                sha256=sha256,
                raw_code=sync_code,
                extra_requirements=None,
            )
        else:
            # Already sync code
            return SyncVerifierFunction(
                func=func,
                key=key,
                verifier_id=verifier_id,
                sha256=sha256,
                raw_code=original_code,
                extra_requirements=None,
            )


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
                    _ = asyncio.get_running_loop()
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


def load_tasks(env_key: Optional[str] = None) -> List[Task]:
    """Convenience function to load tasks without initializing a client.

    Creates an `AsyncFleet` client under the hood and returns the tasks list.
    """
    # Use the global client by default so users can pre-configure it once
    from .global_client import get_client

    client = get_client()
    return client.load_tasks(env_key=env_key)
