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
from fleet.verifiers.parse import convert_verifier_string, extract_function_name

from ..exceptions import FleetEnvironmentError
from ..config import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT

from .base import SyncWrapper, default_httpx_client
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
            httpx_client=httpx_client
            or default_httpx_client(DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT),
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
        self, function_code: str, function_name: str | None = None
    ) -> ExecuteFunctionResponse:
        try:
            function_code = convert_verifier_string(function_code)
        except:
            pass

        if function_name is None:
            function_name = extract_function_name(function_code)

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
            logger.debug(f"Loading resources from {self.base_url}/resources")
            start_time = time.time()
            
            try:
                response = self.client.request("GET", "/resources")
                load_duration = time.time() - start_time
                
                if response.status_code != 200:
                    logger.warning(f"Resource loading failed with status {response.status_code}, setting empty resources list")
                    self._resources = []
                    return

                # Handle both old and new response formats
                try:
                    response_data = response.json()
                    logger.debug(f"Resource loading response received in {load_duration:.2f}s")
                    
                    if isinstance(response_data, dict) and "resources" in response_data:
                        # Old format: {"resources": [...]}
                        resources_list = response_data["resources"]
                        logger.debug(f"Using old response format, found {len(resources_list)} resources")
                    else:
                        # New format: [...]
                        resources_list = response_data
                        if isinstance(resources_list, list):
                            logger.debug(f"Using new response format, found {len(resources_list)} resources")
                        else:
                            logger.warning(f"Unexpected response format: {type(resources_list)}")
                            
                except Exception as e:
                    logger.error(f"Failed to parse resources response as JSON: {e}")
                    logger.error(f"Raw response text: {response.text}")
                    raise

                self._resources = [ResourceModel(**resource) for resource in resources_list]
                logger.debug(f"Successfully parsed {len(self._resources)} resource models")
                
                for resource in self._resources:
                    if resource.type.value not in self._resources_state:
                        self._resources_state[resource.type.value] = {}
                    self._resources_state[resource.type.value][resource.name] = (
                        RESOURCE_TYPES[resource.type](resource, self.client)
                    )
                    logger.debug(f"Initialized resource: {resource.type.value}/{resource.name}")
                    
                total_duration = time.time() - start_time
                logger.info(f"Resource loading completed in {total_duration:.2f}s, loaded {len(self._resources)} resources")
                
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Resource loading failed after {duration:.2f}s: {type(e).__name__}: {e}")
                raise

    def step(self, action: Dict[str, Any]) -> Tuple[Dict[str, Any], float, bool]:
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

    def manager_health_check(self) -> Optional[HealthResponse]:
        response = self.client.request("GET", "/health")
        return HealthResponse(**response.json())

    def __enter__(self):
        """Async context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        self.close()
