import httpx
import httpx_retries

from fleet.runner_auth import RUNNER_TOKEN_HEADER
from typing import Dict, Any, Optional


def default_httpx_client(max_retries: int, timeout: float) -> httpx.Client:
    if max_retries <= 0:
        return httpx.Client(timeout=timeout)

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
        transport=httpx.HTTPTransport(retries=2), retry=policy
    )
    return httpx.Client(
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

    def _headers_with_runner_token(self) -> Dict[str, str]:
        """SDK headers plus X-Runner-Token, when one is available.

        self.url already ends in the instance's /api/v1/env base, so every
        request this wrapper makes is a runner request -- there is no
        control-plane traffic here to scope away from.
        """
        headers = self.get_headers()
        if self.runner_token_provider is None:
            return headers
        token = self.runner_token_provider.token()
        if token:
            headers[RUNNER_TOKEN_HEADER] = token
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
            headers=self._headers_with_runner_token(),
            params=params,
            json=json,
            **kwargs,
        )
