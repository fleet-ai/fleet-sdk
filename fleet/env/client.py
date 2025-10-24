from ..client import Fleet, SyncEnv, Task
from ..models import Environment as EnvironmentModel, AccountResponse, InstanceResponse
from typing import List, Optional, Dict, Any


def make(
    env_key: str,
    data_key: Optional[str] = None,
    region: Optional[str] = None,
    env_variables: Optional[Dict[str, Any]] = None,
    image_type: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
    run_id: Optional[str] = None,
) -> SyncEnv:
    return Fleet().make(
        env_key,
        data_key=data_key,
        region=region,
        env_variables=env_variables,
        image_type=image_type,
        ttl_seconds=ttl_seconds,
        run_id=run_id,
    )


def make_for_task_async(task: Task) -> SyncEnv:
    return Fleet().make_for_task(task)


def list_envs() -> List[EnvironmentModel]:
    return Fleet().list_envs()


def list_regions() -> List[str]:
    return Fleet().list_regions()


def list_instances(
    status: Optional[str] = None, region: Optional[str] = None, run_id: Optional[str] = None
) -> List[SyncEnv]:
    return Fleet().instances(status=status, region=region, run_id=run_id)


def get(instance_id: str) -> SyncEnv:
    return Fleet().instance(instance_id)


def close(instance_id: str) -> InstanceResponse:
    """Close (delete) a specific instance by ID.
    
    Args:
        instance_id: The instance ID to close
        
    Returns:
        InstanceResponse containing the deleted instance details
    """
    return Fleet().close(instance_id)


def close_all(run_id: str) -> List[InstanceResponse]:
    """Close (delete) all instances associated with a run_id.
    
    Args:
        run_id: The run ID whose instances should be closed
        
    Returns:
        List[InstanceResponse] containing the deleted instances
    """
    return Fleet().close_all(run_id)


def account() -> AccountResponse:
    return Fleet().account()
