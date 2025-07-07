# Copyright 2025 Fleet AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Fleet API Client for making HTTP requests to Fleet services."""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import aiohttp
from pydantic import BaseModel, Field

from .config import FleetConfig
from .exceptions import (
    FleetAPIError,
    FleetAuthenticationError,
    FleetRateLimitError,
    FleetTimeoutError,
    FleetError,
)


logger = logging.getLogger(__name__)


class InstanceRequest(BaseModel):
    """Request model for creating instances."""
    
    env_key: str = Field(..., description="Environment key to create instance for")
    version: Optional[str] = Field(None, description="Version of the environment")
    region: Optional[str] = Field("us-west-1", description="AWS region")
    seed: Optional[int] = Field(None, description="Random seed for deterministic behavior")
    timestamp: Optional[int] = Field(None, description="Timestamp for environment state")
    p_error: Optional[float] = Field(None, description="Error probability")
    avg_latency: Optional[float] = Field(None, description="Average latency")
    run_id: Optional[str] = Field(None, description="Run ID for tracking")
    task_id: Optional[str] = Field(None, description="Task ID for tracking")


class ManagerURLs(BaseModel):
    """Model for manager API URLs."""
    
    api: str = Field(..., description="Manager API URL")
    docs: str = Field(..., description="Manager docs URL")
    reset: str = Field(..., description="Reset URL")
    diff: str = Field(..., description="Diff URL")
    snapshot: str = Field(..., description="Snapshot URL")
    execute_verifier_function: str = Field(..., description="Execute verifier function URL")
    execute_verifier_function_with_upload: str = Field(..., description="Execute verifier function with upload URL")


class InstanceURLs(BaseModel):
    """Model for instance URLs."""
    
    root: str = Field(..., description="Root URL")
    app: str = Field(..., description="App URL")
    api: Optional[str] = Field(None, description="API URL")
    health: Optional[str] = Field(None, description="Health check URL")
    api_docs: Optional[str] = Field(None, description="API documentation URL")
    manager: ManagerURLs = Field(..., description="Manager API URLs")


class InstanceResponse(BaseModel):
    """Response model for instance operations."""
    
    instance_id: str = Field(..., description="Instance ID")
    env_key: str = Field(..., description="Environment key")
    version: str = Field(..., description="Environment version")
    status: str = Field(..., description="Instance status")
    subdomain: str = Field(..., description="Instance subdomain")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    terminated_at: Optional[str] = Field(None, description="Termination timestamp")
    team_id: str = Field(..., description="Team ID")
    region: str = Field(..., description="AWS region")
    urls: InstanceURLs = Field(..., description="Instance URLs")
    health: Optional[bool] = Field(None, description="Health status")


class EnvDetails(BaseModel):
    """Model for environment details and metadata."""
    
    env_key: str = Field(..., description="Environment key")
    name: str = Field(..., description="Environment name")
    description: Optional[str] = Field(..., description="Environment description")
    default_version: Optional[str] = Field(..., description="Default version")
    versions: Dict[str, str] = Field(..., description="Available versions")


class HealthResponse(BaseModel):
    """Response model for health checks."""
    
    status: str = Field(..., description="Health status")
    timestamp: str = Field(..., description="Timestamp")
    mode: str = Field(..., description="Operation mode")
    region: str = Field(..., description="AWS region")
    docker_status: str = Field(..., description="Docker status")
    docker_error: Optional[str] = Field(None, description="Docker error if any")
    instances: int = Field(..., description="Number of instances")
    regions: Optional[Dict[str, "HealthResponse"]] = Field(None, description="Regional health info")


class FleetAPIClient:
    """Client for making requests to the Fleet API."""
    
    def __init__(self, config: FleetConfig):
        """Initialize the Fleet API client.
        
        Args:
            config: Fleet configuration with API key and base URL
        """
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._base_url = config.base_url
        
    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
        
    async def _ensure_session(self):
        """Ensure HTTP session is created."""
        if self._session is None or self._session.closed:
            headers = {}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
                
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=timeout,
                connector=aiohttp.TCPConnector(limit=100),
            )
            
    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            
    async def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Make an HTTP request to the Fleet API.
        
        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            path: API endpoint path
            data: Request body data
            params: Query parameters
            headers: Additional headers
            timeout: Request timeout in seconds
            
        Returns:
            Response data as dictionary
            
        Raises:
            FleetAPIError: If the API returns an error
            FleetAuthenticationError: If authentication fails
            FleetRateLimitError: If rate limit is exceeded
            FleetTimeoutError: If request times out
        """
        await self._ensure_session()
        
        url = f"{self._base_url}{path}"
        request_headers = headers or {}
        
        try:
            logger.debug(f"Making {method} request to {url}")
            
            async with self._session.request(
                method=method,
                url=url,
                json=data,
                params=params,
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=timeout or 60),
            ) as response:
                response_data = await response.json() if response.content_type == "application/json" else {}
                
                if response.status == 200:
                    logger.debug(f"Request successful: {response.status}")
                    return response_data
                    
                elif response.status == 401:
                    raise FleetAuthenticationError("Authentication failed - check your API key")
                    
                elif response.status == 429:
                    raise FleetRateLimitError("Rate limit exceeded - please retry later")
                    
                else:
                    error_message = response_data.get("detail", f"API request failed with status {response.status}")
                    raise FleetAPIError(
                        error_message,
                        status_code=response.status,
                        response_data=response_data,
                    )
                    
        except asyncio.TimeoutError:
            raise FleetTimeoutError(f"Request to {url} timed out")
            
        except aiohttp.ClientError as e:
            raise FleetAPIError(f"HTTP client error: {e}")
            
    # Environment operations
    async def list_environments(self) -> List[EnvDetails]:
        """List all available environments.
        
        Returns:
            List of EnvDetails objects
        """
        response = await self._request("GET", "/v1/env/")
        return [EnvDetails(**env_data) for env_data in response]
        
    async def get_environment(self, env_key: str) -> EnvDetails:
        """Get details for a specific environment.
        
        Args:
            env_key: Environment key
            
        Returns:
            EnvDetails object
        """
        response = await self._request("GET", f"/v1/env/{env_key}")
        return EnvDetails(**response)
        
    # Instance operations
    async def create_instance(self, request: InstanceRequest) -> InstanceResponse:
        """Create a new environment instance.
        
        Args:
            request: Instance creation request
            
        Returns:
            InstanceResponse object
        """
        response = await self._request("POST", "/v1/env/instances", data=request.model_dump(exclude_none=True))
        return InstanceResponse(**response)
        
    async def list_instances(self, status: Optional[str] = None) -> List[InstanceResponse]:
        """List all instances, optionally filtered by status.
        
        Args:
            status: Optional status filter (pending, running, stopped, error)
            
        Returns:
            List of InstanceResponse objects
        """
        params = {}
        if status:
            params["status"] = status
            
        response = await self._request("GET", "/v1/env/instances", params=params)
        return [InstanceResponse(**instance_data) for instance_data in response]
        
    async def get_instance(self, instance_id: str) -> InstanceResponse:
        """Get details for a specific instance.
        
        Args:
            instance_id: Instance ID
            
        Returns:
            InstanceResponse object
        """
        response = await self._request("GET", f"/v1/env/instances/{instance_id}")
        return InstanceResponse(**response)
        
    async def delete_instance(self, instance_id: str) -> Dict[str, Any]:
        """Delete an instance.
        
        Args:
            instance_id: Instance ID
            
        Returns:
            Deletion response data
        """
        response = await self._request("DELETE", f"/v1/env/instances/{instance_id}")
        return response
        
    # Health check operations
    async def health_check(self) -> HealthResponse:
        """Check the health of the Fleet API.
        
        Returns:
            HealthResponse object
        """
        response = await self._request("GET", "/health")
        return HealthResponse(**response)
        
    async def health_check_simple(self) -> HealthResponse:
        """Simple health check without authentication.
        
        Returns:
            HealthResponse object
        """
        response = await self._request("GET", "/health-check")
        return HealthResponse(**response) 