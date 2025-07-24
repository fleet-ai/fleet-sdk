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

import base64
import cloudpickle
import httpx
import logging
import os
from typing import List, Optional

from .base import EnvironmentBase, AsyncWrapper
from ..models import (
    InstanceRequest,
    InstanceRecord,
    Environment as EnvironmentModel,
    VerifiersCheckResponse,
    VerificationResponse,
    VerifiersExecuteResponse,
)

from .instance import (
    AsyncInstanceClient,
    ResetRequest,
    ResetResponse,
    ExecuteFunctionResponse,
)
from ..config import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT, REGION_BASE_URL
from .instance.base import default_httpx_client
from .instance.client import ValidatorType
from .resources.base import Resource
from .resources.sqlite import AsyncSQLiteResource
from .resources.browser import AsyncBrowserResource

logger = logging.getLogger(__name__)


class AsyncEnv(EnvironmentBase):
    def __init__(self, client: Optional[AsyncWrapper], **kwargs):
        super().__init__(**kwargs)
        self._client = client
        self._instance: Optional[AsyncInstanceClient] = None

    @property
    def instance(self) -> AsyncInstanceClient:
        if self._instance is None:
            self._instance = AsyncInstanceClient(
                self.manager_url, self._client.httpx_client if self._client else None
            )
        return self._instance

    @property
    def _load_client(self) -> AsyncWrapper:
        if self._client is None:
            raise ValueError("Client not initialized")
        return self._client

    async def reset(
        self, seed: Optional[int] = None, timestamp: Optional[int] = None
    ) -> ResetResponse:
        return await self.instance.reset(ResetRequest(seed=seed, timestamp=timestamp))

    def db(self, name: str = "current") -> AsyncSQLiteResource:
        return self.instance.db(name)

    def browser(self, name: str = "cdp") -> AsyncBrowserResource:
        return self.instance.browser(name)

    def state(self, uri: str) -> Resource:
        return self.instance.state(uri)

    async def resources(self) -> List[Resource]:
        return await self.instance.resources()

    async def close(self) -> InstanceRecord:
        return await _delete_instance(self._load_client, self.instance_id)

    async def verify(self, validator: ValidatorType) -> ExecuteFunctionResponse:
        return await self.instance.verify(validator)

    async def verify_raw(
        self, function_code: str, function_name: str
    ) -> ExecuteFunctionResponse:
        return await self.instance.verify_raw(function_code, function_name)

    async def check_bundle_exists(self, bundle_hash: str) -> VerifiersCheckResponse:
        return await _check_bundle_exists(self._load_client, bundle_hash)

    async def execute_verifier_remote(
        self, 
        bundle_data: bytes, 
        bundle_sha: str,
        key: str,
        function_name: str,
        args: tuple, 
        kwargs: dict, 
        timeout: Optional[int] = 30,
        needs_upload: bool = True,
    ) -> VerifiersExecuteResponse:
        return await _execute_verifier_remote(
            self._load_client, 
            bundle_data, 
            bundle_sha,
            key,
            function_name,
            args, 
            kwargs, 
            timeout,
            needs_upload
        )

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("_client", None)
        state.pop("_instance", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)


class AsyncFleet:
    def __init__(
        self,
        api_key: Optional[str] = os.getenv("FLEET_API_KEY"),
        base_url: Optional[str] = None,
        httpx_client: Optional[httpx.AsyncClient] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._httpx_client = httpx_client or default_httpx_client(max_retries, timeout)
        self.client = AsyncWrapper(
            api_key=api_key,
            base_url=base_url,
            httpx_client=self._httpx_client,
        )

    async def list_envs(self) -> List[EnvironmentModel]:
        response = await self.client.request("GET", "/v1/env/")
        return [EnvironmentModel(**env_data) for env_data in response.json()]

    async def list_regions(self) -> List[str]:
        response = await self.client.request("GET", "/v1/regions")
        return response.json()

    async def environment(self, env_key: str) -> EnvironmentModel:
        response = await self.client.request("GET", f"/v1/env/{env_key}")
        return EnvironmentModel(**response.json())

    async def make(
        self, env_key: str, region: Optional[str] = None
    ) -> AsyncEnv:
        if ":" in env_key:
            env_key_part, version = env_key.split(":", 1)
            if not version.startswith("v"):
                version = f"v{version}"
        else:
            env_key_part = env_key
            version = None

        request = InstanceRequest(env_key=env_key_part, version=version, region=region)
        region_base_url = REGION_BASE_URL.get(region)
        response = await self.client.request(
            "POST",
            "/v1/env/instances",
            json=request.model_dump(),
            base_url=region_base_url,
        )
        instance = AsyncEnv(client=self.client, **response.json())
        await instance.instance.load()
        return instance

    async def instances(
        self, status: Optional[str] = None, region: Optional[str] = None
    ) -> List[AsyncEnv]:
        params = {}
        if status:
            params["status"] = status
        if region:
            params["region"] = region

        response = await self.client.request("GET", "/v1/env/instances", params=params)
        return [
            AsyncEnv(client=self.client, **instance_data)
            for instance_data in response.json()
        ]

    async def instance(self, instance_id: str) -> AsyncEnv:
        response = await self.client.request("GET", f"/v1/env/instances/{instance_id}")
        instance = AsyncEnv(client=self.client, **response.json())
        await instance.instance.load()
        return instance

    async def check_bundle_exists(self, bundle_hash: str) -> VerifiersCheckResponse:
        return await _check_bundle_exists(self.client, bundle_hash)

    async def execute_verifier_remote(
        self, bundle_data: bytes, args: tuple, kwargs: dict, timeout: Optional[int] = 30
    ) -> VerifiersExecuteResponse:
        return await _execute_verifier_remote(
            self.client, bundle_data, args, kwargs, timeout
        )

    async def delete(self, instance_id: str) -> InstanceRecord:
        return await _delete_instance(self.client, instance_id)


# Shared
async def _delete_instance(client: AsyncWrapper, instance_id: str) -> InstanceRecord:
    response = await client.request("DELETE", f"/v1/env/instances/{instance_id}")
    return InstanceRecord(**response.json())


async def _check_bundle_exists(
    client: AsyncWrapper, bundle_hash: str
) -> VerifiersCheckResponse:
    response = await client.request("GET", f"/v1/verifiers/check?sha256={bundle_hash}")
    return VerifiersCheckResponse(**response.json())


async def _execute_verifier_remote(
    client: AsyncWrapper,
    bundle_data: bytes,
    bundle_sha: str,
    key: str,
    function_name: str,
    args: tuple,
    kwargs: dict,
    timeout: Optional[int] = 30,
    needs_upload: bool = True,
) -> VerificationResponse:
    # Pickle args and kwargs together
    # The first arg should be None as a placeholder for env
    args_with_none = (None,) + args
    args_kwargs_pickled = cloudpickle.dumps({"args": args_with_none, "kwargs": kwargs})
    args_kwargs_b64 = base64.b64encode(args_kwargs_pickled).decode("utf-8")

    # Build request data
    request_data = {
        "key": key,
        "sha256": bundle_sha,
        "args": args_kwargs_b64,
        "function_name": function_name,
        "timeout": timeout,
        "region": "us-west-1",  # TODO: make configurable
    }
    
    # Add bundle data only if upload is needed
    if needs_upload:
        bundle_b64 = base64.b64encode(bundle_data).decode("utf-8")
        request_data["bundle"] = bundle_b64
    
    # Debug logging
    logger.debug(f"Sending verifier execute request: key={key}, sha256={bundle_sha[:8]}..., function_name={function_name}")
    logger.debug(f"Request has bundle: {needs_upload}")
    logger.debug(f"Using client with base_url: {client.base_url}")
    logger.debug(f"Request data keys: {list(request_data.keys())}")
    logger.debug(f"Bundle size: {len(request_data.get('bundle', ''))} chars" if 'bundle' in request_data else "No bundle")

    # Note: This should be called on the instance URL, not the orchestrator
    # The instance has manager URLs for verifier execution
    response = await client.request("POST", "/v1/verifiers/execute", json=request_data)
    
    # Debug the response
    response_json = response.json()
    logger.debug(f"Verifier execute response: {response_json}")

    return VerifiersExecuteResponse(**response_json)
