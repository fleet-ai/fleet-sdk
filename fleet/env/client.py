from ..client import Fleet, SyncEnv, Task
from ..models import Environment as EnvironmentModel, AccountResponse
from typing import List, Optional, Dict, Any


def make(
    env_key: str,
    data_key: Optional[str] = None,
    region: Optional[str] = None,
    env_variables: Optional[Dict[str, Any]] = None,
    image_type: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> SyncEnv:
    return Fleet().make(
        env_key,
        data_key=data_key,
        region=region,
        env_variables=env_variables,
        image_type=image_type,
        ttl_seconds=ttl_seconds,
    )


def make_for_task_async(task: Task) -> SyncEnv:
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
