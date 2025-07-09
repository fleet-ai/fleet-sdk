"""Fleet SDK Base Environment Classes."""

from typing import Any, Dict, List, Optional, Tuple
import asyncio
import httpx
import time
import logging
from urllib.parse import urlparse

from ..resources.sqlite import AsyncSQLiteResource
from ..resources.browser import AsyncBrowserResource
from ..resources.base import Resource

from ..exceptions import FleetEnvironmentError, FleetAPIError

from .base import SyncWrapper, AsyncWrapper
from .models import ResetResponse, Resource as ResourceModel, ResourceType


logger = logging.getLogger(__name__)


RESOURCE_TYPES = {
    ResourceType.sqlite: AsyncSQLiteResource,
    ResourceType.cdp: AsyncBrowserResource,
}


class Environment:
    def __init__(
        self,
        url: str,
        httpx_client: Optional[httpx.Client] = None,
    ):
        self.base_url = url
        self.client = SyncWrapper(
            url=self.base_url, httpx_client=httpx_client or httpx.Client()
        )
        raise NotImplementedError("SyncManager is not implemented")

    def reset(self) -> ResetResponse:
        response = self.client.request("POST", "/reset")
        return ResetResponse(**response.json())


class AsyncEnvironment:
    def __init__(
        self,
        url: str,
        httpx_client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = url
        self.client = AsyncWrapper(
            url=self.base_url, httpx_client=httpx_client or httpx.AsyncClient()
        )
        self._resources: Optional[List[ResourceModel]] = None
        self._resources_state: Dict[str, Dict[str, Resource]] = {
            resource_type.value: {} for resource_type in ResourceType
        }

    async def load(self) -> None:
        await self._load_resources()

    @property
    def env_key(self) -> Optional[str]:
        """Get the environment key from instance response or config."""
        if self._instance_response:
            return self._instance_response.env_key
        return self.config.environment_type

    @property
    def region(self) -> Optional[str]:
        """Get the region from instance response."""
        if self._instance_response:
            return self._instance_response.region
        return self.config.metadata.get("region")

    @property
    def status(self) -> Optional[str]:
        """Get the current instance status."""
        if self._instance_response:
            return self._instance_response.status
        return None

    @property
    def subdomain(self) -> Optional[str]:
        """Get the instance subdomain."""
        if self._instance_response:
            return self._instance_response.subdomain
        return None

    async def reset(self) -> ResetResponse:
        response = await self.client.request("POST", "/reset")
        return ResetResponse(**response.json())

    def state(self, uri: str) -> Resource:
        url = urlparse(uri)
        return self._resources_state[url.scheme][url.netloc]

    def sqlite(self, name: str) -> AsyncSQLiteResource:
        return AsyncSQLiteResource(
            self._resources_state[ResourceType.sqlite.value][name], self.client
        )

    def browser(self, name: str) -> AsyncBrowserResource:
        return AsyncBrowserResource(
            self._resources_state[ResourceType.cdp.value][name], self.client
        )

    async def resources(self) -> List[ResourceModel]:
        await self._load_resources()
        return self._resources

    async def _load_resources(self) -> None:
        if self._resources is None:
            response = await self.client.request("GET", "/resources")
            self._resources = [
                ResourceModel(**resource) for resource in response.json()["resources"]
            ]
            for resource in self._resources:
                if resource.type not in self._resources_state:
                    self._resources_state[resource.type.value] = {}
                self._resources_state[resource.type.value][resource.name] = (
                    RESOURCE_TYPES[resource.type](resource, self.client)
                )

    async def step(self, action: Dict[str, Any]) -> Tuple[Dict[str, Any], float, bool]:
        """Execute one step in the environment."""
        if not self._instance_id:
            raise FleetEnvironmentError(
                "Environment not initialized. Call reset() first."
            )

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

    # async def manager_health_check(self) -> Optional[ManagerHealthResponse]:
    #     """Check the health of the manager API.

    #     Returns:
    #         ManagerHealthResponse if manager is available, None otherwise
    #     """
    #     await self._ensure_manager_client()
    #     if not self._manager_client:
    #         return None

    #     try:
    #         return await self._manager_client.health_check()
    #     except Exception as e:
    #         logger.warning(f"Manager health check failed: {e}")
    #         return None

    # async def _ensure_manager_client(self) -> None:
    #     """Ensure manager client is initialized if instance URLs are available."""
    #     if self._manager_client is not None:
    #         return

    #     # Need instance response to get manager URLs
    #     if not self._instance_response and self._instance_id:
    #         try:
    #             self._instance_response = await self._client.get_instance(
    #                 self._instance_id
    #             )
    #         except Exception as e:
    #             logger.warning(
    #                 f"Failed to get instance details for manager client: {e}"
    #             )
    #             return

    #     if self._instance_response and self._instance_response.urls.manager:
    #         manager_base_url = self._instance_response.urls.manager.api
    #         self._manager_client = FleetManagerClient(manager_base_url)
    #         logger.debug(f"Initialized manager client for {manager_base_url}")

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
                    raise FleetEnvironmentError(
                        f"Instance {self._instance_id} failed to start"
                    )

                # Wait before checking again
                await asyncio.sleep(5)

            except FleetAPIError as e:
                if time.time() - start_time >= timeout:
                    raise FleetEnvironmentError(
                        f"Timeout waiting for instance to be ready: {e}"
                    )
                await asyncio.sleep(5)

        raise FleetEnvironmentError(
            f"Timeout waiting for instance {self._instance_id} to be ready"
        )

    async def _execute_action(
        self, action: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], float, bool]:
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
            "status": "running",
        }

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
