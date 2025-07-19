from ..client import Fleet, Environment
from ..models import Environment as EnvironmentModel
from typing import List, Optional


def make(env_key: str, region: Optional[str] = None) -> Environment:
    return Fleet().make(env_key, region=region)


def list_envs() -> List[EnvironmentModel]:
    return Fleet().list_envs()


def list_regions() -> List[str]:
    return Fleet().list_regions()


def list_instances(
    status: Optional[str] = None, region: Optional[str] = None
) -> List[Environment]:
    return Fleet().instances(status=status, region=region)


def get(instance_id: str) -> Environment:
    return Fleet().instance(instance_id)
