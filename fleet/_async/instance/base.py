import httpx
import httpx_retries

from fleet.runner_auth import RUNNER_TOKEN_HEADER
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
    def __init__(self, *, url: str, runner_token_provider=None):
        self.url = url
        # Optional so an InstanceClient built directly -- which callers do, and
        # the tests do -- keeps working with no token and no control-plane call.
        self.runner_token_provider = runner_token_provider

    def get_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "X-Fleet-SDK-Language": "Python",
            "X-Fleet-SDK-Version": "1.0.0",
        }
        return headers

    async def _headers_with_runner_token(self) -> Dict[str, str]:
        """SDK headers plus X-Runner-Token, when one is available.

        Async all the way down: httpx.AsyncClient would not accept a coroutine
        here, and resolving the token needs a network call the first time.
        """
        headers = self.get_headers()
        if self.runner_token_provider is None:
            return headers
        token = await self.runner_token_provider.token_async()
        if token:
            headers[RUNNER_TOKEN_HEADER] = token
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
            headers=await self._headers_with_runner_token(),
            params=params,
            json=json,
            **kwargs,
        )
