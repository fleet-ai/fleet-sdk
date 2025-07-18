"""Fleet SDK Instance Client."""

from typing import Any, Callable, Dict, List, Optional, Tuple
import asyncio
import httpx
import inspect
import time
import logging
from urllib.parse import urlparse

from ..resources.sqlite import AsyncSQLiteResource
from ..resources.browser import AsyncBrowserResource
from ..resources.base import Resource

from fleet.verifiers import DatabaseSnapshot

from ..exceptions import FleetEnvironmentError, FleetAPIError

from .base import AsyncWrapper
from .models import (
    ResetRequest,
    ResetResponse,
    Resource as ResourceModel,
    ResourceType,
    HealthResponse,
    ExecuteFunctionRequest,
    ExecuteFunctionResponse,
    ExecuteVerifierRemoteRequest,
    ExecuteVerifierRemoteResponse,
)


logger = logging.getLogger(__name__)


RESOURCE_TYPES = {
    ResourceType.db: AsyncSQLiteResource,
    ResourceType.cdp: AsyncBrowserResource,
}

ValidatorType = Callable[
    [DatabaseSnapshot, DatabaseSnapshot, Optional[str]],
    int,
]




class AsyncInstanceClient:
    def __init__(
        self,
        url: str,
        httpx_client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = url
        self.client = AsyncWrapper(
            url=self.base_url,
            httpx_client=httpx_client or httpx.AsyncClient(timeout=180.0),
        )
        self._resources: Optional[List[ResourceModel]] = None
        self._resources_state: Dict[str, Dict[str, Resource]] = {
            resource_type.value: {} for resource_type in ResourceType
        }

    async def load(self) -> None:
        await self._load_resources()

    async def reset(
        self, reset_request: Optional[ResetRequest] = None
    ) -> ResetResponse:
        response = await self.client.request(
            "POST", "/reset", json=reset_request.model_dump() if reset_request else None
        )
        return ResetResponse(**response.json())

    def state(self, uri: str) -> Resource:
        url = urlparse(uri)
        return self._resources_state[url.scheme][url.netloc]

    def db(self, name: str) -> AsyncSQLiteResource:
        """
        Returns an SQLite database resource for the given database name.

        Args:
            name: The name of the SQLite database to return

        Returns:
            An SQLite database resource for the given database name
        """
        return AsyncSQLiteResource(
            self._resources_state[ResourceType.db.value][name], self.client
        )

    def browser(self, name: str) -> AsyncBrowserResource:
        return AsyncBrowserResource(
            self._resources_state[ResourceType.cdp.value][name], self.client
        )

    async def resources(self) -> List[Resource]:
        await self._load_resources()
        return [
            resource
            for resources_by_name in self._resources_state.values()
            for resource in resources_by_name.values()
        ]

    async def verify(self, validator: ValidatorType) -> ExecuteFunctionResponse:
        function_code = inspect.getsource(validator)
        function_name = validator.__name__
        return await self.verify_raw(function_code, function_name)

    async def verify_raw(
        self, function_code: str, function_name: str
    ) -> ExecuteFunctionResponse:
        response = await self.client.request(
            "POST",
            "/execute_verifier_function",
            json=ExecuteFunctionRequest(
                function_code=function_code,
                function_name=function_name,
            ).model_dump(),
        )
        return ExecuteFunctionResponse(**response.json())



    async def _load_resources(self) -> None:
        if self._resources is None:
            response = await self.client.request("GET", "/resources")
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

    async def step(self, action: Dict[str, Any]) -> Tuple[Dict[str, Any], float, bool]:
        """Execute one step in the environment."""
        try:
            # Create a placeholder state
            state = {
                "action": action,
                "timestamp": time.time(),
                "status": "completed",
            }

            # Create a placeholder reward
            reward = 0.0

            # Determine if episode is done (placeholder logic)
            done = False

            return state, reward, done

        except Exception as e:
            raise FleetEnvironmentError(f"Failed to execute step: {e}")

    async def manager_health_check(self) -> Optional[HealthResponse]:
        response = await self.client.request("GET", "/health")
        return HealthResponse(**response.json())

    async def execute_verifier_remote(
        self, 
        bundle_data: bytes,
        args: tuple,
        kwargs: dict,
        timeout: Optional[int] = 30
    ) -> ExecuteVerifierRemoteResponse:
        """Execute a verifier function remotely using a bundle."""
        import base64
        
        # Convert bundle bytes to base64
        bundle_b64 = base64.b64encode(bundle_data).decode('utf-8')
        
        # Create request
        request = ExecuteVerifierRemoteRequest(
            bundle_data=bundle_b64,
            args=list(args),
            kwargs=kwargs,
            timeout=timeout,
            env_context={
                "instance_id": self.base_url,  # This will need to be improved
                "manager_url": self.base_url
            }
        )
        
        # Make API call
        response = await self.client.request(
            "POST",
            "/v1/verifiers/execute",
            json=request.model_dump()
        )
        
        return ExecuteVerifierRemoteResponse(**response.json())

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
