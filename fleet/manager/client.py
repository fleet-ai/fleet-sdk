import httpx
from typing import Optional, List, Dict, Any
from abc import ABC, abstractmethod
from urllib.parse import urlparse

from .base import SyncWrapper, AsyncWrapper
from .models import ResetResponse, Resource as ResourceModel, ResourceType
from .facets import AsyncSQLiteResource, AsyncBrowserResource
from ..facets.base import Resource


class Manager:
    def __init__(self, url: str, httpx_client: Optional[httpx.Client] = None):
        self.base_url = url
        self.client = SyncWrapper(
            url=self.base_url, httpx_client=httpx_client or httpx.Client()
        )

    def reset(self) -> ResetResponse:
        response = self.client.request("POST", "/reset")
        return ResetResponse(**response.json())


class AsyncManager:
    def __init__(self, url: str, httpx_client: Optional[httpx.AsyncClient] = None):
        self.base_url = url
        self.client = AsyncWrapper(
            url=self.base_url, httpx_client=httpx_client or httpx.AsyncClient()
        )
        self._resources: Optional[List[ResourceModel]] = None
        self._resources_state: Dict[ResourceType, Dict[str, Resource]] = {
            resource_type: {} for resource_type in ResourceType
        }

    async def __aenter__(self):
        await self._load_resources()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None

    async def reset(self) -> ResetResponse:
        response = await self.client.request("POST", "/reset")
        return ResetResponse(**response.json())

    def state(self, uri: str) -> Resource:
        url = urlparse(uri)
        return self._resources_state[url.scheme][url.netloc]

    def sqlite(self, name: str) -> AsyncSQLiteResource:
        return AsyncSQLiteResource(
            self._resources_state[ResourceType.sqlite][name], self.client
        )

    def cdp(self, name: str) -> AsyncBrowserResource:
        return AsyncBrowserResource(
            self._resources_state[ResourceType.cdp][name], self.client
        )

    def resources(self) -> List[ResourceModel]:
        return self._resources

    async def _load_resources(self) -> None:
        if self._resources is None:
            response = await self.client.request("GET", "/resources")
            self._resources = [
                ResourceModel(**resource) for resource in response.json()["resources"]
            ]
            for resource in self._resources:
                if resource.type not in self._resources_state:
                    self._resources_state[resource.type] = {}
                self._resources_state[resource.type][resource.name] = Resource(resource)
