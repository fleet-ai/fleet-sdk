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
import json
import logging
import os
from typing import List, Optional, Dict, TYPE_CHECKING

from .base import EnvironmentBase, AsyncWrapper
from ..models import (
    InstanceRequest,
    InstanceResponse,
    Environment as EnvironmentModel,
    VerifiersCheckResponse,
    VerifiersExecuteResponse,
    TaskListResponse,
    AccountResponse,
    TaskRequest,
)
from .tasks import Task
from ..verifiers.parse import extract_function_name, convert_new_to_old_verifier

if TYPE_CHECKING:
    from .verifiers import AsyncVerifierFunction

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
from ..resources.mcp import MCPResource

logger = logging.getLogger(__name__)


class AsyncEnv(EnvironmentBase):
    def __init__(self, client: Optional[AsyncWrapper], **kwargs):
        super().__init__(**kwargs)
        self._client = client
        self._apps: Dict[str, AsyncInstanceClient] = {}
        self._instance: Optional[AsyncInstanceClient] = None

    @property
    def instance(self) -> AsyncInstanceClient:
        if self._instance is None:
            self._instance = AsyncInstanceClient(
                self.manager_url, self._client.httpx_client if self._client else None
            )
        return self._instance
    
    def app(self, name: str) -> AsyncInstanceClient:
        if name not in self._apps:
            # Extract base URL by removing the current app path (e.g., /sentry/api/v1/env)
            # manager_url looks like: https://xxx.fleetai.com/sentry/api/v1/env
            base_url = self.manager_url.split('/api/v1/env')[0]
            # Remove the current app name (e.g., /sentry) to get the root
            if '/' in base_url:
                parts = base_url.rsplit('/', 1)
                if len(parts) == 2 and parts[0] != "https:/":
                    base_url = parts[0]
            
            self._apps[name] = AsyncInstanceClient(
                f"{base_url}/{name}/api/v1/env",
                self._client.httpx_client if self._client else None,
            )
        return self._apps[name]

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

    @property
    def mcp(self) -> MCPResource:
        mcp_url = f"{self.urls.root}mcp"
        return MCPResource(url=mcp_url, env_key=self.env_key)

    def state(self, uri: str) -> Resource:
        return self.instance.state(uri)

    async def resources(self) -> List[Resource]:
        return await self.instance.resources()

    async def close(self) -> InstanceResponse:
        return await _delete_instance(self._load_client, self.instance_id)

    async def verify(self, validator: ValidatorType) -> ExecuteFunctionResponse:
        return await self.instance.verify(validator)

    async def verify_raw(
        self, function_code: str, function_name: str | None = None
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
        args_array: list,
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
            args_array,
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
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        httpx_client: Optional[httpx.AsyncClient] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        if api_key is None:
            api_key = os.getenv("FLEET_API_KEY")
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
            if not version.startswith("v") and len(version) != 0 and version[0].isdigit():
                version = f"v{version}"
        else:
            env_key_part = env_key
            version = None

        request = InstanceRequest(env_key=env_key_part, version=version, region=region, created_from="sdk")
        region_base_url = REGION_BASE_URL.get(region)
        response = await self.client.request(
            "POST",
            "/v1/env/instances",
            json=request.model_dump(exclude_none=True),
            base_url=region_base_url,
        )

        instance = AsyncEnv(client=self.client, **response.json())
        await instance.instance.load()
        return instance

    async def make_for_task(self, task: Task) -> AsyncEnv:
        return await self.make(env_key=f"{task.env_id}:{task.version}")

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

    async def delete(self, instance_id: str) -> InstanceResponse:
        return await _delete_instance(self.client, instance_id)

    async def load_tasks_from_file(self, filename: str) -> List[Task]:
        with open(filename, 'r', encoding='utf-8') as f:
            tasks_data = f.read()

        return self.load_task_array_from_string(tasks_data)

    async def load_task_array_from_string(self, serialized_tasks: List[Dict]) -> List[Task]:
        tasks = []

        json_tasks = json.loads(serialized_tasks)
        for json_task in json_tasks:
            parsed_task = self.load_task_from_json(json_task)
            tasks.append(parsed_task)
        return tasks

    async def load_task_from_string(self, task_string: str) -> Task:
        task_json = json.loads(task_string)
        return self.load_task_from_json(task_json)

    async def load_task_from_json(self, task_json: Dict) -> Task:
        try:
            if 'verifier_id' in task_json and task_json['verifier_id']:
                verifier = self._create_verifier_from_data(
                    verifier_id=task_json['verifier_id'],
                    verifier_key=task_json['key'],
                    verifier_code=task_json['verifier_func'],
                    verifier_sha=task_json.get('verifier_sha', '')
                )
        except Exception as e:
            logger.warning(f"Failed to create verifier {task_json['key']}: {e}")
        
        task = Task(
            key=task_json['key'],
            prompt=task_json['prompt'],
            env_id=task_json['env_id'],  # Use env_id from the data
            created_at=task_json['created_at'],
            version=task_json.get('version'),
            env_variables=task_json.get('env_variables', {}),
            verifier_func=task_json.get('verifier_func'),  # Set verifier code
            verifier=verifier,  # Use created verifier or None
            metadata=task_json.get('metadata', {})  # Default empty metadata
        )
        return task

    async def load_tasks(self, env_key: Optional[str] = None) -> List[Task]:
        """Load tasks for the authenticated team, optionally filtered by environment.
        
        Args:
            env_key: Optional environment key to filter tasks by
            
        Returns:
            List[Task] containing Task objects
        """
        params = {}
        if env_key is not None:
            params["env_key"] = env_key
            
        response = await self.client.request("GET", "/v1/tasks", params=params)
        task_list_response = TaskListResponse(**response.json())
        
        # Transform TaskResponse objects to Task objects
        tasks = []
        for task_response in task_list_response.tasks:
            # Create verifier function if verifier data is present
            verifier = None
            verifier_func = task_response.verifier_func
            
            if task_response.verifier:
                embedded_code = task_response.verifier.code or ""
                is_embedded_error = embedded_code.strip().startswith("<error loading code:")
                if not is_embedded_error:
                    # Only override if the embedded code looks valid
                    verifier_func = embedded_code
                    # Create VerifierFunction from the embedded data
                    try:
                        verifier = await self._create_verifier_from_data(
                            verifier_id=task_response.verifier.verifier_id,
                            verifier_key=task_response.verifier.key,
                            verifier_code=embedded_code,
                            verifier_sha=task_response.verifier.sha256
                        )
                    except Exception as e:
                        logger.warning(f"Failed to create verifier {task_response.verifier.key}: {e}")
                else:
                    # Fallback: try fetching by ID if embedded code failed to load
                    try:
                        logger.warning(
                            f"Embedded verifier code missing for {task_response.verifier.key} (NoSuchKey). "
                            f"Attempting to refetch by id {task_response.verifier.verifier_id}"
                        )
                        verifier = await self._load_verifier(task_response.verifier.verifier_id)
                    except Exception as e:
                        logger.warning(
                            f"Refetch by verifier id failed for {task_response.verifier.key}: {e}. "
                            "Leaving verifier unset."
                        )
            
            task = Task(
                key=task_response.key,
                prompt=task_response.prompt,
                env_id=task_response.environment_id,  # Map environment_id -> env_id
                created_at=task_response.created_at,
                version=task_response.version,
                env_variables=task_response.env_variables or {},
                verifier_func=verifier_func,  # Set verifier code
                verifier=verifier,  # Use created verifier or None
                metadata={}  # Default empty metadata
            )
            tasks.append(task)
        
        return tasks

    async def export_tasks(self, env_key: Optional[str] = None, filename: Optional[str] = None):
        """Export tasks for the authenticated team, optionally filtered by environment.
        
        Args:
            env_key: Optional environment key to filter tasks by
            filename: Optional filename to write tasks to. If not provided, defaults to 'tasks.json' or 'tasks_{env_key}.json'
            
        Returns:
            str: Path to the exported file if tasks were written, None if no tasks found
        """
        tasks = await self.load_tasks(env_key)
        if tasks:
            # Generate filename if not provided
            if filename is None:
                if env_key:
                    filename = f"tasks_{env_key}.json"
                else:
                    filename = "tasks.json"
            
            # Convert tasks to serializable format
            tasks_data = []
            for task in tasks:
                task_dict = task.model_dump()
                # Remove non-serializable verifier object, keep verifier_func (code string)
                if 'verifier' in task_dict:
                    task_dict.pop('verifier')
                tasks_data.append(task_dict)
            
            # Write to JSON file
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, indent=2, default=str)
            
            logger.info(f"Exported {len(tasks)} tasks to {filename}")
            return filename
        else:
            logger.info("No tasks found to export")
            return None
            
    async def import_tasks(self, filename: str):
        """Import tasks from a JSON file.
        
        Args:
            filename: Path to the JSON file of Task objects to import
            
        Returns:
            List[Task] containing imported Task objects
        """
        with open(filename, 'r', encoding='utf-8') as f:
            tasks_data = json.load(f)
            
        # Create tasks from the loaded data
        tasks = []
        for task_data in tasks_data:
            task = Task(**task_data)
            tasks.append(task)

        for task in tasks:
            payload = TaskRequest(
                key=task.key,
                prompt=task.prompt,
                environment_id=task.env_id,
                verifier_func=task.verifier_func,
                version=task.version or None,
                env_variables=task.env_variables or {},
            )
            try:
                response = await self.client.request("POST", "/v1/tasks", json=payload.model_dump())
            except Exception as e:
                logger.error(f"Failed to import task {task.key}: {e}")
                continue


    async def account(self) -> AccountResponse:
        """Get account information including instance limits and usage.

        Returns:
            AccountResponse containing team_id, team_name, instance_limit, and instance_count
        """
        response = await self.client.request("GET", "/v1/account")
        return AccountResponse(**response.json())
    
    async def _create_verifier_from_data(
        self, 
        verifier_id: str,
        verifier_key: str,
        verifier_code: str,
        verifier_sha: str
    ) -> "AsyncVerifierFunction":
        """Create an AsyncVerifierFunction from verifier data.
        
        Args:
            verifier_id: The verifier ID
            verifier_key: The verifier key
            verifier_code: The verifier code
            verifier_sha: The verifier SHA256
            
        Returns:
            AsyncVerifierFunction created from the verifier code
        """
        from .verifiers.verifier import AsyncVerifierFunction
        
        # Check if this is a new format verifier (has before/after parameters)
        if 'before: DatabaseSnapshot' in verifier_code and 'after: DatabaseSnapshot' in verifier_code:
            # Convert new format to old format
            verifier_code = convert_new_to_old_verifier(verifier_code)
            # Update function name since wrapper adds _wrapper suffix
            original_name = extract_function_name(verifier_code.split('\n')[0])
            if original_name and original_name.endswith('_wrapper'):
                function_name = original_name
            else:
                function_name = extract_function_name(verifier_code)
        else:
            # Extract function name from code
            function_name = extract_function_name(verifier_code)
        
        if not function_name:
            raise ValueError(f"Could not extract function name from verifier {verifier_id}")
        
        # Create a function object from the code
        # Import necessary classes for the namespace
        from ..verifiers.db import IgnoreConfig, DatabaseSnapshot
        
        # Create a namespace for the function
        namespace = {
            '__builtins__': __builtins__,
            'Environment': object,  # Placeholder, will be provided at runtime
            'IgnoreConfig': IgnoreConfig,
            'DatabaseSnapshot': DatabaseSnapshot,
            'TASK_FAILED_SCORE': 0,
            'TASK_SUCCESSFUL_SCORE': 1,
        }
        
        # Execute the code to define the function
        exec(verifier_code, namespace)
        
        # Get the function object
        if function_name not in namespace:
            raise ValueError(f"Function {function_name} not found in verifier code")
        
        func = namespace[function_name]
        
        # Create and return AsyncVerifierFunction with SHA if available
        # Since the function was created via exec, we need to provide the raw code
        verifier_func = AsyncVerifierFunction(
            func=func,
            key=verifier_key,
            extra_requirements=[],
            verifier_id=verifier_id,
            sha256=verifier_sha,  # Pass SHA directly to constructor
            raw_code=verifier_code  # Provide raw code since func won't have extractable source
        )
        
        # Store the original verifier code for reference
        verifier_func._verifier_code = verifier_code
        
        return verifier_func
    
    async def _load_verifier(self, verifier_id: str) -> "AsyncVerifierFunction":
        """Load a verifier by ID and create an AsyncVerifierFunction.
        
        Args:
            verifier_id: The verifier ID to fetch
            
        Returns:
            AsyncVerifierFunction created from the verifier code
        """
        # Fetch verifier from API
        response = await self.client.request("GET", f"/v1/verifier/{verifier_id}")
        verifier_data = response.json()
        
        # Use the common method to create verifier
        return await self._create_verifier_from_data(
            verifier_id=verifier_id,
            verifier_key=verifier_data["key"],
            verifier_code=verifier_data["code"],
            verifier_sha=verifier_data.get("sha256", "")
        )


# Shared
async def _delete_instance(client: AsyncWrapper, instance_id: str) -> InstanceResponse:
    response = await client.request("DELETE", f"/v1/env/instances/{instance_id}")
    return InstanceResponse(**response.json())


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
    args_array: list,
    kwargs: dict,
    timeout: Optional[int] = 30,
    needs_upload: bool = True,
) -> VerifiersExecuteResponse:
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
        "args_array": args_array,
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
