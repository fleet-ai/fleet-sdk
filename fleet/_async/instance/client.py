"""Fleet SDK Instance Client."""

from typing import Any, Callable, Dict, List, Optional, Tuple
import httpx
import inspect
import time
import logging
from urllib.parse import urlparse

from ..resources.sqlite import AsyncSQLiteResource
from ..resources.browser import AsyncBrowserResource
from ..resources.api import AsyncAPIResource
from ..resources.filesystem import AsyncFilesystemResource
from ..resources.base import Resource

from fleet.verifiers import DatabaseSnapshot
from fleet.verifiers.parse import convert_verifier_string, extract_function_name

from ..exceptions import FleetEnvironmentError
from ...config import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT

from .base import AsyncWrapper, default_httpx_client
from ...instance.models import (
    ResetRequest,
    ResetResponse,
    Resource as ResourceModel,
    ResourceType,
    ResourceMode,
    HealthResponse,
    ExecuteFunctionRequest,
    ExecuteFunctionResponse,
    FsDiffRequest,
    FsDiffResponse,
)


logger = logging.getLogger(__name__)


RESOURCE_TYPES = {
    ResourceType.db: AsyncSQLiteResource,
    ResourceType.cdp: AsyncBrowserResource,
    ResourceType.api: AsyncAPIResource,
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
            httpx_client=httpx_client
            or default_httpx_client(DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT),
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
        resource_info = self._resources_state[ResourceType.db.value][name]
        # Local mode - resource_info is a dict with creation parameters
        if isinstance(resource_info, dict) and resource_info.get('type') == 'local':
            # Create new instance each time (matching HTTP mode behavior)
            return AsyncSQLiteResource(
                resource_info['resource_model'],
                client=None,
                db_path=resource_info['db_path']
            )
        # HTTP mode - resource_info is a ResourceModel, create new wrapper
        return AsyncSQLiteResource(resource_info, self.client)

    def browser(self, name: str) -> AsyncBrowserResource:
        return AsyncBrowserResource(
            self._resources_state[ResourceType.cdp.value][name], self.client
        )

    def fs(self) -> AsyncFilesystemResource:
        """Returns a filesystem diff resource for inspecting file changes.

        Returns:
            An AsyncFilesystemResource for querying filesystem diffs
        """
        resource_model = ResourceModel(
            name="fs",
            type=ResourceType.db,  # Reuse existing type; fs is not a registered resource type
            mode=ResourceMode.ro,
        )
        return AsyncFilesystemResource(resource_model, self.client)

    def api(self, name: str, base_url: str) -> AsyncAPIResource:
        """
        Returns an API resource for making HTTP requests.

        Args:
            name: The name of the API resource
            base_url: The base URL for API requests

        Returns:
            An AsyncAPIResource for making HTTP requests
        """
        # Create a minimal resource model for API
        resource_model = ResourceModel(
            name=name,
            type=ResourceType.api,
            mode=ResourceMode.rw,
        )
        return AsyncAPIResource(
            resource_model,
            base_url=base_url,
            client=self.client.httpx_client if self.client else None,
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
        self, function_code: str, function_name: Optional[str] = None
    ) -> ExecuteFunctionResponse:
        try:
            function_code = convert_verifier_string(function_code)
        except:
            pass

        if function_name is None:
            function_name = extract_function_name(function_code)

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
                response_body = response.text[:500] if response.text else "empty"
                self._resources = []  # Mark as loaded (empty) to prevent retries
                raise FleetEnvironmentError(
                    f"Failed to load instance resources: status_code={response.status_code} "
                    f"(url={self.base_url}, response={response_body})"
                )

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
                if resource.type.value not in self._resources_state:
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

    def close(self):
        """Close anchor connections for in-memory databases."""
        if hasattr(self, '_memory_anchors'):
            for conn in self._memory_anchors.values():
                conn.close()
            self._memory_anchors.clear()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        self.close()
