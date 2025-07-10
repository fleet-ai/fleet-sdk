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

from .base import EnvironmentBase, SyncWrapper
from .models import InstanceRequest, InstanceRecord, Environment as EnvironmentModel

from .instance import (
    InstanceClient,
    ResetRequest,
    ResetResponse,
    ValidatorType,
    ExecuteFunctionResponse,
)
from .resources.base import Resource
from .resources.sqlite import SQLiteResource
from .resources.browser import BrowserResource

logger = logging.getLogger(__name__)


class Environment(EnvironmentBase):
    def __init__(self, httpx_client: Optional[httpx.Client] = None, **kwargs):
        super().__init__(**kwargs)
        self._httpx_client = httpx_client or httpx.Client(timeout=60.0)
        self._instance: Optional[InstanceClient] = None

    @property
    def instance(self) -> InstanceClient:
        if self._instance is None:
            self._instance = InstanceClient(self.manager_url, self._httpx_client)
        return self._instance

    def reset(
        self, seed: Optional[int] = None, timestamp: Optional[int] = None
    ) -> ResetResponse:
        return self.instance.reset(ResetRequest(seed=seed, timestamp=timestamp))

    def db(self, name: str = "current") -> SQLiteResource:
        return self.instance.db(name)

    def browser(self, name: str = "cdp") -> BrowserResource:
        return self.instance.browser(name)

    def state(self, uri: str) -> Resource:
        return self.instance.state(uri)

    def resources(self) -> List[Resource]:
        return self.instance.resources()

    def close(self) -> InstanceRecord:
        return Fleet().delete(self.instance_id)

    def verify(self, validator: ValidatorType) -> ExecuteFunctionResponse:
        return self.instance.verify(validator)

    def verify_raw(
        self, function_code: str, function_name: str
    ) -> ExecuteFunctionResponse:
        return self.instance.verify_raw(function_code, function_name)


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

    def list_envs(self) -> List[EnvironmentModel]:
        response = self.client.request("GET", "/v1/env/")
        return [EnvironmentModel(**env_data) for env_data in response.json()]

    def environment(self, env_key: str) -> EnvironmentModel:
        response = self.client.request("GET", f"/v1/env/{env_key}")
        return EnvironmentModel(**response.json())

    def make(self, env_key: str) -> Environment:
        if ":" in env_key:
            env_key_part, version = env_key.split(":", 1)
            if not version.startswith("v"):
                version = f"v{version}"
        else:
            env_key_part = env_key
            version = None

        request = InstanceRequest(env_key=env_key_part, version=version)
        response = self.client.request(
            "POST", "/v1/env/instances", json=request.model_dump()
        )
        return Environment(**response.json())

    def instances(self, status: Optional[str] = None) -> List[Environment]:
        params = {}
        if status:
            params["status"] = status

        response = self.client.request("GET", "/v1/env/instances", params=params)
        return [Environment(**instance_data) for instance_data in response.json()]

    def instance(self, instance_id: str) -> Environment:
        response = self.client.request("GET", f"/v1/env/instances/{instance_id}")
        return Environment(**response.json())

    def delete(self, instance_id: str) -> InstanceRecord:
        response = self.client.request("DELETE", f"/v1/env/instances/{instance_id}")
        return InstanceRecord(**response.json())