"""Fleet SDK Task Model."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator

# Import the shared VerifierFunction type that works for both async and sync
from fleet.types import VerifierFunction


class Task(BaseModel):
    """A task model representing a single task in the Fleet system."""
    
    key: str = Field(..., description="Unique task key identifier")
    prompt: str = Field(..., description="Task prompt or instruction")
    env_id: str = Field(..., description="Environment identifier")
    env_variables: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Environment variables")
    created_at: Optional[datetime] = Field(None, description="Task creation timestamp")
    version: Optional[str] = Field(None, description="Task version")
    verifier_func: Optional[str] = Field(None, description="Verifier function code")
    verifier: Optional[Any] = Field(None, description="Verifier function with decorator (async or sync)")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional task metadata")

    @validator('key')
    def validate_key_format(cls, v):
        """Validate key follows kebab-case format."""
        if not re.match(r'^[a-z0-9]+(-[a-z0-9]+)*$', v):
            raise ValueError(f'Invalid task key format: {v}. Must follow kebab-case format.')
        return v

    @validator('created_at', pre=True, always=True)
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

    def verify(self, *args, **kwargs) -> float:
        """Verify the task using the verifier function (sync version).
        
        For sync environments, calls the sync verifier directly.
        For async verifiers, automatically runs them with asyncio.run().
        """
        if self.verifier:
            import asyncio
            import inspect
            
            result = self.verifier.remote(*args, **kwargs)
            
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
    
    async def verify_async(self, *args, **kwargs) -> float:
        """Verify the task using the verifier function (async version).
        
        For async environments, awaits the async verifier.
        Works with both sync and async verifiers in async contexts.
        """
        if self.verifier:
            result = self.verifier.remote(*args, **kwargs)
            # If it's a coroutine, await it
            import inspect
            if inspect.iscoroutine(result):
                return await result
            else:
                return result
        else:
            raise ValueError("No verifier function found for this task")
