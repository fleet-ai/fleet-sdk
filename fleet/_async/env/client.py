from ..client import AsyncFleet, AsyncEnvironment
from ..models import Environment as EnvironmentModel
from typing import List, Optional


async def make_async(env_key: str) -> AsyncEnvironment:
    return await AsyncFleet().make(env_key)


async def list_envs_async() -> List[EnvironmentModel]:
    return await AsyncFleet().list_envs()


async def list_instances_async(status: Optional[str] = None) -> List[AsyncEnvironment]:
    return await AsyncFleet().instances(status=status)


async def get_async(instance_id: str) -> AsyncEnvironment:
    return await AsyncFleet().instance(instance_id)
