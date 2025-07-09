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

import asyncio
import os
import httpx
import logging
from typing import Optional, List

from .base import InstanceBase, AsyncWrapper, SyncWrapper
from .models import InstanceRequest, InstanceRecord, Environment as EnvironmentModel

from .env import Environment, AsyncEnvironment, ResetRequest, ResetResponse
from .resources.base import Resource
from .resources.sqlite import AsyncSQLiteResource
from .resources.browser import AsyncBrowserResource

logger = logging.getLogger(__name__)


class Instance(InstanceBase):
    def __init__(self, httpx_client: Optional[httpx.Client] = None, **kwargs):
        super().__init__(**kwargs)
        self._httpx_client = httpx_client or httpx.Client()
        self._env: Optional[Environment] = None

    @property
    def env(self) -> Environment:
        if self._env is None:
            self._env = Environment(self.manager_url, self._httpx_client)
        return self._env


class AsyncInstance(InstanceBase):
    def __init__(self, httpx_client: Optional[httpx.AsyncClient] = None, **kwargs):
        super().__init__(**kwargs)
        self._httpx_client = httpx_client or httpx.AsyncClient()
        self._env: Optional[AsyncEnvironment] = None

    @property
    def env(self) -> AsyncEnvironment:
        if self._env is None:
            self._env = AsyncEnvironment(self.manager_url, self._httpx_client)
        return self._env

    async def reset(
        self, seed: Optional[int] = None, timestamp: Optional[int] = None
    ) -> ResetResponse:
        return await self.env.reset(ResetRequest(seed=seed, timestamp=timestamp))

    def db(self, name: str = "current") -> AsyncSQLiteResource:
        return self.env.db(name)

    def browser(self, name: str = "cdp") -> AsyncBrowserResource:
        return self.env.browser(name)

    def state(self, uri: str) -> Resource:
        return self.env.state(uri)


class Fleet:
    def __init__(
        self,
        api_key: Optional[str] = os.getenv("FLEET_API_KEY"),
        base_url: Optional[str] = None,
        httpx_client: Optional[httpx.Client] = None,
    ):
        self._httpx_client = httpx_client or httpx.Client(timeout=60.0)
        self.client = SyncWrapper(
            api_key=api_key,
            base_url=base_url,
            httpx_client=self._httpx_client,
        )

    def environments(self) -> List[EnvironmentModel]:
        response = self.client.request("GET", "/v1/env/")
        return [EnvironmentModel(**env_data) for env_data in response.json()]

    def environment(self, env_key: str) -> EnvironmentModel:
        response = self.client.request("GET", f"/v1/env/{env_key}")
        return EnvironmentModel(**response.json())

    def make(self, request: InstanceRequest) -> Instance:
        response = self.client.request(
            "POST", "/v1/env/instances", json=request.model_dump()
        )
        return Instance(**response.json())

    def instances(self, status: Optional[str] = None) -> List[Instance]:
        params = {}
        if status:
            params["status"] = status

        response = self.client.request("GET", "/v1/env/instances", params=params)
        return [Instance(**instance_data) for instance_data in response.json()]

    def instance(self, instance_id: str) -> Instance:
        response = self.client.request("GET", f"/v1/env/instances/{instance_id}")
        return Instance(**response.json())

    def delete(self, instance_id: str) -> InstanceRecord:
        response = self.client.request("DELETE", f"/v1/env/instances/{instance_id}")
        return InstanceRecord(**response.json())


class AsyncFleet:
    def __init__(
        self,
        api_key: Optional[str] = os.getenv("FLEET_API_KEY"),
        base_url: Optional[str] = None,
        httpx_client: Optional[httpx.AsyncClient] = None,
    ):
        self._httpx_client = httpx_client or httpx.AsyncClient(timeout=60.0)
        self.client = AsyncWrapper(
            api_key=api_key,
            base_url=base_url,
            httpx_client=self._httpx_client,
        )

    async def list_envs(self) -> List[EnvironmentModel]:
        response = await self.client.request("GET", "/v1/env/")
        return [EnvironmentModel(**env_data) for env_data in response.json()]

    async def environment(self, env_key: str) -> EnvironmentModel:
        response = await self.client.request("GET", f"/v1/env/{env_key}")
        return EnvironmentModel(**response.json())

    async def make(self, env_key: str) -> AsyncInstance:
        if ":" in env_key:
            env_key_part, version = env_key.split(":", 1)
            if not version.startswith("v"):
                version = f"v{version}"
        else:
            env_key_part = env_key
            version = None

        request = InstanceRequest(env_key=env_key_part, version=version)
        response = await self.client.request(
            "POST", "/v1/env/instances", json=request.model_dump()
        )
        instance = AsyncInstance(**response.json())
        await instance.env.load()
        return instance

    async def instances(self, status: Optional[str] = None) -> List[AsyncInstance]:
        params = {}
        if status:
            params["status"] = status

        response = await self.client.request("GET", "/v1/env/instances", params=params)
        instances = [
            AsyncInstance(**instance_data) for instance_data in response.json()
        ]
        await asyncio.gather(*[instance.env.load() for instance in instances])
        return instances

    async def instance(self, instance_id: str) -> AsyncInstance:
        response = await self.client.request("GET", f"/v1/env/instances/{instance_id}")
        instance = AsyncInstance(**response.json())
        await instance.env.load()
        return instance

    async def delete(self, instance_id: str) -> InstanceRecord:
        response = await self.client.request(
            "DELETE", f"/v1/env/instances/{instance_id}"
        )
        return InstanceRecord(**response.json())
