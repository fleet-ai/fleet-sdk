"""Fleet env module - convenience functions for environment management."""

from .client import (
    make,
    make_for_task_async,
    list_envs,
    list_regions,
    get,
    list_instances,
    close,
    close_all,
    account,
)

# Import async versions from _async
from .._async.env.client import (
    make_async,
    list_envs_async,
    list_regions_async,
    get_async,
    list_instances_async,
    close_async,
    close_all_async,
    account_async,
)

__all__ = [
    "make",
    "make_for_task_async",
    "list_envs",
    "list_regions",
    "list_instances",
    "get",
    "close",
    "close_all",
    "make_async",
    "list_envs_async",
    "list_regions_async",
    "list_instances_async",
    "get_async",
    "close_async",
    "close_all_async",
    "account",
    "account_async",
]
