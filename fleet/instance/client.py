"""Fleet SDK Instance Client."""

from typing import Any, Callable, Dict, List, Optional, Tuple
import httpx
import inspect
import time
import logging
from urllib.parse import urlparse

from ..resources.sqlite import SQLiteResource
from ..resources.browser import BrowserResource
from ..resources.base import Resource

from ..verifiers import DatabaseSnapshot

from ..exceptions import FleetEnvironmentError, FleetAPIError

from .base import SyncWrapper
from .models import (
    ResetRequest,
    ResetResponse,
    Resource as ResourceModel,
    ResourceType,
    HealthResponse,
    ExecuteFunctionRequest,
    ExecuteFunctionResponse,
)


logger = logging.getLogger(__name__)


RESOURCE_TYPES = {
    ResourceType.db: SQLiteResource,
    ResourceType.cdp: BrowserResource,
}

ValidatorType = Callable[
    [DatabaseSnapshot, DatabaseSnapshot, Optional[str]],
    int,
]


class InstanceClient:
    def __init__(
        self,
        url: str,
        httpx_client: Optional[httpx.Client] = None,
    ):
        self.base_url = url
        self.client = SyncWrapper(
            url=self.base_url,
            httpx_client=httpx_client or httpx.Client(timeout=60.0),
        )
        self._resources: Optional[List[ResourceModel]] = None
        self._resources_state: Dict[str, Dict[str, Resource]] = {
            resource_type.value: {} for resource_type in ResourceType
        }

    def load(self) -> None:
        self._load_resources()

    def reset(
        self, reset_request: Optional[ResetRequest] = None
    ) -> ResetResponse:
        response = self.client.request(
            "POST", "/reset", json=reset_request.model_dump() if reset_request else None
        )
        return ResetResponse(**response.json())

    def state(self, uri: str) -> Resource:
        url = urlparse(uri)
        return self._resources_state[url.scheme][url.netloc]

    def db(self, name: str) -> SQLiteResource:
        """
        Returns an SQLite database resource for the given database name.

        Args:
            name: The name of the SQLite database to return

        Returns:
            An SQLite database resource for the given database name
        """
        return SQLiteResource(
            self._resources_state[ResourceType.db.value][name], self.client
        )

    def browser(self, name: str) -> BrowserResource:
        return BrowserResource(
            self._resources_state[ResourceType.cdp.value][name], self.client
        )

    def resources(self) -> List[Resource]:
        self._load_resources()
        return [
            resource
            for resources_by_name in self._resources_state.values()
            for resource in resources_by_name.values()
        ]

    def verify(self, validator: ValidatorType) -> ExecuteFunctionResponse:
        function_code = inspect.getsource(validator)
        function_name = validator.__name__
        return self.verify_raw(function_code, function_name)

    def verify_raw(
        self, function_code: str, function_name: str
    ) -> ExecuteFunctionResponse:
        response = self.client.request(
            "POST",
            "/execute_verifier_function",
            json=ExecuteFunctionRequest(
                function_code=function_code,
                function_name=function_name,
            ).model_dump(),
        )
        return ExecuteFunctionResponse(**response.json())

    def _load_resources(self) -> None:
        if self._resources is None:
            response = self.client.request("GET", "/resources")
            if response.status_code != 200:
                self._resources = []
                return

            # Handle both old and new response formats
            response_data = response.json()
            if isinstance(response_data, dict) and "resources" in response_data:
                # Old format: {"resources": [...]}
                resources_list = response_data["resources"]
            else:
                # New format: [...]
                resources_list = response_data

            self._resources = [ResourceModel(**resource) for resource in resources_list]
            for resource in self._resources:
                if resource.type not in self._resources_state:
                    self._resources_state[resource.type.value] = {}
                self._resources_state[resource.type.value][resource.name] = (
                    RESOURCE_TYPES[resource.type](resource, self.client)
                )

    def step(self, action: Dict[str, Any]) -> Tuple[Dict[str, Any], float, bool]:
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
            state, reward, done = self._execute_action(action)

            return state, reward, done

        except Exception as e:
            raise FleetEnvironmentError(f"Failed to execute step: {e}")

    def close(self) -> None:
        """Close the environment and clean up resources."""
        try:
            # Delete instance if it exists
            if self._instance_id:
                try:
                    self._client.delete_instance(self._instance_id)
                    logger.info(f"Deleted instance: {self._instance_id}")
                except FleetAPIError as e:
                    logger.warning(f"Failed to delete instance: {e}")
                finally:
                    self._instance_id = None
                    self._instance_response = None

            # Close manager client
            if self._manager_client:
                self._manager_client.close()
                self._manager_client = None

            # Close API client
            self._client.close()

        except Exception as e:
            logger.error(f"Error closing environment: {e}")

    def manager_health_check(self) -> Optional[HealthResponse]:
        response = self.client.request("GET", "/health")
        return HealthResponse(**response.json())

    def _wait_for_instance_ready(self, timeout: float = 300.0) -> None:
        """Wait for instance to be ready.

        Args:
            timeout: Maximum time to wait in seconds
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                instance = self._client.get_instance(self._instance_id)
                self._instance_response = instance

                if instance.status == "running":
                    logger.info(f"Instance {self._instance_id} is ready")
                    return

                elif instance.status == "error":
                    raise FleetEnvironmentError(
                        f"Instance {self._instance_id} failed to start"
                    )

                # Wait before checking again
                time.sleep(5)

            except FleetAPIError as e:
                if time.time() - start_time >= timeout:
                    raise FleetEnvironmentError(
                        f"Timeout waiting for instance to be ready: {e}"
                    )
                time.sleep(5)

        raise FleetEnvironmentError(
            f"Timeout waiting for instance {self._instance_id} to be ready"
        )

    def _execute_action(
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
        self._ensure_manager_client()

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

    def __enter__(self):
        """Async context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        self.close()