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

import os
import httpx
import logging
from typing import Optional, List

from .base import EnvironmentBase, AsyncWrapper
from .models import InstanceRequest, InstanceRecord, Environment as EnvironmentModel

from .instance import (
    AsyncInstanceClient,
    ResetRequest,
    ResetResponse,
    ValidatorType,
    ExecuteFunctionResponse,
)
from .config import DEFAULT_MAX_RETRIES
from .instance.base import default_httpx_client
from .resources.base import Resource
from .resources.sqlite import AsyncSQLiteResource
from .resources.browser import AsyncBrowserResource

logger = logging.getLogger(__name__)


class AsyncEnvironment(EnvironmentBase):
    def __init__(self, client: AsyncWrapper, **kwargs):
        super().__init__(**kwargs)
        self._client = client
        self._instance: Optional[AsyncInstanceClient] = None

    @property
    def instance(self) -> AsyncInstanceClient:
        if self._instance is None:
            self._instance = AsyncInstanceClient(
                self.manager_url, self._client.httpx_client
            )
        return self._instance

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
        response = await self._client.request(
            "DELETE", f"/v1/env/instances/{self.instance_id}"
        )
        return InstanceRecord(**response.json())

    async def verify(self, validator: ValidatorType) -> ExecuteFunctionResponse:
        return await self.instance.verify(validator)

    async def verify_raw(
        self, function_code: str, function_name: str
    ) -> ExecuteFunctionResponse:
        return await self.instance.verify_raw(function_code, function_name)


class AsyncFleet:
    def __init__(
        self,
        api_key: Optional[str] = os.getenv("FLEET_API_KEY"),
        base_url: Optional[str] = None,
        httpx_client: Optional[httpx.AsyncClient] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self._httpx_client = httpx_client or default_httpx_client(max_retries)
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
    ) -> AsyncEnvironment:
        if ":" in env_key:
            env_key_part, version = env_key.split(":", 1)
            if not version.startswith("v"):
                version = f"v{version}"
        else:
            env_key_part = env_key
            version = None

        request = InstanceRequest(env_key=env_key_part, version=version, region=region)
        response = await self.client.request(
            "POST", "/v1/env/instances", json=request.model_dump()
        )
        instance = AsyncEnvironment(client=self.client, **response.json())
        await instance.instance.load()
        return instance

    async def instances(
        self, status: Optional[str] = None, region: Optional[str] = None
    ) -> List[AsyncEnvironment]:
        params = {}
        if status:
            params["status"] = status
        if region:
            params["region"] = region

        response = await self.client.request("GET", "/v1/env/instances", params=params)
        return [
            AsyncEnvironment(client=self.client, **instance_data)
            for instance_data in response.json()
        ]

    async def instance(self, instance_id: str) -> AsyncEnvironment:
        response = await self.client.request("GET", f"/v1/env/instances/{instance_id}")
        instance = AsyncEnvironment(client=self.client, **response.json())
        await instance.instance.load()
        return instance

    async def delete(self, instance_id: str) -> InstanceRecord:
        response = await self.client.request(
            "DELETE", f"/v1/env/instances/{instance_id}"
        )
        return InstanceRecord(**response.json())
