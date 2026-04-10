from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .client import AsyncFleet
from ..config import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT

if TYPE_CHECKING:
    from ..models import JudgeEndpointConfig


_default_client: Optional[AsyncFleet] = None


def get_client() -> AsyncFleet:
    """Get the global default AsyncFleet client, creating it if needed."""
    global _default_client
    if _default_client is None:
        _default_client = AsyncFleet()
    return _default_client


def configure(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT,
    judge_endpoint: Optional[JudgeEndpointConfig] = None,
) -> AsyncFleet:
    """Configure the global default AsyncFleet client.

    Returns the configured client instance.
    """
    global _default_client
    _default_client = AsyncFleet(
        api_key=api_key,
        base_url=base_url,
        max_retries=max_retries,
        timeout=timeout,
        judge_endpoint=judge_endpoint,
    )
    return _default_client


def reset_client() -> None:
    """Reset the global default client. A new one will be created on next access."""
    global _default_client
    _default_client = None
