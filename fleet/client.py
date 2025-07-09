import os
import httpx
import logging
from typing import Optional, List

from .base import InstanceBase, AsyncWrapper, SyncWrapper
from .models import InstanceRequest, InstanceRecord, Environment as EnvironmentModel

from .env import Environment, AsyncEnvironment

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

    def list_environments(self) -> List[EnvironmentModel]:
        response = self.client.request("GET", "/v1/env/")
        return [Environment(**env_data) for env_data in response.json()]

    def get_environment(self, env_key: str) -> EnvironmentModel:
        response = self.client.request("GET", f"/v1/env/{env_key}")
        return Environment(**response.json())

    def create_instance(self, request: InstanceRequest) -> Instance:
        response = self.client.request("POST", "/v1/env/instances", json=request.model_dump())
        return Instance(**response.json())

    def list_instances(self, status: Optional[str] = None) -> List[Instance]:
        params = {}
        if status:
            params["status"] = status

        response = self.client.request("GET", "/v1/env/instances", params=params)
        return [Instance(**instance_data) for instance_data in response.json()]

    def get_instance(self, instance_id: str) -> Instance:
        response = self.client.request("GET", f"/v1/env/instances/{instance_id}")
        return Instance(**response.json())

    def delete_instance(self, instance_id: str) -> InstanceRecord:
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

    async def environments(self) -> List[EnvironmentModel]:
        response = await self.client.request("GET", "/v1/env/")
        return [EnvironmentModel(**env_data) for env_data in response.json()]

    async def environment(self, env_key: str) -> EnvironmentModel:
        response = await self.client.request("GET", f"/v1/env/{env_key}")
        return EnvironmentModel(**response.json())

    async def make(self, request: InstanceRequest) -> AsyncInstance:
        response = await self.client.request(
            "POST", "/v1/env/instances", json=request.model_dump()
        )
        return AsyncInstance(**response.json())

    async def instances(self, status: Optional[str] = None) -> List[AsyncInstance]:
        params = {}
        if status:
            params["status"] = status

        response = await self.client.request("GET", "/v1/env/instances", params=params)
        return [AsyncInstance(**instance_data) for instance_data in response.json()]

    async def instance(self, instance_id: str) -> AsyncInstance:
        response = await self.client.request("GET", f"/v1/env/instances/{instance_id}")
        return AsyncInstance(**response.json())

    async def delete(self, instance_id: str) -> InstanceRecord:
        response = await self.client.request(
            "DELETE", f"/v1/env/instances/{instance_id}"
        )
        return InstanceRecord(**response.json())
