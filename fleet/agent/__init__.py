"""Fleet Agent - Run agents locally with Docker-based browser control.

Usage:
    # Via CLI
    flt eval run -p my-project -m google/gemini-2.5-pro --local gemini_cua
    
    # Via Python
    from fleet.agent import run_agent
    
    results = await run_agent(
        project_key="my-project",
        agent="gemini_cua",
        api_keys={"GEMINI_API_KEY": "xxx"},
    )
"""

from .types import AgentConfig, AgentResult, TaskResult
from .utils import get_agent_path, AGENT_DIR

# Import these last to avoid circular imports
from .orchestrator import run_agent, AgentOrchestrator

__all__ = [
    "AgentConfig",
    "AgentResult",
    "TaskResult",
    "run_agent",
    "AgentOrchestrator",
    "get_agent_path",
    "AGENT_DIR",
]

