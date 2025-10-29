from ..client import AsyncFleet, AsyncEnv, Task
from ...models import Environment as EnvironmentModel, AccountResponse, InstanceResponse, Run
from typing import List, Optional, Dict, Any


async def make_async(
    env_key: str,
    data_key: Optional[str] = None,
    region: Optional[str] = None,
    env_variables: Optional[Dict[str, Any]] = None,
    image_type: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
    run_id: Optional[str] = None,
) -> AsyncEnv:
    return await AsyncFleet().make(
        env_key,
        data_key=data_key,
        region=region,
        env_variables=env_variables,
        image_type=image_type,
        ttl_seconds=ttl_seconds,
        run_id=run_id,
    )


async def make_for_task_async(task: Task) -> AsyncEnv:
    return await AsyncFleet().make_for_task(task)


async def list_envs_async() -> List[EnvironmentModel]:
    return await AsyncFleet().list_envs()


async def list_regions_async() -> List[str]:
    return await AsyncFleet().list_regions()


async def list_instances_async(
    status: Optional[str] = None, region: Optional[str] = None, run_id: Optional[str] = None, profile_id: Optional[str] = None
) -> List[AsyncEnv]:
    return await AsyncFleet().instances(status=status, region=region, run_id=run_id, profile_id=profile_id)


async def get_async(instance_id: str) -> AsyncEnv:
    return await AsyncFleet().instance(instance_id)


async def close_async(instance_id: str) -> InstanceResponse:
    """Close (delete) a specific instance by ID.
    
    Args:
        instance_id: The instance ID to close
        
    Returns:
        InstanceResponse containing the deleted instance details
    """
    return await AsyncFleet().close(instance_id)


async def close_all_async(run_id: Optional[str] = None, profile_id: Optional[str] = None) -> List[InstanceResponse]:
    """Close (delete) instances using the batch delete endpoint.
    
    Args:
        run_id: Optional run ID to filter instances by
        profile_id: Optional profile ID to filter instances by (use "self" for your own profile)
        
    Returns:
        List[InstanceResponse] containing the deleted instances
        
    Note:
        At least one of run_id or profile_id must be provided.
    """
    return await AsyncFleet().close_all(run_id=run_id, profile_id=profile_id)


async def list_runs_async(profile_id: Optional[str] = None, status: Optional[str] = "active") -> List[Run]:
    """List all runs (groups of instances by run_id) with aggregated statistics.
    
    Args:
        profile_id: Optional profile ID to filter runs by (use "self" for your own profile)
        status: Filter by run status - "active" (default), "inactive", or "all"
        
    Returns:
        List[Run] containing run information with instance counts and timestamps
    """
    return await AsyncFleet().list_runs(profile_id=profile_id, status=status)


async def account_async() -> AccountResponse:
    return await AsyncFleet().account()
