import httpx
from typing import Optional

from .base import SyncWrapper, AsyncWrapper
from .models import ResetResponse


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

    async def reset(self) -> ResetResponse:
        response = await self.client.request("POST", "/reset")
        print(response.json())
        return ResetResponse(**response.json())
