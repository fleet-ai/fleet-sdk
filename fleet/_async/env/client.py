from ..client import AsyncFleet, AsyncEnv
from ...models import Environment as EnvironmentModel
from typing import List, Optional


async def make_async(env_key: str, region: Optional[str] = None) -> AsyncEnv:
    return await AsyncFleet().make(env_key, region=region)


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
