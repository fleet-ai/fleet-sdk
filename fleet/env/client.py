from ..client import Fleet, SyncEnv, Task
from ..models import Environment as EnvironmentModel, AccountResponse
from typing import List, Optional


def make(env_key: str, region: Optional[str] = None) -> SyncEnv:
    return Fleet().make(env_key, region=region)


def make_for_task(task: Task) -> SyncEnv:
    return Fleet().make_for_task(task)


def list_envs() -> List[EnvironmentModel]:
    return Fleet().list_envs()


def list_regions() -> List[str]:
    return Fleet().list_regions()


def list_instances(
    status: Optional[str] = None, region: Optional[str] = None
) -> List[SyncEnv]:
    return Fleet().instances(status=status, region=region)


def get(instance_id: str) -> SyncEnv:
    return Fleet().instance(instance_id)


def account() -> AccountResponse:
    return Fleet().account()
