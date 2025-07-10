from ..client import Fleet, Environment
from ..models import Environment as EnvironmentModel
from typing import List


def make(env_key: str) -> Environment:
    return Fleet().make(env_key)


def list_envs() -> List[EnvironmentModel]:
    return Fleet().list_envs()


def get(instance_id: str) -> Environment:
    return Fleet().instance(instance_id)
