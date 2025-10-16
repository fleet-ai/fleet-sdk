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
import concurrent.futures
import httpx
import json
import logging
import os
from typing import List, Optional, Dict, Any, TYPE_CHECKING

from .base import EnvironmentBase, SyncWrapper
from .models import (
    InstanceRequest,
    InstanceResponse,
    Environment as EnvironmentModel,
    VerifiersCheckResponse,
    VerifiersExecuteResponse,
    TaskListResponse,
    AccountResponse,
    TaskRequest,
    TaskResponse,
    TaskUpdateRequest,
)
from .tasks import Task

if TYPE_CHECKING:
    from .verifiers import SyncVerifierFunction

from .instance import (
    InstanceClient,
    ResetRequest,
    ResetResponse,
    ExecuteFunctionResponse,
)
from .config import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    REGION_BASE_URL,
    GLOBAL_BASE_URL,
)
from .instance.base import default_httpx_client
from .instance.client import ValidatorType
from .resources.base import Resource
from .resources.sqlite import SQLiteResource
from .resources.browser import BrowserResource
from .resources.mcp import SyncMCPResource

logger = logging.getLogger(__name__)


class SyncEnv(EnvironmentBase):
    def __init__(self, client: Optional[SyncWrapper], **kwargs):
        super().__init__(**kwargs)
        self._client = client
        self._apps: Dict[str, InstanceClient] = {}
        self._instance: Optional[InstanceClient] = None

    @property
    def instance(self) -> InstanceClient:
        if self._instance is None:
            self._instance = InstanceClient(
                self.manager_url, self._client.httpx_client if self._client else None
            )
        return self._instance

    def app(self, name: str) -> InstanceClient:
        if name not in self._apps:
            # Extract base URL by removing the current app path (e.g., /sentry/api/v1/env)
            # manager_url looks like: https://xxx.fleetai.com/sentry/api/v1/env
            base_url = self.manager_url.split("/api/v1/env")[0]
            # Remove the current app name (e.g., /sentry) to get the root
            if "/" in base_url:
                parts = base_url.rsplit("/", 1)
                if len(parts) == 2 and parts[0] != "https:/":
                    base_url = parts[0]

            self._apps[name] = InstanceClient(
                f"{base_url}/{name}/api/v1/env",
                self._client.httpx_client if self._client else None,
            )
        return self._apps[name]

    @property
    def _load_client(self) -> SyncWrapper:
        if self._client is None:
            raise ValueError("Client not initialized")
        return self._client

    def reset(
        self, seed: Optional[int] = None, timestamp: Optional[int] = None
    ) -> ResetResponse:
        return self.instance.reset(ResetRequest(seed=seed, timestamp=timestamp))

    def db(self, name: str = "current") -> SQLiteResource:
        return self.instance.db(name)

    def browser(self, name: str = "cdp") -> BrowserResource:
        return self.instance.browser(name)

    @property
    def mcp(self) -> SyncMCPResource:
        mcp_url = f"{self.urls.root}mcp"
        return SyncMCPResource(url=mcp_url, env_key=self.env_key)

    def state(self, uri: str) -> Resource:
        return self.instance.state(uri)

    def resources(self) -> List[Resource]:
        return self.instance.resources()

    def close(self) -> InstanceResponse:
        return _delete_instance(self._load_client, self.instance_id)

    def verify(self, validator: ValidatorType) -> ExecuteFunctionResponse:
        return self.instance.verify(validator)

    def verify_raw(
        self, function_code: str, function_name: Optional[str] = None
    ) -> ExecuteFunctionResponse:
        return self.instance.verify_raw(function_code, function_name)

    def check_bundle_exists(self, bundle_hash: str) -> VerifiersCheckResponse:
        return _check_bundle_exists(self._load_client, bundle_hash)

    def execute_verifier_remote(
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
        return _execute_verifier_remote(
            self._load_client,
            bundle_data,
            bundle_sha,
            key,
            function_name,
            args,
            args_array,
            kwargs,
            timeout,
            needs_upload,
        )

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("_client", None)
        state.pop("_instance", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)


class Fleet:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        httpx_client: Optional[httpx.Client] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        if api_key is None:
            api_key = os.getenv("FLEET_API_KEY")
        if base_url is None:
            base_url = os.getenv("FLEET_BASE_URL")
        self._httpx_client = httpx_client or default_httpx_client(max_retries, timeout)
        self.client = SyncWrapper(
            api_key=api_key,
            base_url=base_url,
            httpx_client=self._httpx_client,
        )

    def list_envs(self) -> List[EnvironmentModel]:
        response = self.client.request("GET", "/v1/env/")
        return [EnvironmentModel(**env_data) for env_data in response.json()]

    def list_regions(self) -> List[str]:
        response = self.client.request("GET", "/v1/regions")
        return response.json()

    def environment(self, env_key: str) -> EnvironmentModel:
        response = self.client.request("GET", f"/v1/env/{env_key}")
        return EnvironmentModel(**response.json())

    def make(
        self,
        env_key: str,
        data_key: Optional[str] = None,
        region: Optional[str] = None,
        env_variables: Optional[Dict[str, Any]] = None,
        image_type: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> SyncEnv:
        if ":" in env_key:
            env_key_part, env_version = env_key.split(":", 1)
            if (
                not env_version.startswith("v")
                and len(env_version) != 0
                and env_version[0].isdigit()
            ):
                env_version = f"v{env_version}"
        else:
            env_key_part = env_key
            env_version = None

        if data_key is not None and ":" in data_key:
            data_key_part, data_version = data_key.split(":", 1)
            if (
                not data_version.startswith("v")
                and len(data_version) != 0
                and data_version[0].isdigit()
            ):
                data_version = f"v{data_version}"
        else:
            data_key_part = data_key
            data_version = None

        request = InstanceRequest(
            env_key=env_key_part,
            env_version=env_version,
            data_key=data_key_part,
            data_version=data_version,
            region=region,
            env_variables=env_variables,
            image_type=image_type,
            created_from="sdk",
            ttl_seconds=ttl_seconds,
        )

        # Only use region-specific base URL if no custom base URL is set
        base_url = None
        if region and self.client.base_url == GLOBAL_BASE_URL:
            base_url = REGION_BASE_URL.get(region)

        response = self.client.request(
            "POST",
            "/v1/env/instances",
            json=request.model_dump(exclude_none=True),
            base_url=base_url,
        )

        instance = SyncEnv(client=self.client, **response.json())
        instance.instance.load()
        return instance

    def make_for_task(self, task: Task) -> SyncEnv:
        return self.make(env_key=f"{task.env_id}:{task.version}")

    def instances(
        self, status: Optional[str] = None, region: Optional[str] = None
    ) -> List[SyncEnv]:
        params = {}
        if status:
            params["status"] = status
        if region:
            params["region"] = region

        response = self.client.request("GET", "/v1/env/instances", params=params)
        return [
            SyncEnv(client=self.client, **instance_data)
            for instance_data in response.json()
        ]

    def instance(self, instance_id: str) -> SyncEnv:
        response = self.client.request("GET", f"/v1/env/instances/{instance_id}")
        instance = SyncEnv(client=self.client, **response.json())
        instance.instance.load()
        return instance

    def check_bundle_exists(self, bundle_hash: str) -> VerifiersCheckResponse:
        return _check_bundle_exists(self.client, bundle_hash)

    def execute_verifier_remote(
        self, bundle_data: bytes, args: tuple, kwargs: dict, timeout: Optional[int] = 30
    ) -> VerifiersExecuteResponse:
        return _execute_verifier_remote(self.client, bundle_data, args, kwargs, timeout)

    def delete(self, instance_id: str) -> InstanceResponse:
        return _delete_instance(self.client, instance_id)

    def load_tasks_from_file(self, filename: str) -> List[Task]:
        with open(filename, "r", encoding="utf-8") as f:
            tasks_data = f.read()

        return self.load_task_array_from_string(tasks_data)

    def load_task_array_from_string(self, serialized_tasks: str) -> List[Task]:
        tasks = []

        parsed_data = json.loads(serialized_tasks)
        if isinstance(parsed_data, list):
            json_tasks = parsed_data
        elif isinstance(parsed_data, dict) and "tasks" in parsed_data:
            json_tasks = parsed_data["tasks"]
        else:
            raise ValueError(
                "Invalid JSON structure: expected array or object with 'tasks' key"
            )

        for json_task in json_tasks:
            parsed_task = self.load_task_from_json(json_task)
            tasks.append(parsed_task)
        return tasks

    def load_task_from_string(self, task_string: str) -> Task:
        task_json = json.loads(task_string)
        return self.load_task_from_json(task_json)

    def load_task_from_json(
        self, task_json: Dict, raise_on_verifier_error: bool = False
    ) -> Task:
        verifier = None
        verifier_code = task_json.get("verifier_func") or task_json.get("verifier_code")
        verifier_sha = task_json.get("verifier_sha", "")

        # Check if verifier is a nested object with code inside
        if not verifier_code and "verifier" in task_json:
            verifier_obj = task_json["verifier"]
            if isinstance(verifier_obj, dict):
                verifier_code = verifier_obj.get("code")
                # Also extract sha256 from nested verifier if not found at top level
                if not verifier_sha:
                    verifier_sha = verifier_obj.get("sha256", "")

        # Try to find verifier_id in multiple locations
        verifier_id = task_json.get("verifier_id")
        
        # Check nested verifier object for verifier_id
        if not verifier_id and "verifier" in task_json:
            verifier_obj = task_json["verifier"]
            if isinstance(verifier_obj, dict):
                verifier_id = verifier_obj.get("verifier_id")
        
        if (
            not verifier_id
            and "metadata" in task_json
            and isinstance(task_json["metadata"], dict)
        ):
            verifier_metadata = task_json["metadata"].get("verifier", {})
            if isinstance(verifier_metadata, dict):
                verifier_id = verifier_metadata.get("verifier_id")

        # If no verifier_id found, use the task key/id as fallback
        if not verifier_id:
            verifier_id = task_json.get("key", task_json.get("id"))

        try:
            if verifier_id and verifier_code:
                verifier = self._create_verifier_from_data(
                    verifier_id=verifier_id,
                    verifier_key=task_json.get("key", task_json.get("id")),
                    verifier_code=verifier_code,
                    verifier_sha=verifier_sha,
                )
        except Exception as e:
            error_msg = f"Failed to create verifier {task_json.get('key', task_json.get('id'))}: {e}"
            if raise_on_verifier_error:
                raise ValueError(error_msg) from e
            else:
                logger.warning(error_msg)

        task = Task(
            key=task_json.get("key", task_json.get("id")),
            prompt=task_json["prompt"],
            env_id=task_json.get(
                "env_id", task_json.get("env_key")
            ),  # Use env_id or fallback to env_key
            created_at=task_json.get("created_at"),
            version=task_json.get("version"),
            data_id=task_json.get("data_id"),
            data_version=task_json.get("data_version"),
            env_variables=task_json.get("env_variables", {}),
            verifier_func=verifier_code,  # Set verifier code
            verifier=verifier,  # Use created verifier or None
            verifier_id=verifier_id,  # Set verifier_id so _rebuild_verifier works
            verifier_sha=verifier_sha,  # Set verifier_sha
            metadata=task_json.get("metadata", {}),  # Default empty metadata
            output_json_schema=task_json.get("output_json_schema"),  # JSON schema for output
        )
        return task

    def load_tasks(
        self,
        env_key: Optional[str] = None,
        keys: Optional[List[str]] = None,
        version: Optional[str] = None,
        team_id: Optional[str] = None,
        project_key: Optional[str] = None,
        task_project_key: Optional[str] = None,
        data_id: Optional[str] = None,
        data_version: Optional[str] = None,
    ) -> List[Task]:
        """Load tasks for the authenticated team, with optional filtering.

        Args:
            env_key: Optional environment key to filter tasks by
            keys: Optional list of task keys to filter by
            version: Optional version to filter tasks by (client-side filter)
            team_id: Optional team_id to filter by (admin only)
            project_key: Optional project key to filter tasks by
            task_project_key: Optional task project key to filter tasks by
            data_id: Optional data identifier to filter tasks by
            data_version: Optional data version to filter tasks by

        Returns:
            List[Task] containing Task objects
        """
        params = {}
        if env_key is not None:
            params["env_key"] = env_key
        if keys is not None:
            params["task_keys"] = keys
        if team_id is not None:
            params["team_id"] = team_id
        if project_key is not None:
            params["project_key"] = project_key
        if task_project_key is not None:
            params["task_project_key"] = task_project_key
        if data_id is not None:
            params["data_id"] = data_id
        if data_version is not None:
            params["data_version"] = data_version

        response = self.client.request("GET", "/v1/tasks", params=params)
        task_list_response = TaskListResponse(**response.json())

        # Prepare verifier loading tasks
        verifier_tasks = []
        task_responses_with_indices = []

        for idx, task_response in enumerate(task_list_response.tasks):
            if task_response.verifier:
                embedded_code = task_response.verifier.code or ""
                is_embedded_error = embedded_code.strip().startswith(
                    "<error loading code:"
                )

                def create_verifier_with_fallback(tr, emb_code, is_error):
                    """Create verifier with fallback logic."""
                    if not is_error:
                        # Try to create from embedded data
                        try:
                            return self._create_verifier_from_data(
                                verifier_id=tr.verifier.verifier_id,
                                verifier_key=tr.verifier.key,
                                verifier_code=emb_code,
                                verifier_sha=tr.verifier.sha256,
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to create verifier {tr.verifier.key}: {e}"
                            )
                            return None
                    else:
                        # Fallback: try fetching by ID
                        try:
                            logger.warning(
                                f"Embedded verifier code missing for {tr.verifier.key} (NoSuchKey). "
                                f"Attempting to refetch by id {tr.verifier.verifier_id}"
                            )
                            return self._load_verifier(tr.verifier.verifier_id)
                        except Exception as e:
                            logger.warning(
                                f"Refetch by verifier id failed for {tr.verifier.key}: {e}. "
                                "Leaving verifier unset."
                            )
                            return None

                # Add the task for parallel execution
                verifier_tasks.append(
                    (
                        create_verifier_with_fallback,
                        task_response,
                        embedded_code,
                        is_embedded_error,
                    )
                )
                task_responses_with_indices.append((idx, task_response))
            else:
                # No verifier needed
                verifier_tasks.append(None)
                task_responses_with_indices.append((idx, task_response))

        # Execute all verifier loading in parallel using ThreadPoolExecutor
        verifier_results = []
        if verifier_tasks:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = []
                for task in verifier_tasks:
                    if task is not None:
                        func, tr, emb_code, is_error = task
                        future = executor.submit(func, tr, emb_code, is_error)
                        futures.append(future)
                    else:
                        futures.append(None)

                # Collect results
                for future in futures:
                    if future is None:
                        verifier_results.append(None)
                    else:
                        try:
                            result = future.result()
                            verifier_results.append(result)
                        except Exception as e:
                            logger.warning(f"Verifier loading failed: {e}")
                            verifier_results.append(None)

        # Build tasks with results
        tasks = []
        for (idx, task_response), verifier_result in zip(
            task_responses_with_indices, verifier_results
        ):
            # Handle verifier result
            verifier = None
            verifier_func = task_response.verifier_func

            if task_response.verifier:
                # Process verifier result
                if verifier_result is not None:
                    verifier = verifier_result
                    embedded_code = task_response.verifier.code or ""
                    is_embedded_error = embedded_code.strip().startswith(
                        "<error loading code:"
                    )
                    if not is_embedded_error:
                        verifier_func = embedded_code

            task = Task(
                key=task_response.key,
                prompt=task_response.prompt,
                env_id=task_response.environment_id,  # Map environment_id -> env_id
                created_at=task_response.created_at,
                version=task_response.version,
                data_id=getattr(task_response, "data_id", None),  # Get data_id if available
                data_version=getattr(task_response, "data_version", None),  # Get data_version if available
                env_variables=task_response.env_variables or {},
                verifier_func=verifier_func,  # Set verifier code
                verifier=verifier,  # Use created verifier or None
                metadata={},  # Default empty metadata
                output_json_schema=getattr(task_response, "output_json_schema", None),  # Get output_json_schema if available
            )
            tasks.append(task)

        # Apply client-side filtering for version if specified
        if version is not None:
            tasks = [task for task in tasks if task.version == version]
        
        # Apply client-side filtering for data_id if specified
        if data_id is not None:
            tasks = [task for task in tasks if task.data_id == data_id]
        
        # Apply client-side filtering for data_version if specified
        if data_version is not None:
            tasks = [task for task in tasks if task.data_version == data_version]

        return tasks

    def export_tasks(
        self, env_key: Optional[str] = None, filename: Optional[str] = None
    ):
        """Export tasks for the authenticated team, optionally filtered by environment.

        Args:
            env_key: Optional environment key to filter tasks by
            filename: Optional filename to write tasks to. If not provided, defaults to 'tasks.json' or 'tasks_{env_key}.json'

        Returns:
            str: Path to the exported file if tasks were written, None if no tasks found
        """
        tasks = self.load_tasks(env_key)
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
                if "verifier" in task_dict:
                    task_dict.pop("verifier")
                tasks_data.append(task_dict)

            # Write to JSON file
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(tasks_data, f, indent=2, default=str)

            logger.info(f"Exported {len(tasks)} tasks to {filename}")
            return filename
        else:
            logger.info("No tasks found to export")
            return None

    def import_single_task(self, task: Task, project_key: Optional[str] = None):
        """Import a single task.

        Args:
            task: Task object to import
            project_key: Optional project key to associate with the task

        Returns:
            Response from the API, or None if the import failed
        """
        try:
            # Validate that verifier_func exists
            if not task.verifier_func:
                raise ValueError(
                    f"Task {task.key} is missing verifier_func. "
                    "All tasks must have a verifier_func to be imported."
                )

            params = {}
            if project_key:
                params["project_key"] = project_key
            response = self.client.request(
                "POST", "/v1/tasks", json=task.model_dump(), params=params
            )
            return response
        except Exception as e:
            logger.error(f"Failed to import task {task.key}: {e}")
            return None

    def import_tasks(self, filename: str, project_key: Optional[str] = None):
        """Import tasks from a JSON file.

        Args:
            filename: Path to the JSON file of Task objects to import
            project_key: Optional project key to associate with the tasks

        Returns:
            List[Task] containing imported Task objects

        Raises:
            ValueError: If any task is missing verifier_func or has invalid verifier code
        """
        with open(filename, "r", encoding="utf-8") as f:
            tasks_data = json.load(f)

        # Create tasks from the loaded data using load_task_from_json
        # This will validate and create verifiers properly
        tasks = []
        for task_data in tasks_data:
            # Validate that verifier_func exists
            verifier_code = task_data.get("verifier_func") or task_data.get(
                "verifier_code"
            )
            if not verifier_code:
                task_key = task_data.get("key", task_data.get("id", "unknown"))
                raise ValueError(
                    f"Task {task_key} is missing verifier_func. "
                    "All tasks must have a verifier_func to be imported."
                )

            # Use load_task_from_json to properly create and validate the task
            # Pass raise_on_verifier_error=True to fail fast on invalid verifier code
            task = self.load_task_from_json(task_data, raise_on_verifier_error=True)
            tasks.append(task)

        # Use ThreadPoolExecutor to parallelize the imports with max 20 workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            responses = list(
                executor.map(lambda t: self.import_single_task(t, project_key), tasks)
            )

        # Filter out None values (failed imports)
        return [r for r in responses if r is not None]

    def account(self) -> AccountResponse:
        """Get account information including instance limits and usage.

        Returns:
            AccountResponse containing team_id, team_name, instance_limit, and instance_count
        """
        response = self.client.request("GET", "/v1/account")
        return AccountResponse(**response.json())

    def update_task(
        self,
        task_key: str,
        prompt: Optional[str] = None,
        verifier_code: Optional[str] = None,
    ) -> TaskResponse:
        """Update an existing task.

        Args:
            task_key: The key of the task to update
            prompt: New prompt text for the task (optional)
            verifier_code: Python code for task verification (optional)

        Returns:
            TaskResponse containing the updated task details
        """
        payload = TaskUpdateRequest(prompt=prompt, verifier_code=verifier_code)
        response = self.client.request(
            "PUT", f"/v1/tasks/{task_key}", json=payload.model_dump(exclude_none=True)
        )
        return TaskResponse(**response.json())

    def get_task(
        self,
        task_key: str,
        version_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> TaskResponse:
        """Get a task by key and optional version.

        Args:
            task_key: The key of the task to retrieve
            version_id: Optional version ID to filter by
            team_id: Optional team_id to filter by (admin only)

        Returns:
            TaskResponse containing the task details
        """
        params = {}
        if version_id is not None:
            params["version_id"] = version_id
        if team_id is not None:
            params["team_id"] = team_id

        response = self.client.request(
            "GET", f"/v1/tasks/{task_key}", params=params
        )
        return TaskResponse(**response.json())

    def _create_verifier_from_data(
        self, verifier_id: str, verifier_key: str, verifier_code: str, verifier_sha: str
    ) -> "SyncVerifierFunction":
        """Create an AsyncVerifierFunction from verifier data.

        Args:
            verifier_id: The verifier ID
            verifier_key: The verifier key
            verifier_code: The verifier code
            verifier_sha: The verifier SHA256

        Returns:
            AsyncVerifierFunction created from the verifier code
        """
        from .tasks import verifier_from_string
        from .verifiers import SyncVerifierFunction

        # Use verifier_from_string to create the verifier
        verifier_func = verifier_from_string(
            verifier_func=verifier_code,
            verifier_id=verifier_id,
            verifier_key=verifier_key,
            sha256=verifier_sha,
        )

        # Store the original verifier code for reference
        verifier_func._verifier_code = verifier_code

        return verifier_func

    def _load_verifier(self, verifier_id: str) -> "SyncVerifierFunction":
        """Load a verifier by ID and create an AsyncVerifierFunction.

        Args:
            verifier_id: The verifier ID to fetch

        Returns:
            AsyncVerifierFunction created from the verifier code
        """
        # Fetch verifier from API
        response = self.client.request("GET", f"/v1/verifiers/{verifier_id}")
        verifier_data = response.json()

        # Use the common method to create verifier
        return self._create_verifier_from_data(
            verifier_id=verifier_id,
            verifier_key=verifier_data["key"],
            verifier_code=verifier_data["code"],
            verifier_sha=verifier_data.get("sha256", ""),
        )


# Shared
def _delete_instance(client: SyncWrapper, instance_id: str) -> InstanceResponse:
    response = client.request("DELETE", f"/v1/env/instances/{instance_id}")
    return InstanceResponse(**response.json())


def _check_bundle_exists(
    client: SyncWrapper, bundle_hash: str
) -> VerifiersCheckResponse:
    response = client.request("GET", f"/v1/verifiers/check?sha256={bundle_hash}")
    return VerifiersCheckResponse(**response.json())


def _execute_verifier_remote(
    client: SyncWrapper,
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
    logger.debug(
        f"Sending verifier execute request: key={key}, sha256={bundle_sha[:8]}..., function_name={function_name}"
    )
    logger.debug(f"Request has bundle: {needs_upload}")
    logger.debug(f"Using client with base_url: {client.base_url}")
    logger.debug(f"Request data keys: {list(request_data.keys())}")
    logger.debug(
        f"Bundle size: {len(request_data.get('bundle', ''))} chars"
        if "bundle" in request_data
        else "No bundle"
    )

    # Note: This should be called on the instance URL, not the orchestrator
    # The instance has manager URLs for verifier execution
    response = client.request("POST", "/v1/verifiers/execute", json=request_data)

    # Debug the response
    response_json = response.json()
    logger.debug(f"Verifier execute response: {response_json}")

    return VerifiersExecuteResponse(**response_json)
