"""Logging utilities for Fleet SDK."""

import os

# Verbose logging flag - check once at import time
VERBOSE = os.environ.get("FLEET_VERBOSE", "false").lower() in ("true", "1", "yes")


def log_verbose(*args, **kwargs):
    """Print only if FLEET_VERBOSE is enabled."""
    if VERBOSE:
        print(*args, **kwargs)

