"""Agent utilities."""

from pathlib import Path

AGENT_DIR = Path(__file__).parent


def get_agent_path(name_or_path: str) -> Path:
    """Get path to an agent.
    
    Args:
        name_or_path: Either a built-in agent name (e.g., 'gemini_cua')
                      or a path to a custom agent directory
    
    Returns:
        Path to agent directory
    """
    # Check if it's a path (contains / or . or is absolute)
    if "/" in name_or_path or name_or_path.startswith(".") or Path(name_or_path).is_absolute():
        path = Path(name_or_path)
        if not path.exists():
            raise ValueError(f"Agent path not found: {name_or_path}")
        if not (path / "Dockerfile").exists():
            raise ValueError(f"Invalid agent directory (no Dockerfile): {name_or_path}")
        return path
    
    # Otherwise treat as built-in agent name
    agent_path = AGENT_DIR / name_or_path
    if not agent_path.exists():
        available = [d.name for d in AGENT_DIR.iterdir() 
                     if d.is_dir() and not d.name.startswith('_')]
        raise ValueError(f"Agent '{name_or_path}' not found. Available: {available}")
    return agent_path

