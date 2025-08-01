import httpx
import httpx_retries
from typing import Dict, Any, Optional


def default_httpx_client(max_retries: int, timeout: float) -> httpx.AsyncClient:
    if max_retries <= 0:
        return httpx.AsyncClient(timeout=timeout)

    policy = httpx_retries.Retry(
        total=max_retries,
        status_forcelist=[
            404,
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=["GET", "POST", "PATCH", "DELETE"],
        backoff_factor=0.5,
    )
    retry = httpx_retries.RetryTransport(
        transport=httpx.AsyncHTTPTransport(retries=2), retry=policy
    )
    return httpx.AsyncClient(
        timeout=timeout,
        transport=retry,
    )


class BaseWrapper:
    def __init__(self, *, url: str):
        self.url = url

    def get_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "X-Fleet-SDK-Language": "Python",
            "X-Fleet-SDK-Version": "1.0.0",
        }
        return headers


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
