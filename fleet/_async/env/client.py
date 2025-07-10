from ..client import AsyncFleet, AsyncEnvironment
from ..models import Environment as EnvironmentModel
from typing import List


async def make_async(env_key: str) -> AsyncEnvironment:
    return await AsyncFleet().make(env_key)


async def list_envs_async() -> List[EnvironmentModel]:
    return await AsyncFleet().list_envs()


async def get_async(instance_id: str) -> AsyncEnvironment:
    return await AsyncFleet().instance(instance_id)