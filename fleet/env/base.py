"""Fleet SDK Base Environment Classes."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime
import asyncio
import time
import logging
from pydantic import BaseModel, Field

from ..facets.base import Facet
from ..exceptions import FleetEnvironmentError, FleetAPIError
from ..client import FleetAPIClient, InstanceRequest, InstanceResponse
from ..manager_client import FleetManagerClient, ManagerHealthResponse
from ..config import FleetConfig, get_config


logger = logging.getLogger(__name__)


class EnvironmentConfig(BaseModel):
    """Configuration for Fleet environments."""
    
    environment_type: str = Field(..., description="Type of environment (e.g., 'chrome-desktop-v1')")
    api_key: Optional[str] = Field(None, description="Fleet API key")
    base_url: str = Field(default="https://fleet.new", description="Fleet API base URL")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional configuration")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return self.model_dump()


class Environment(ABC):
    """Base class for all Fleet environments."""
    
    def __init__(self, config: EnvironmentConfig):
        self.config = config
        self._facets: Dict[str, Facet] = {}
        self._session_id: Optional[str] = None
        self._instance_id: Optional[str] = None
        self._step_count: int = 0
        
    @abstractmethod
    async def reset(
        self,
        seed: Optional[int] = None,
        timestamp: Optional[Union[str, datetime]] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> None:
        """Reset the environment.
        
        Args:
            seed: Integer seed for deterministic RNG in the env (physics, action noise, etc.)
            timestamp: ISO8601 string or datetime for the "current time" the sim should use
            options: Any additional flags the env impl supports (e.g. viewport size, login creds, feature flags)
        """
        pass
    
    @abstractmethod
    async def step(self, action: Dict[str, Any]) -> Tuple[Dict[str, Any], float, bool]:
        """Execute one step in the environment.
        
        Args:
            action: The action to execute as a dictionary
            
        Returns:
            Tuple of (state, reward, done)
        """
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close the environment and clean up resources."""
        pass
    
    @abstractmethod
    def state(self, facet_uri: str) -> Facet:
        """Get a facet for accessing environment state.
        
        Args:
            facet_uri: URI identifying the facet (e.g., 'sqlite://crm', 'browser://dom')
            
        Returns:
            Facet instance for the requested state
        """
        pass
    
    @property
    def session_id(self) -> Optional[str]:
        """Get the current session ID."""
        return self._session_id
    
    @property
    def instance_id(self) -> Optional[str]:
        """Get the current instance ID."""
        return self._instance_id
    
    @property
    def step_count(self) -> int:
        """Get the current step count."""
        return self._step_count
    
    def _increment_step(self) -> None:
        """Increment the step counter."""
        self._step_count += 1
    
    def _reset_step_count(self) -> None:
        """Reset the step counter."""
        self._step_count = 0
    
    def _register_facet(self, uri: str, facet: Facet) -> None:
        """Register a facet for this environment."""
        self._facets[uri] = facet
    
    def _get_facet(self, uri: str) -> Optional[Facet]:
        """Get a registered facet."""
        return self._facets.get(uri)


class RemoteEnvironment(Environment):
    """Environment that connects to a remote Fleet API."""
    
    def __init__(self, config: EnvironmentConfig, instance_response: Optional[InstanceResponse] = None, instance_id: Optional[str] = None):
        super().__init__(config)
        
        # Create Fleet config from environment config
        self._fleet_config = FleetConfig(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        
        # Initialize API client
        self._client = FleetAPIClient(self._fleet_config)
        
        # Set instance details
        if instance_response:
            self._instance_response = instance_response
            self._instance_id = instance_response.instance_id
        else:
            self._instance_id = instance_id
            self._instance_response = None
        
        # Initialize manager client (will be set when instance URLs are available)
        self._manager_client: Optional[FleetManagerClient] = None
        
    async def reset(
        self,
        seed: Optional[int] = None,
        timestamp: Optional[Union[str, datetime]] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> None:
        """Reset the environment state.
        
        Args:
            seed: Integer seed for deterministic RNG in the env (physics, action noise, etc.)
            timestamp: ISO8601 string or datetime for the "current time" the sim should use
            options: Any additional flags the env impl supports (e.g. viewport size, login creds, feature flags)
        """
        raise NotImplementedError("reset() is not implemented yet.")
    
    async def step(self, action: Dict[str, Any]) -> Tuple[Dict[str, Any], float, bool]:
        """Execute one step in the environment."""
        if not self._instance_id:
            raise FleetEnvironmentError("Environment not initialized. Call reset() first.")
        
        try:
            # Increment step count
            self._increment_step()
            
            # Execute action through instance manager API
            # This is a placeholder - actual implementation depends on the manager API spec
            state, reward, done = await self._execute_action(action)
            
            return state, reward, done
            
        except Exception as e:
            raise FleetEnvironmentError(f"Failed to execute step: {e}")
    
    async def close(self) -> None:
        """Close the environment and clean up resources."""
        try:
            # Delete instance if it exists
            if self._instance_id:
                try:
                    await self._client.delete_instance(self._instance_id)
                    logger.info(f"Deleted instance: {self._instance_id}")
                except FleetAPIError as e:
                    logger.warning(f"Failed to delete instance: {e}")
                finally:
                    self._instance_id = None
                    self._instance_response = None
            
            # Close manager client
            if self._manager_client:
                await self._manager_client.close()
                self._manager_client = None
            
            # Close API client
            await self._client.close()
            
        except Exception as e:
            logger.error(f"Error closing environment: {e}")
    
    def state(self, facet_uri: str) -> Facet:
        """Get a facet for accessing environment state."""
        # Check if facet is already registered
        facet = self._get_facet(facet_uri)
        if facet:
            return facet
        
        # Create new facet based on URI
        from ..facets.factory import create_facet
        facet = create_facet(facet_uri, self)
        self._register_facet(facet_uri, facet)
        return facet
    
    async def manager_health_check(self) -> Optional[ManagerHealthResponse]:
        """Check the health of the manager API.
        
        Returns:
            ManagerHealthResponse if manager is available, None otherwise
        """
        await self._ensure_manager_client()
        if not self._manager_client:
            return None
        
        try:
            return await self._manager_client.health_check()
        except Exception as e:
            logger.warning(f"Manager health check failed: {e}")
            return None
    
    async def _ensure_manager_client(self) -> None:
        """Ensure manager client is initialized if instance URLs are available."""
        if self._manager_client is not None:
            return
        
        # Need instance response to get manager URLs
        if not self._instance_response and self._instance_id:
            try:
                self._instance_response = await self._client.get_instance(self._instance_id)
            except Exception as e:
                logger.warning(f"Failed to get instance details for manager client: {e}")
                return
        
        if self._instance_response and self._instance_response.urls.manager:
            manager_base_url = self._instance_response.urls.manager.api
            self._manager_client = FleetManagerClient(manager_base_url)
            logger.debug(f"Initialized manager client for {manager_base_url}")
    
    async def _wait_for_instance_ready(self, timeout: float = 300.0) -> None:
        """Wait for instance to be ready.
        
        Args:
            timeout: Maximum time to wait in seconds
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                instance = await self._client.get_instance(self._instance_id)
                self._instance_response = instance
                
                if instance.status == "running":
                    logger.info(f"Instance {self._instance_id} is ready")
                    return
                    
                elif instance.status == "error":
                    raise FleetEnvironmentError(f"Instance {self._instance_id} failed to start")
                    
                # Wait before checking again
                await asyncio.sleep(5)
                
            except FleetAPIError as e:
                if time.time() - start_time >= timeout:
                    raise FleetEnvironmentError(f"Timeout waiting for instance to be ready: {e}")
                await asyncio.sleep(5)
        
        raise FleetEnvironmentError(f"Timeout waiting for instance {self._instance_id} to be ready")
    
    async def _execute_action(self, action: Dict[str, Any]) -> Tuple[Dict[str, Any], float, bool]:
        """Execute an action through the instance manager API.
        
        This is a placeholder implementation that should be extended based on
        the actual manager API specification.
        
        Args:
            action: The action to execute as a dictionary
            
        Returns:
            Tuple of (state, reward, done)
        """
        # Ensure manager client is available
        await self._ensure_manager_client()
        
        # TODO: In the future, this would use the manager API to execute actions
        # For example: await self._manager_client.log_action(action)
        # For now, return placeholder values
        
        # Create a placeholder state
        state = self._create_state_from_action(action)
        
        # Create a placeholder reward
        reward = 0.0
        
        # Determine if episode is done (placeholder logic)
        done = self._step_count >= 100  # Example: done after 100 steps
        
        return state, reward, done
    
    def _create_state_from_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Create state based on executed action."""
        return {
            "instance_id": self._instance_id,
            "step": self._step_count,
            "last_action": action,
            "timestamp": time.time(),
            "status": "running"
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close() 