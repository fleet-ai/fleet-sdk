"""Type definitions for Fleet Agent."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Configuration for running an agent."""
    
    project_key: Optional[str] = None
    task_keys: Optional[List[str]] = None
    agent: str = "gemini_cua"
    model: str = "gemini-2.5-pro"
    max_concurrent: int = 4
    max_steps: int = 50
    timeout_seconds: int = 600
    screen_width: int = 1366
    screen_height: int = 768
    port_range_start: int = 8800
    vnc_port_start: int = 6080  # noVNC web port
    headful: bool = False  # Show browser via noVNC
    verbose: bool = False  # Enable verbose agent logging
    api_keys: Dict[str, str] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """Result from agent execution on a single task."""
    
    task_key: str
    final_answer: Optional[str] = None
    completed: bool = False
    error: Optional[str] = None
    steps_taken: int = 0
    execution_time_ms: int = 0
    transcript: List[Dict[str, Any]] = Field(default_factory=list)


class TaskResult(BaseModel):
    """Full result including verification."""
    
    task_key: str
    task_prompt: str
    agent_result: Optional[AgentResult] = None
    verification_success: Optional[bool] = None
    verification_score: Optional[float] = None
    error: Optional[str] = None
    execution_time_ms: int = 0

