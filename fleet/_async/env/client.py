from ..client import AsyncFleet, AsyncEnv, Task
from ...models import Environment as EnvironmentModel, AccountResponse
from typing import List, Optional, Dict, Any


async def make_async(
    env_key: str,
    data_key: Optional[str] = None,
    region: Optional[str] = None,
    env_variables: Optional[Dict[str, Any]] = None,
    image_type: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> AsyncEnv:
    return await AsyncFleet().make(
        env_key,
        data_key=data_key,
        region=region,
        env_variables=env_variables,
        image_type=image_type,
        ttl_seconds=ttl_seconds,
    )


async def make_for_task_async(task: Task) -> AsyncEnv:
    return await AsyncFleet().make_for_task(task)


async def list_envs_async() -> List[EnvironmentModel]:
    return await AsyncFleet().list_envs()


async def list_regions_async() -> List[str]:
    return await AsyncFleet().list_regions()


async def list_instances_async(
    status: Optional[str] = None, region: Optional[str] = None
) -> List[AsyncEnv]:
    return await AsyncFleet().instances(status=status, region=region)


async def get_async(instance_id: str) -> AsyncEnv:
    return await AsyncFleet().instance(instance_id)


async def account_async() -> AccountResponse:
    return await AsyncFleet().account()
