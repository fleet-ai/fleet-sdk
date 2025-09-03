from __future__ import annotations

from typing import Optional

from .client import Fleet
from .config import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT


_default_client: Optional[Fleet] = None


def get_client() -> Fleet:
    """Get the global default AsyncFleet client, creating it if needed."""
    global _default_client
    if _default_client is None:
        _default_client = Fleet()
    return _default_client


def configure(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT,
) -> Fleet:
    """Configure the global default AsyncFleet client.

    Returns the configured client instance.
    """
    global _default_client
    _default_client = Fleet(
        api_key=api_key,
        base_url=base_url,
        max_retries=max_retries,
        timeout=timeout,
    )
    return _default_client


def reset_client() -> None:
    """Reset the global default client. A new one will be created on next access."""
    global _default_client
    _default_client = None
