from ..client import Fleet, Environment
from ..models import Environment as EnvironmentModel
from typing import List, Optional


def make(env_key: str) -> Environment:
    return Fleet().make(env_key)


def list_envs() -> List[EnvironmentModel]:
    return Fleet().list_envs()


def list_instances(status: Optional[str] = None) -> List[Environment]:
    return Fleet().instances(status=status)


def get(instance_id: str) -> Environment:
    return Fleet().instance(instance_id)
