"""Async API Resource for making HTTP requests to the app's API endpoint."""

from typing import Any, Dict, Optional
import httpx

from .base import Resource
from ...instance.models import Resource as ResourceModel


class AsyncAPIResponse:
    """Simple wrapper around httpx.Response with a requests-like interface."""

    def __init__(self, response: httpx.Response):
        self._response = response
        self.status_code: int = response.status_code
        self.headers: httpx.Headers = response.headers
        self.text: str = response.text
        self.content: bytes = response.content
        self.url: str = str(response.url)
        self.ok: bool = response.is_success

    def json(self) -> Any:
        """Parse response body as JSON."""
        return self._response.json()

    def raise_for_status(self) -> "AsyncAPIResponse":
        """Raise an HTTPStatusError if the response has an error status code."""
        self._response.raise_for_status()
        return self

    def __repr__(self) -> str:
        return f"<AsyncAPIResponse [{self.status_code}]>"


class AsyncAPIResource(Resource):
    """Async HTTP client for making requests to the app's API endpoint.

    Provides a requests-like interface for interacting with the app's REST API.

    Example:
        api = env.api()
        response = await api.get("/users/1")
        print(response.status_code)  # 200
        print(response.json())       # {"id": 1, "name": "John"}

        # With headers/auth
        response = await api.post(
            "/users",
            json={"name": "Jane"},
            headers={"Authorization": "Bearer xxx"}
        )
    """

    def __init__(
        self,
        resource: ResourceModel,
        base_url: str,
        client: Optional[httpx.AsyncClient] = None,
    ):
        super().__init__(resource)
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient()

    def _build_url(self, path: str) -> str:
        """Build full URL from base_url and path."""
        if path.startswith("/"):
            return f"{self.base_url}{path}"
        return f"{self.base_url}/{path}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Any] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> AsyncAPIResponse:
        """Make an HTTP request.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE, etc.)
            path: URL path (relative to base_url)
            params: Query parameters
            json: JSON body (will be serialized)
            data: Form data
            headers: Request headers
            cookies: Request cookies
            timeout: Request timeout in seconds
            **kwargs: Additional arguments passed to httpx

        Returns:
            AsyncAPIResponse with status_code, headers, text, content, json() method
        """
        url = self._build_url(path)
        response = await self._client.request(
            method,
            url,
            params=params,
            json=json,
            data=data,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            **kwargs,
        )
        return AsyncAPIResponse(response)

    async def get(
        self,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> AsyncAPIResponse:
        """Make a GET request."""
        return await self.request("GET", path, params=params, headers=headers, **kwargs)

    async def post(
        self,
        path: str,
        *,
        json: Optional[Any] = None,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> AsyncAPIResponse:
        """Make a POST request."""
        return await self.request(
            "POST", path, json=json, data=data, params=params, headers=headers, **kwargs
        )

    async def put(
        self,
        path: str,
        *,
        json: Optional[Any] = None,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> AsyncAPIResponse:
        """Make a PUT request."""
        return await self.request(
            "PUT", path, json=json, data=data, params=params, headers=headers, **kwargs
        )

    async def patch(
        self,
        path: str,
        *,
        json: Optional[Any] = None,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> AsyncAPIResponse:
        """Make a PATCH request."""
        return await self.request(
            "PATCH", path, json=json, data=data, params=params, headers=headers, **kwargs
        )

    async def delete(
        self,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> AsyncAPIResponse:
        """Make a DELETE request."""
        return await self.request("DELETE", path, params=params, headers=headers, **kwargs)

    async def head(
        self,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> AsyncAPIResponse:
        """Make a HEAD request."""
        return await self.request("HEAD", path, params=params, headers=headers, **kwargs)

    async def options(
        self,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> AsyncAPIResponse:
        """Make an OPTIONS request."""
        return await self.request("OPTIONS", path, params=params, headers=headers, **kwargs)
