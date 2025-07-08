import httpx
from typing import Dict, Any, Optional

from .models import InstanceResponse


class InstanceBase(InstanceResponse):
    @property
    def manager_url(self) -> str:
        return f"{self.urls.manager.api}"


class BaseWrapper:
    def __init__(self, *, api_key: Optional[str], base_url: Optional[str]):
        if api_key is None:
            raise ValueError("api_key is required")
        self.api_key = api_key
        if base_url is None:
            base_url = "https://fleet.new"
        self.base_url = base_url

    def get_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "X-Fleet-SDK-Language": "Python",
            "X-Fleet-SDK-Version": "1.0.0",
        }
        headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class SyncWrapper(BaseWrapper):
    def __init__(self, *, httpx_client: httpx.Client, **kwargs):
        super().__init__(**kwargs)
        self.httpx_client = httpx_client

    def request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Any] = None,
        **kwargs,
    ) -> httpx.Response:
        return self.httpx_client.request(
            method,
            f"{self.base_url}{url}",
            headers=self.get_headers(),
            params=params,
            json=json,
            **kwargs,
        )


class AsyncWrapper(BaseWrapper):
    def __init__(self, *, httpx_client: httpx.AsyncClient, **kwargs):
        super().__init__(**kwargs)
        self.httpx_client = httpx_client

    async def request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Any] = None,
        **kwargs,
    ) -> httpx.Response:
        return await self.httpx_client.request(
            method,
            f"{self.base_url}{url}",
            headers=self.get_headers(),
            params=params,
            json=json,
            **kwargs,
        )
