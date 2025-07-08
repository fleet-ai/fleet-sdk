import httpx
from typing import Dict, Any, Optional


class BaseWrapper:
    def __init__(self, *, url: str):
        self.url = url

    def get_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "X-Fleet-SDK-Language": "Python",
            "X-Fleet-SDK-Version": "1.0.0",
        }
        return headers


class SyncWrapper(BaseWrapper):
    def __init__(self, *, httpx_client: httpx.Client, **kwargs):
        super().__init__(**kwargs)
        self.httpx_client = httpx_client

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Any] = None,
        **kwargs,
    ) -> httpx.Response:
        return self.httpx_client.request(
            method,
            f"{self.url}{path}",
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
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Any] = None,
        **kwargs,
    ) -> httpx.Response:
        return await self.httpx_client.request(
            method,
            f"{self.url}{path}",
            headers=self.get_headers(),
            params=params,
            json=json,
            **kwargs,
        )
