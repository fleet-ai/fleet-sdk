"""Fleet SDK Task Model."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator

# Import the shared VerifierFunction type that works for both async and sync
from .types import VerifierFunction


class Task(BaseModel):
    """A task model representing a single task in the Fleet system."""
    
    key: str = Field(..., description="Unique task key identifier")
    prompt: str = Field(..., description="Task prompt or instruction")
    env_id: str = Field(..., description="Environment identifier")
    created_at: Optional[datetime] = Field(None, description="Task creation timestamp")
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

    class Config:
        """Pydantic model configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
        # Allow arbitrary types for the verifier field
        arbitrary_types_allowed = True