"""Fleet SDK Environment Factory."""

import os
from typing import Dict, Optional, Any, List, Union, Tuple
from datetime import datetime

from .base import Environment, EnvironmentConfig, RemoteEnvironment
from ..exceptions import FleetEnvironmentError, FleetAuthenticationError
from ..config import get_config, FleetConfig
from ..client import FleetAPIClient, EnvDetails, InstanceRequest


# Registry of available environment types with versioning
ENVIRONMENT_REGISTRY: Dict[str, Dict[str, Dict[str, str]]] = {
    "browser": {
        "chrome-desktop": {
            "v1": "web_browser",
            "v2": "web_browser",
            "latest": "v2"
        },
        "firefox-desktop": {
            "v1": "web_browser",
            "latest": "v1"
        },
        "safari-desktop": {
            "v1": "web_browser",
            "latest": "v1"
        },
        "chrome-mobile": {
            "v1": "mobile_browser",
            "latest": "v1"
        }
    },
    "database": {
        "postgres": {
            "v1": "database",
            "latest": "v1"
        },
        "mysql": {
            "v1": "database",
            "latest": "v1"
        }
    },
    "file-system": {
        "unix": {
            "v1": "file_system",
            "latest": "v1"
        }
    },
    "api": {
        "rest": {
            "v1": "api",
            "latest": "v1"
        }
    }
}


class EnvironmentInstance:
    """Represents a live environment instance."""
    
    def __init__(
        self,
        instance_id: str,
        env_key: str,
        status: str,
        created_at: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.instance_id = instance_id
        self.env_key = env_key
        self.status = status
        self.created_at = created_at
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert instance to dictionary representation."""
        return {
            "instance_id": self.instance_id,
            "env_key": self.env_key,
            "status": self.status,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


def _parse_environment_spec(environment_spec: str) -> Tuple[str, Optional[str]]:
    """Parse environment specification into name and version.
    
    Args:
        environment_spec: Environment specification in format:
            - "name:version" (e.g., "fira:v1.2.5")
            - "name" (defaults to None, will use environment's default version)
            
    Returns:
        Tuple of (name, version)
        
    Raises:
        FleetEnvironmentError: If the specification format is invalid
    """
    if ":" in environment_spec:
        name, version = environment_spec.split(":", 1)
        return name, version
    else:
        return environment_spec, None





async def make(
    environment_spec: str,
    version: Optional[str] = None,
    region: Optional[str] = None,
    **kwargs: Any,
) -> Environment:
    """Create a Fleet environment.
    
    Args:
        environment_spec: Environment specification in format:
            - "name:version" (e.g., "fira:v1.2.5")
            - "name" (e.g., "fira" - uses default version)
        version: Optional version to override any version in environment_spec
        region: Optional AWS region (defaults to "us-west-1")
        **kwargs: Additional configuration options
        
    Returns:
        Environment instance
        
    Raises:
        FleetEnvironmentError: If environment specification is invalid
        FleetAuthenticationError: If API key is missing or invalid
        FleetConfigurationError: If configuration is invalid
    """
    # Parse the environment specification
    env_name, parsed_version = _parse_environment_spec(environment_spec)
    
    # Use explicit version parameter if provided, otherwise use parsed version
    final_version = version or parsed_version
    
    # Load configuration from environment variables
    config = get_config(**kwargs)
    
    # API key is required
    if not config.api_key:
        raise FleetAuthenticationError(
            "API key is required. Set FLEET_API_KEY environment variable."
        )
    
    # Create environment configuration
    env_config = EnvironmentConfig(
        environment_type=env_name,
        api_key=config.api_key,
        base_url=config.base_url,
        metadata=kwargs,
    )
    
    # Add version to metadata if specified
    if final_version:
        env_config.metadata["version"] = final_version
    
    # Add region to metadata if specified
    if region:
        env_config.metadata["region"] = region
    
    # Create API client and create instance
    async with FleetAPIClient(config) as client:
        try:
            # Create instance request
            instance_request = InstanceRequest(
                env_key=env_name,
                version=final_version,
                region=region,
                **kwargs
            )
            
            # Create the instance
            instance_response = await client.create_instance(instance_request)
            
            # Create environment instance with the created instance
            env = RemoteEnvironment(env_config, instance_response=instance_response)
            
            # Initialize environment
            await _initialize_environment(env)
            
            return env
            
        except Exception as e:
            raise FleetEnvironmentError(f"Failed to create environment instance: {e}")


async def get(
    instance_id: str,
    **kwargs: Any,
) -> Environment:
    """Hydrate an environment from one that is already running.
    
    Args:
        instance_id: ID of the running environment instance to connect to
        **kwargs: Additional configuration options
        
    Returns:
        Environment instance connected to the running environment
        
    Raises:
        FleetEnvironmentError: If instance is not found or not accessible
        FleetAuthenticationError: If API key is missing or invalid
        FleetConfigurationError: If configuration is invalid
    """
    # Load configuration from environment variables
    config = get_config(**kwargs)
    
    if not config.api_key:
        raise FleetAuthenticationError(
            "API key is required. Set FLEET_API_KEY environment variable."
        )
    
    # Create API client
    async with FleetAPIClient(config) as client:
        try:
            # Get instance details from API
            instance_response = await client.get_instance(instance_id)
            
            # Create environment configuration based on instance details
            env_config = EnvironmentConfig(
                environment_type=instance_response.env_key,
                api_key=config.api_key,
                base_url=config.base_url,
                metadata=kwargs,
            )
            
            # Create environment instance with existing instance ID
            env = RemoteEnvironment(env_config, instance_id=instance_id)
            
            # Initialize environment
            await _initialize_environment(env)
            
            return env
            
        except Exception as e:
            raise FleetEnvironmentError(f"Failed to get environment instance {instance_id}: {e}")


async def list_instances(
    status: Optional[str] = None,
    env_key_filter: Optional[str] = None,
    **kwargs: Any,
) -> List[EnvironmentInstance]:
    """Get a directory of all live environment instances.
    
    Args:
        status: Filter by instance status (e.g., 'running', 'paused', 'stopped')
        env_key_filter: Filter by environment key (e.g., 'fira', 'dropbox')
        **kwargs: Additional query parameters
        
    Returns:
        List of EnvironmentInstance objects representing live instances
        
    Raises:
        FleetAuthenticationError: If API key is missing or invalid
        FleetAPIError: If API request fails
        FleetConfigurationError: If configuration is invalid
    """
    # Load configuration from environment variables
    config = get_config(**kwargs)
    
    if not config.api_key:
        raise FleetAuthenticationError(
            "API key is required. Set FLEET_API_KEY environment variable."
        )
    
    # Create API client
    async with FleetAPIClient(config) as client:
        try:
            # Get all instances from API
            instances = await client.list_instances(status=status)
            
            # Convert to EnvironmentInstance objects and apply filters
            result = []
            for instance in instances:
                # Apply environment key filter if specified
                if env_key_filter and instance.env_key != env_key_filter:
                    continue
                
                env_instance = EnvironmentInstance(
                    instance_id=instance.instance_id,
                    env_key=instance.env_key,
                    status=instance.status,
                    created_at=instance.created_at,
                    metadata={
                        "version": instance.version,
                        "region": instance.region,
                        "team_id": instance.team_id,
                        "urls": instance.urls.model_dump(),
                        "health": instance.health,
                    }
                )
                result.append(env_instance)
            
            return result
            
        except Exception as e:
            raise FleetEnvironmentError(f"Failed to list instances: {e}")


async def list_envs(**kwargs: Any) -> List[EnvDetails]:
    """Get list of available environments from Fleet service.
    
    Args:
        **kwargs: Additional query parameters
        
    Returns:
        List of EnvDetails objects with environment details
        
    Raises:
        FleetAuthenticationError: If API key is missing or invalid
        FleetAPIError: If API request fails
    """
    # Load configuration from environment variables
    config = get_config(**kwargs)
    
    if not config.api_key:
        raise FleetAuthenticationError(
            "API key is required. Set FLEET_API_KEY environment variable."
        )
    
    # Create API client
    async with FleetAPIClient(config) as client:
        # Get available environments from API - no fallback
        environments = await client.list_environments()
        return environments


def list_environments() -> List[str]:
    """List all available environment specifications.
    
    Returns:
        List of environment specifications in format "category/name:version"
    """
    env_specs = []
    for category, names in ENVIRONMENT_REGISTRY.items():
        for name, versions in names.items():
            for version in versions.keys():
                if version != "latest":  # Don't include "latest" in the list
                    env_specs.append(f"{category}/{name}:{version}")
    
    return sorted(env_specs)


def list_categories() -> List[str]:
    """List all available environment categories.
    
    Returns:
        List of category names
    """
    return list(ENVIRONMENT_REGISTRY.keys())


def list_names(category: str) -> List[str]:
    """List all available environment names in a category.
    
    Args:
        category: Environment category
        
    Returns:
        List of environment names in the category
        
    Raises:
        FleetEnvironmentError: If category is not found
    """
    if category not in ENVIRONMENT_REGISTRY:
        available_categories = ", ".join(ENVIRONMENT_REGISTRY.keys())
        raise FleetEnvironmentError(
            f"Unknown environment category: {category}. "
            f"Available categories: {available_categories}"
        )
    
    return list(ENVIRONMENT_REGISTRY[category].keys())


def list_versions(category: str, name: str) -> List[str]:
    """List all available versions for an environment.
    
    Args:
        category: Environment category
        name: Environment name
        
    Returns:
        List of available versions (excluding "latest")
        
    Raises:
        FleetEnvironmentError: If category or name is not found
    """
    if category not in ENVIRONMENT_REGISTRY:
        available_categories = ", ".join(ENVIRONMENT_REGISTRY.keys())
        raise FleetEnvironmentError(
            f"Unknown environment category: {category}. "
            f"Available categories: {available_categories}"
        )
    
    if name not in ENVIRONMENT_REGISTRY[category]:
        available_names = ", ".join(ENVIRONMENT_REGISTRY[category].keys())
        raise FleetEnvironmentError(
            f"Unknown environment name: {name} in category {category}. "
            f"Available names: {available_names}"
        )
    
    versions = [v for v in ENVIRONMENT_REGISTRY[category][name].keys() if v != "latest"]
    return sorted(versions)


def is_environment_supported(environment_spec: str) -> bool:
    """Check if an environment specification is supported.
    
    Args:
        environment_spec: Environment specification to check
        
    Returns:
        True if the environment is supported, False otherwise
    """
    try:
        env_name, version = _parse_environment_spec(environment_spec)
        # For now, we'll just check if we can parse it successfully
        # In the future, we could validate against the API
        return True
    except FleetEnvironmentError:
        return False


async def _initialize_environment(env: Environment) -> None:
    """Initialize an environment after creation.
    
    Args:
        env: Environment instance to initialize
    """
    # Perform any necessary initialization
    # This could include:
    # - Validating API key
    # - Setting up HTTP client
    # - Registering default facets
    # - Performing health checks
    
    pass


 