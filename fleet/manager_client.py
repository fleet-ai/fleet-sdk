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

"""Fleet Manager API Client for per-instance environment management."""

import asyncio
import logging
from typing import Any, Dict, Optional
import aiohttp
from pydantic import BaseModel, Field

from .exceptions import (
    FleetAPIError,
    FleetTimeoutError,
    FleetError,
)

logger = logging.getLogger(__name__)


class ManagerHealthResponse(BaseModel):
    """Response model for manager health checks."""
    
    status: str = Field(..., description="Health status")
    timestamp: str = Field(..., description="Timestamp")
    service: str = Field(..., description="Service name")


class TimestampResponse(BaseModel):
    """Response model for timestamp endpoint."""
    
    timestamp: str = Field(..., description="Current timestamp")


class FleetManagerClient:
    """Client for interacting with Fleet Manager APIs on individual instances."""
    
    def __init__(self, base_url: str):
        """Initialize the manager client.
        
        Args:
            base_url: Base URL for the manager API (e.g., https://instanceid.fleetai.com)
        """
        self._base_url = base_url.rstrip('/')
        self._session: Optional[aiohttp.ClientSession] = None
    
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
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(limit=10),
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
        """Make an HTTP request to the Manager API.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API endpoint path
            data: Request body data
            params: Query parameters
            headers: Additional headers
            timeout: Request timeout in seconds
            
        Returns:
            Response data as dictionary
            
        Raises:
            FleetAPIError: If the API returns an error
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
                timeout=aiohttp.ClientTimeout(total=timeout or 30),
            ) as response:
                response_data = await response.json() if response.content_type == "application/json" else {}
                
                if response.status == 200:
                    logger.debug(f"Manager API request successful: {response.status}")
                    return response_data
                else:
                    error_message = response_data.get("detail", f"Manager API request failed with status {response.status}")
                    raise FleetAPIError(
                        error_message,
                        status_code=response.status,
                        response_data=response_data,
                    )
                    
        except asyncio.TimeoutError:
            raise FleetTimeoutError(f"Request to {url} timed out")
            
        except aiohttp.ClientError as e:
            raise FleetAPIError(f"HTTP client error: {e}")
    
    # Health check operations
    async def health_check(self) -> ManagerHealthResponse:
        """Check the health of the manager API.
        
        Returns:
            ManagerHealthResponse object
        """
        response = await self._request("GET", "/health")
        return ManagerHealthResponse(**response)
    
    async def get_timestamp(self) -> TimestampResponse:
        """Get current timestamp from the manager.
        
        Returns:
            TimestampResponse object
        """
        response = await self._request("GET", "/timestamp")
        return TimestampResponse(**response)
    
    async def test_path(self) -> Dict[str, Any]:
        """Test endpoint to verify path configuration.
        
        Returns:
            Test response data
        """
        response = await self._request("GET", "/test-path")
        return response
    
    # Future endpoints can be added here as needed:
    # - log_action()
    # - reset_database()
    # - create_snapshots()
    # - generate_diff()
    # - execute_verifier_function()
    # etc. 