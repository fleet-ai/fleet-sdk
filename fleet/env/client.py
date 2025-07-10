from ..client import AsyncFleet, AsyncInstance
from ..models import Environment as EnvironmentModel
from typing import List


async def make(env_key: str) -> AsyncInstance:
    return await AsyncFleet().make(env_key)


async def list_envs() -> List[EnvironmentModel]:
    return await AsyncFleet().list_envs()


async def get(instance_id: str) -> AsyncInstance:
    return await AsyncFleet().instance(instance_id)
