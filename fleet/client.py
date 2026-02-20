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
import dataclasses
import httpx
import json
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any, TYPE_CHECKING, Union
from urllib.parse import urlparse
from uuid import UUID

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
    Run,
    HeartbeatResponse,
    JobCreateRequest,
    JobResponse,
    JobListResponse,
    JobCreateResponse,
    ScenarioResponse,
    ScenarioListResponse,
    ScenarioCreateRequest,
    JobSessionsResponse,
    SessionTranscriptResponse,
    SessionIngestRequest,
    SessionIngestMessage,
    SessionIngestResponse,
    SessionStatus,
)
from .tasks import Task

if TYPE_CHECKING:
    from .verifiers import SyncVerifierFunction
    from .judge import SyncJudge


def _json_default(x: Any) -> Any:
    """Default JSON serializer for non-native types."""
    if isinstance(x, (datetime, date)):
        return x.isoformat()
    if isinstance(x, (UUID, Path)):
        return str(x)
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, Enum):
        return x.value
    if isinstance(x, bytes):
        return base64.b64encode(x).decode("utf-8")
    if isinstance(x, set):
        return list(x)
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return dataclasses.asdict(x)
    # Handle objects with __dict__ (generic objects)
    if hasattr(x, "__dict__"):
        return x.__dict__
    raise TypeError(f"Not JSON serializable: {type(x)}")


def _to_dict(obj: Any) -> Any:
    """Convert any object to a JSON-serializable dict/value.

    Handles:
    - Pydantic v2 models (model_dump)
    - Pydantic v1 models (.dict())
    - dataclasses (asdict)
    - TypedDict (just dict at runtime)
    - Objects with __dict__
    - Primitives pass through
    """
    if obj is None:
        return None

    # Pydantic v2
    if hasattr(obj, "model_dump"):
        return obj.model_dump()

    # Pydantic v1
    if hasattr(obj, "dict") and callable(obj.dict):
        return obj.dict()

    # dataclass
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)

    # Already a dict or list - recursively convert
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dict(v) for v in obj]

    # Primitives
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj

    # bytes -> base64
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("utf-8")

    # datetime/date
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()

    # UUID, Path
    if isinstance(obj, (UUID, Path)):
        return str(obj)

    # Enum
    if isinstance(obj, Enum):
        return obj.value

    # Decimal
    if isinstance(obj, Decimal):
        return float(obj)

    # set
    if isinstance(obj, set):
        return list(obj)

    # Generic object with __dict__
    if hasattr(obj, "__dict__"):
        return {k: _to_dict(v) for k, v in obj.__dict__.items() if not k.startswith("_")}

    # Fallback - try to convert, or return string representation
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


from .instance import (
    InstanceClient,
    ResetRequest,
    ResetResponse,
    ExecuteFunctionResponse,
)
from .instance.models import (
    Resource as ResourceModel,
    ResourceType,
    ResourceMode,
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
from .resources.filesystem import FilesystemResource
from .resources.mcp import SyncMCPResource
from .resources.api import APIResource

logger = logging.getLogger(__name__)


class Session:
    """A session for logging agent interactions to Fleet.

    This provides a simple interface for streaming messages during an agent run.
    Messages are sent one-by-one as they happen.

    Usage:
        session = fleet.session(job_id=job_id)

        # Log LLM calls
        session.log(history, response)

        # Complete when done
        session.complete()  # or session.fail()
    """

    def __init__(
        self,
        client: "Fleet",
        session_id: Optional[str] = None,
        job_id: Optional[str] = None,
        config: Optional[Any] = None,
        model: Optional[str] = None,
        task_key: Optional[str] = None,
        instance_id: Optional[str] = None,
    ):
        self.session_id = session_id
        self.job_id = job_id
        self.config = config
        self.model = model
        self.task_key = task_key
        self.instance_id = instance_id
        self._client = client
        self._message_count = 0
        self._logged_count = 0  # Track how many messages from history have been logged
        self._config_sent = False  # Only send config/model/task_key/instance_id on first log

    def log(self, history: List[Any], response: Any) -> "SessionIngestResponse":
        """Log an LLM call to the session.

        Pass the input history and the model response. The session tracks what's
        already been logged and only sends new messages. Objects are automatically
        serialized to JSON (supports Pydantic, dataclasses, TypedDict, etc.).

        Example:
            response = model.generate(history)
            session.log(history, response.content)

        Args:
            history: The input messages sent to the model
            response: The model's response (any serializable object)

        Returns:
            SessionIngestResponse with updated message count
        """
        from .models import SessionIngestResponse

        # Collect new history messages since last call
        new_history = history[self._logged_count:]

        # Update tracked count to include the response we're about to send
        # This prevents the response from being sent again as "new history" in the next call
        self._logged_count = len(history) + (1 if response is not None else 0)

        # Build the payload - serialize history + response to JSON
        payload: Dict[str, Any] = {
            "history": [_to_dict(msg) for msg in new_history],
            "response": _to_dict(response),
        }
        if self.session_id:
            payload["session_id"] = self.session_id
        if self.job_id:
            payload["job_id"] = self.job_id
        # Include config, model, task_key, instance_id on first log only
        if not self._config_sent:
            if self.config is not None:
                payload["config"] = _to_dict(self.config)
            if self.model is not None:
                payload["model"] = self.model
            if self.task_key is not None:
                payload["task_key"] = self.task_key
            if self.instance_id is not None:
                payload["instance_id"] = self.instance_id
            self._config_sent = True

        if not new_history and response is None:
            return SessionIngestResponse(
                success=True,
                session_id=self.session_id or "",
                message_count=self._message_count,
                created_new_session=False,
            )

        result = self._client._ingest_raw(payload=payload)
        self._message_count = result.message_count
        # Update session_id if this was the first log (new session created)
        if not self.session_id and result.session_id:
            self.session_id = result.session_id
        return result

    def complete(
        self,
        verifier_execution_id: Optional[str] = None,
    ) -> "SessionIngestResponse":
        """Mark the session as completed successfully.

        Args:
            verifier_execution_id: Optional ID of the verifier execution record

        Returns:
            SessionIngestResponse with final state
        """
        from datetime import datetime

        payload: Dict[str, Any] = {
            "session_id": self.session_id,
            "status": "completed",
            "ended_at": datetime.now().isoformat(),
        }
        if verifier_execution_id:
            payload["verifier_execution_id"] = verifier_execution_id

        response = self._client._ingest_raw(payload)
        self._message_count = response.message_count
        return response

    def fail(
        self,
        verifier_execution_id: Optional[str] = None,
    ) -> "SessionIngestResponse":
        """Mark the session as failed.

        Args:
            verifier_execution_id: Optional ID of the verifier execution record

        Returns:
            SessionIngestResponse with final state
        """
        from datetime import datetime

        payload: Dict[str, Any] = {
            "session_id": self.session_id,
            "status": "failed",
            "ended_at": datetime.now().isoformat(),
        }
        if verifier_execution_id:
            payload["verifier_execution_id"] = verifier_execution_id

        response = self._client._ingest_raw(payload)
        self._message_count = response.message_count
        return response

    @property
    def message_count(self) -> int:
        """Get the current message count."""
        return self._message_count


class SyncEnv(EnvironmentBase):
    def __init__(self, client: Optional[SyncWrapper], **kwargs):
        super().__init__(**kwargs)
        self._client = client
        self._apps: Dict[str, InstanceClient] = {}
        self._instance: Optional[InstanceClient] = None
        self._judge: Optional["SyncJudge"] = None
        self._manager_url_override: Optional[str] = None  # For URL mode

    @property
    def manager_url(self) -> str:
        """Override to support URL mode where urls is None."""
        if self._manager_url_override is not None:
            return self._manager_url_override
        return super().manager_url

    @property
    def instance(self) -> InstanceClient:
        if self._instance is None:
            self._instance = InstanceClient(
                self.manager_url, self._client.httpx_client if self._client else None
            )
        return self._instance

    def app(self, name: str) -> InstanceClient:
        if name not in self._apps:
            # Extract scheme://netloc from manager_url, then construct /{name}/api/v1/env
            # Supports all URL formats:
            #   https://host/api/v1/env -> https://host/{name}/api/v1/env
            #   https://host/sentry/api/v1/env -> https://host/{name}/api/v1/env
            #   http://localhost:8080/api/v1/env -> http://localhost:8080/{name}/api/v1/env
            parsed = urlparse(self.manager_url)
            root = f"{parsed.scheme}://{parsed.netloc}"
            new_url = f"{root}/{name}/api/v1/env"

            self._apps[name] = InstanceClient(
                new_url,
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

    def fs(self) -> FilesystemResource:
        """Get a filesystem diff resource for inspecting file changes."""
        return self.instance.fs()

    def api(self, name: str = "api") -> APIResource:
        """Get an API resource for making HTTP requests to the app's API.

        Args:
            name: Name for the API resource (default: "api")

        Returns:
            APIResource for making HTTP requests
        """
        # Use urls.api if available, otherwise fall back to urls.root + "/raw"
        if self.urls and self.urls.api:
            base_url = self.urls.api
        elif self.urls and self.urls.root:
            base_url = f"{self.urls.root.rstrip('/')}/raw"
        elif self._manager_url_override and self._manager_url_override != "local://":
            # URL mode: strip /api/v1/env suffix to get root URL
            base_url = self._manager_url_override.rstrip('/')
            if base_url.endswith('/api/v1/env'):
                base_url = base_url[:-len('/api/v1/env')]
        else:
            raise ValueError("No API URL configured for this environment")
        return self.instance.api(name, base_url)

    @property
    def mcp(self) -> SyncMCPResource:
        mcp_url = f"{self.urls.root}mcp"
        return SyncMCPResource(url=mcp_url, env_key=self.env_key)

    @property
    def judge(self) -> "SyncJudge":
        """LLM-as-judge grading via orchestrator API."""
        if self._judge is None:
            from .judge import SyncJudge

            self._judge = SyncJudge(
                client=self._load_client,
                instance_id=self.instance_id,
            )
        return self._judge

    def state(self, uri: str) -> Resource:
        return self.instance.state(uri)

    def resources(self) -> List[Resource]:
        return self.instance.resources()

    def close(self) -> InstanceResponse:
        return _delete_instance(self._load_client, self.instance_id)

    def heartbeat(self) -> HeartbeatResponse:
        """Send heartbeat to keep instance alive (if heartbeat monitoring is enabled).
        
        Returns:
            HeartbeatResponse containing heartbeat status and deadline information
        """
        body = {}
        if self.heartbeat_region:
            body["region"] = self.heartbeat_region
        
        response = self._load_client.request(
            "POST", 
            f"/v1/env/instances/{self.instance_id}/heartbeat",
            json=body
        )
        return HeartbeatResponse(**response.json())

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
        verifier_runtime_version: Optional[str] = None,
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
            verifier_runtime_version,
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
        run_id: Optional[str] = None,
        heartbeat_interval: Optional[int] = None,
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
            run_id=run_id,
            heartbeat_interval=heartbeat_interval,
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
        return self.make(env_key=task.env_spec)

    def instances(
        self, status: Optional[str] = None, region: Optional[str] = None, run_id: Optional[str] = None, profile_id: Optional[str] = None
    ) -> List[SyncEnv]:
        params = {}
        if status:
            params["status"] = status
        if region:
            params["region"] = region
        if run_id:
            params["run_id"] = run_id
        if profile_id:
            params["profile_id"] = profile_id

        response = self.client.request("GET", "/v1/env/instances", params=params)
        return [
            SyncEnv(client=self.client, **instance_data)
            for instance_data in response.json()
        ]

    def instance(self, instance_id: Union[str, Dict[str, str]]) -> SyncEnv:
        """Create or connect to an environment instance.

        Supports three modes based on input type:
        1. dict: Local filesystem mode - {"current": "./data.db", "seed": "./seed.db"}
        2. str starting with http:// or https://: Localhost/URL mode
        3. str (other): Remote cloud instance mode

        Args:
            instance_id: Instance identifier (str), URL (str starting with http://),
                        or local db mapping (dict)

        Returns:
            SyncEnv: Environment instance
        """
        # Local filesystem mode - dict of resource names to file paths
        if isinstance(instance_id, dict):
            return self._create_local_instance(instance_id)

        # Localhost/direct URL mode - string starting with http:// or https://
        elif isinstance(instance_id, str) and instance_id.startswith(("http://", "https://")):
            return self._create_url_instance(instance_id)

        # Remote mode - existing behavior
        else:
            response = self.client.request("GET", f"/v1/env/instances/{instance_id}")
            instance = SyncEnv(client=self.client, **response.json())
            instance.instance.load()
            return instance

    def _create_url_instance(self, base_url: str) -> SyncEnv:
        """Create instance connected to a direct URL (localhost or custom).

        Args:
            base_url: URL of the instance manager API

        Returns:
            SyncEnv: Environment instance configured for URL mode
        """
        instance_client = InstanceClient(url=base_url, httpx_client=self._httpx_client)

        # Create a minimal environment for URL mode
        env = SyncEnv(
            client=self.client,
            instance_id=base_url,
            env_key="localhost",
            version="",
            status="running",
            subdomain="localhost",
            created_at="",
            updated_at="",
            terminated_at=None,
            team_id="",
            region="localhost",
            env_variables=None,
            data_key=None,
            data_version=None,
            urls=None,
            health=None,
        )
        env._instance = instance_client
        env._manager_url_override = base_url  # Set manager_url for URL mode
        return env

    @staticmethod
    def _normalize_db_path(path: str) -> tuple[str, bool]:
        """Normalize database path and detect if it's in-memory.

        Args:
            path: Database path - can be:
                  - File path: "./data.db"
                  - Plain memory: ":memory:"
                  - Named memory: ":memory:namespace"
                  - URI: "file:name?mode=memory&cache=shared"

        Returns:
            Tuple of (normalized_path, is_memory)
        """
        import uuid
        import sqlite3

        if path == ":memory:":
            # Plain :memory: - create unique namespace
            name = f"mem_{uuid.uuid4().hex[:8]}"
            return f"file:{name}?mode=memory&cache=shared", True
        elif path.startswith(":memory:"):
            # Named memory: :memory:current -> file:current?mode=memory&cache=shared
            namespace = path[8:]  # Remove ":memory:" prefix
            return f"file:{namespace}?mode=memory&cache=shared", True
        elif "mode=memory" in path:
            # Already a proper memory URI
            return path, True
        else:
            # Regular file path
            return path, False

    def _create_local_instance(self, dbs: Dict[str, str]) -> SyncEnv:
        """Create instance with local file-based or in-memory SQLite resources.

        Args:
            dbs: Map of resource names to paths (e.g., {"current": "./data.db"} or
                 {"current": ":memory:current"})

        Returns:
            SyncEnv: Environment instance configured for local mode
        """
        import sqlite3

        instance_client = InstanceClient(url="local://", httpx_client=None)
        instance_client._resources = []  # Mark as loaded
        instance_client._memory_anchors = {}  # Store anchor connections for in-memory DBs

        # Store creation parameters for local SQLiteResources
        # This allows db() to create new instances each time (matching HTTP mode behavior)
        for name, path in dbs.items():
            # Normalize path and detect if it's in-memory
            normalized_path, is_memory = self._normalize_db_path(path)

            # Create anchor connection for in-memory databases
            # This keeps the database alive as long as the env exists
            if is_memory:
                anchor_conn = sqlite3.connect(normalized_path, uri=True)
                instance_client._memory_anchors[name] = anchor_conn

            resource_model = ResourceModel(
                name=name,
                type=ResourceType.db,
                mode=ResourceMode.rw,
                label=f"Local: {path}",
            )
            instance_client._resources_state[ResourceType.db.value][name] = {
                'type': 'local',
                'resource_model': resource_model,
                'db_path': normalized_path,
                'is_memory': is_memory
            }

        # Create a minimal environment for local mode
        env = SyncEnv(
            client=self.client,
            instance_id="local",
            env_key="local",
            version="",
            status="running",
            subdomain="local",
            created_at="",
            updated_at="",
            terminated_at=None,
            team_id="",
            region="local",
            env_variables=None,
            data_key=None,
            data_version=None,
            urls=None,
            health=None,
        )
        env._instance = instance_client
        env._manager_url_override = "local://"  # Set manager_url for local mode
        return env

    def check_bundle_exists(self, bundle_hash: str) -> VerifiersCheckResponse:
        return _check_bundle_exists(self.client, bundle_hash)

    def execute_verifier_remote(
        self, bundle_data: bytes, args: tuple, kwargs: dict, timeout: Optional[int] = 30
    ) -> VerifiersExecuteResponse:
        return _execute_verifier_remote(self.client, bundle_data, args, kwargs, timeout)

    def delete(self, instance_id: str) -> InstanceResponse:
        return _delete_instance(self.client, instance_id)

    def close(self, instance_id: str) -> InstanceResponse:
        """Close (delete) a specific instance by ID.
        
        Args:
            instance_id: The instance ID to close
            
        Returns:
            InstanceResponse containing the deleted instance details
        """
        return _delete_instance(self.client, instance_id)

    def heartbeat(self, instance_id: str, region: Optional[str] = None) -> HeartbeatResponse:
        """Send heartbeat to keep instance alive (if heartbeat monitoring is enabled).
        
        Args:
            instance_id: The instance ID to send heartbeat for
            region: Optional region override for cross-region heartbeats
            
        Returns:
            HeartbeatResponse containing heartbeat status and deadline information
        """
        return _send_heartbeat(self.client, instance_id, region)

    def close_all(self, run_id: Optional[str] = None, profile_id: Optional[str] = None) -> List[InstanceResponse]:
        """Close (delete) instances using the batch delete endpoint.
        
        Args:
            run_id: Optional run ID to filter instances by
            profile_id: Optional profile ID to filter instances by (use "self" for your own profile)
            
        Returns:
            List[InstanceResponse] containing the deleted instances
            
        Note:
            At least one of run_id or profile_id must be provided.
        """
        return _delete_instances_batch(self.client, run_id=run_id, profile_id=profile_id)
    
    def list_runs(
        self, profile_id: Optional[str] = None, status: Optional[str] = "active"
    ) -> List[Run]:
        """List all runs (groups of instances by run_id) with aggregated statistics.
        
        Args:
            profile_id: Optional profile ID to filter runs by (use "self" for your own profile)
            status: Filter by run status - "active" (default), "inactive", or "all"
            
        Returns:
            List[Run] containing run information with instance counts and timestamps
        """
        params = {}
        if profile_id:
            params["profile_id"] = profile_id
        if status:
            params["active"] = status
            
        response = self.client.request("GET", "/v1/env/runs", params=params)
        return [Run(**run_data) for run_data in response.json()]

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

        # Extract verifier_runtime_version from metadata if present
        verifier_runtime_version = None
        if "metadata" in task_json and isinstance(task_json["metadata"], dict):
            verifier_runtime_version = task_json["metadata"].get("verifier_runtime_version")

        try:
            if verifier_id and verifier_code:
                verifier = self._create_verifier_from_data(
                    verifier_id=verifier_id,
                    verifier_key=task_json.get("key", task_json.get("id")),
                    verifier_code=verifier_code,
                    verifier_sha=verifier_sha,
                    verifier_runtime_version=verifier_runtime_version,
                )
        except Exception as e:
            error_msg = f"Failed to create verifier {task_json.get('key', task_json.get('id'))}: {e}"
            if raise_on_verifier_error:
                raise ValueError(error_msg) from e
            # else:
            #     logger.warning(error_msg)

        task = Task(
            key=task_json.get("key", task_json.get("id")),
            prompt=task_json["prompt"],
            env_key=task_json.get("env_key") or task_json.get("environment_id") or task_json.get("env_id"),  # Prefer env_key, fallback to environment_id (API) or env_id (legacy)
            created_at=task_json.get("created_at"),
            version=task_json.get("version"),
            data_id=task_json.get("data_id"),
            data_version=task_json.get("data_version"),
            env_variables=task_json.get("env_variables", {}),
            verifier_func=verifier_code,  # Set verifier code
            verifier=verifier,  # Use created verifier or None
            verifier_id=verifier_id,  # Set verifier_id so _rebuild_verifier works
            verifier_sha=verifier_sha,  # Set verifier_sha
            verifier_runtime_version=verifier_runtime_version,  # Set verifier_runtime_version
            metadata=task_json.get("metadata", {}),  # Default empty metadata
            output_json_schema=task_json.get("output_json_schema"),  # JSON schema for output
            factual_answer=task_json.get("factual_answer"),  # Expected answer for research/factual tasks
            task_modality=task_json.get("task_modality"),  # Task modality (computer_use, tool_use, browser)
            task_scenario_id=task_json.get("task_scenario_id"),  # Task scenario ID
            task_lifecycle_status=task_json.get("task_lifecycle_status"),  # Task lifecycle status
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
                            # logger.warning(
                            #     f"Failed to create verifier {tr.verifier.key}: {e}"
                            # )
                            return None
                    else:
                        # Fallback: try fetching by ID
                        try:
                            # logger.warning(
                            #     f"Embedded verifier code missing for {tr.verifier.key} (NoSuchKey). "
                            #     f"Attempting to refetch by id {tr.verifier.verifier_id}"
                            # )
                            return self._load_verifier(tr.verifier.verifier_id)
                        except Exception as e:
                            # logger.warning(
                            #     f"Refetch by verifier id failed for {tr.verifier.key}: {e}. "
                            #     "Leaving verifier unset."
                            # )
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
                            # logger.warning(f"Verifier loading failed: {e}")
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

            # Extract verifier metadata
            verifier_id = task_response.verifier_id
            if not verifier_id and task_response.verifier:
                verifier_id = task_response.verifier.verifier_id
            
            verifier_sha = None
            if task_response.verifier:
                verifier_sha = task_response.verifier.sha256
            
            # Extract verifier_runtime_version from metadata if present
            verifier_runtime_version = None
            metadata = task_response.metadata or {}
            if isinstance(metadata, dict):
                verifier_runtime_version = metadata.get("verifier_runtime_version")

            task = Task(
                key=task_response.key,
                prompt=task_response.prompt,
                env_key=task_response.env_key,
                created_at=task_response.created_at,
                version=task_response.version,
                data_id=getattr(task_response, "data_id", None),  # Get data_id if available
                data_version=getattr(task_response, "data_version", None),  # Get data_version if available
                env_variables=task_response.env_variables or {},
                verifier_func=verifier_func,  # Set verifier code
                verifier=verifier,  # Use created verifier or None
                verifier_id=verifier_id,  # Set verifier_id
                verifier_sha=verifier_sha,  # Set verifier_sha
                verifier_runtime_version=verifier_runtime_version,  # Set verifier_runtime_version
                metadata=metadata,
                output_json_schema=getattr(task_response, "output_json_schema", None),  # Get output_json_schema if available
                factual_answer=getattr(task_response, "factual_answer", None),  # Get factual_answer if available
                task_modality=getattr(task_response, "task_modality", None),  # Get task_modality if available
                task_scenario_id=getattr(task_response, "task_scenario_id", None),  # Get task_scenario_id if available
                task_lifecycle_status=getattr(task_response, "task_lifecycle_status", None),  # Get task_lifecycle_status if available
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

            # logger.info(f"Exported {len(tasks)} tasks to {filename}")
            return filename
        else:
            # logger.info("No tasks found to export")
            return None

    def import_single_task(self, task: Task, project_key: Optional[str] = None):
        """Import a single task.

        Args:
            task: Task object to import
            project_key: Optional project key to associate with the task

        Returns:
            Response from the API

        Raises:
            ValueError: If task is missing verifier_func
            Exception: If the API request fails
        """
        # Validate that verifier_func exists
        if not task.verifier_func:
            raise ValueError(
                f"Task {task.key} is missing verifier_func. "
                "All tasks must have a verifier_func to be imported."
            )

        params = {}
        if project_key:
            params["project_key"] = project_key
        
        # Convert task to dict and map env_key -> env_id for API compatibility
        task_data = task.model_dump()
        if "env_key" in task_data:
            task_data["env_id"] = task_data.pop("env_key")
        
        response = self.client.request(
            "POST", "/v1/tasks", json=task_data, params=params
        )
        return response

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

    # Scenario methods
    def get_scenario(self, scenario_id: str) -> ScenarioResponse:
        """Get a scenario by ID.

        Args:
            scenario_id: The scenario ID to retrieve

        Returns:
            ScenarioResponse containing the scenario details
        """
        response = self.client.request("GET", f"/v1/scenarios/{scenario_id}")
        return ScenarioResponse(**response.json())

    def list_scenarios(self, project_id: Optional[str] = None) -> ScenarioListResponse:
        """List scenarios, optionally filtered by project.

        Args:
            project_id: Optional project ID to filter scenarios by

        Returns:
            ScenarioListResponse containing the list of scenarios
        """
        params = {}
        if project_id:
            params["project_id"] = project_id
        response = self.client.request("GET", "/v1/scenarios", params=params)
        return ScenarioListResponse(**response.json())

    def create_scenario(
        self,
        scenario_title: str,
        project_id: str,
        output_json_schema: Optional[Dict[str, Any]] = None,
        task_complexity_tier: Optional[str] = None,
        user_story: Optional[str] = None,
        entrypoint: Optional[str] = None,
        is_research_based: Optional[bool] = None,
        is_action_based: Optional[bool] = None,
        scenario_verifier_prompt: Optional[str] = None,
    ) -> ScenarioResponse:
        """Create a new scenario.

        Args:
            scenario_title: Title for the scenario
            project_id: Project ID to associate the scenario with
            output_json_schema: Optional JSON schema for expected output
            task_complexity_tier: Optional complexity tier
            user_story: Optional user story description
            entrypoint: Optional entrypoint URL
            is_research_based: Whether the scenario is research-based
            is_action_based: Whether the scenario is action-based
            scenario_verifier_prompt: Optional verifier prompt

        Returns:
            ScenarioResponse containing the created scenario
        """
        request = ScenarioCreateRequest(
            scenario_title=scenario_title,
            project_id=project_id,
            output_json_schema=output_json_schema,
            task_complexity_tier=task_complexity_tier,
            user_story=user_story,
            entrypoint=entrypoint,
            is_research_based=is_research_based,
            is_action_based=is_action_based,
            scenario_verifier_prompt=scenario_verifier_prompt,
        )
        response = self.client.request("POST", "/v1/scenarios", json=request.model_dump(exclude_none=True))
        return ScenarioResponse(**response.json())

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
        metadata: Optional[Dict[str, Any]] = None,
        writer_metadata: Optional[Dict[str, Any]] = None,
        qa_metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskResponse:
        """Update an existing task.

        Args:
            task_key: The key of the task to update
            prompt: New prompt text for the task (optional)
            verifier_code: Python code for task verification (optional)
            metadata: Additional metadata for the task (optional)
            writer_metadata: Metadata filled by task writer (optional)
            qa_metadata: Metadata filled by QA reviewer (optional)

        Returns:
            TaskResponse containing the updated task details
        """
        payload = TaskUpdateRequest(
            prompt=prompt,
            verifier_code=verifier_code,
            metadata=metadata,
            writer_metadata=writer_metadata,
            qa_metadata=qa_metadata,
        )
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

    # Jobs API methods

    def list_jobs(self, team_id: Optional[str] = None) -> List[JobResponse]:
        """List all jobs for the authenticated team.

        Args:
            team_id: Optional team_id to filter by (admin only)

        Returns:
            List[JobResponse] containing job information
        """
        params = {}
        if team_id is not None:
            params["team_id"] = team_id

        response = self.client.request("GET", "/v1/jobs", params=params)
        job_list = JobListResponse(**response.json())
        return job_list.jobs

    def create_job(
        self,
        models: List[str],
        name: Optional[str] = None,
        pass_k: int = 1,
        env_key: Optional[str] = None,
        project_key: Optional[str] = None,
        task_keys: Optional[List[str]] = None,
        excluded_task_keys: Optional[List[str]] = None,
        max_steps: Optional[int] = None,
        max_duration_minutes: int = 60,
        max_concurrent_per_model: int = 30,
        mode: Optional[str] = None,
        system_prompt: Optional[str] = None,
        model_prompts: Optional[Dict[str, str]] = None,
        byok_keys: Optional[Dict[str, str]] = None,
        byok_ttl_minutes: Optional[int] = None,
        harness: Optional[str] = None,
    ) -> JobCreateResponse:
        """Create a new job.

        Args:
            models: List of model identifiers in "provider/model" format
            name: Optional job name. Supports placeholders: {id} (UUID), {sid} (short UUID), {i} (auto-increment, must be suffix)
            pass_k: Number of passes (default: 1)
            env_key: Environment key (mutually exclusive with project_key/task_keys)
            project_key: Project key (mutually exclusive with env_key/task_keys)
            task_keys: Specific task keys (mutually exclusive with env_key/project_key)
            excluded_task_keys: Task keys to exclude
            max_steps: Maximum agent steps
            max_duration_minutes: Timeout in minutes (default: 60)
            max_concurrent_per_model: Max concurrent per model (default: 30)
            mode: "tool-use" or "computer-use"
            system_prompt: Custom system prompt
            model_prompts: Per-model prompts (model -> prompt)
            byok_keys: Bring Your Own Keys (provider -> API key)
            byok_ttl_minutes: TTL for BYOK keys in minutes
            harness: Harness identifier

        Returns:
            JobCreateResponse containing job_id, workflow_job_id, status, and name
        """
        request = JobCreateRequest(
            name=name,
            models=models,
            pass_k=pass_k,
            env_key=env_key,
            project_key=project_key,
            task_keys=task_keys,
            excluded_task_keys=excluded_task_keys,
            max_steps=max_steps,
            max_duration_minutes=max_duration_minutes,
            max_concurrent_per_model=max_concurrent_per_model,
            mode=mode,
            system_prompt=system_prompt,
            model_prompts=model_prompts,
            byok_keys=byok_keys,
            byok_ttl_minutes=byok_ttl_minutes,
            harness=harness,
        )

        response = self.client.request(
            "POST", "/v1/jobs", json=request.model_dump(exclude_none=True)
        )
        return JobCreateResponse(**response.json())

    def get_job(self, job_id: str, team_id: Optional[str] = None) -> JobResponse:
        """Get a specific job by ID.

        Args:
            job_id: The job ID
            team_id: Optional team_id to filter by (admin only)

        Returns:
            JobResponse containing job information
        """
        params = {}
        if team_id is not None:
            params["team_id"] = team_id

        response = self.client.request("GET", f"/v1/jobs/{job_id}", params=params)
        return JobResponse(**response.json())

    # Sessions API methods

    def list_job_sessions(self, job_id: str) -> JobSessionsResponse:
        """List all sessions for a job, grouped by task.

        Args:
            job_id: The job ID

        Returns:
            JobSessionsResponse containing sessions grouped by task with statistics
        """
        response = self.client.request("GET", f"/v1/sessions/job/{job_id}")
        return JobSessionsResponse(**response.json())

    def get_session_transcript(self, session_id: str) -> SessionTranscriptResponse:
        """Get the transcript for a specific session.

        Args:
            session_id: The session ID

        Returns:
            SessionTranscriptResponse containing task, instance, verifier result, and messages
        """
        response = self.client.request(
            "GET", f"/v1/sessions/{session_id}/transcript"
        )
        return SessionTranscriptResponse(**response.json())

    def _ingest(
        self,
        messages: List[Dict[str, Any]],
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        task_key: Optional[str] = None,
        job_id: Optional[str] = None,
        instance_id: Optional[str] = None,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        started_at: Optional[str] = None,
        ended_at: Optional[str] = None,
        verifier_execution_id: Optional[str] = None,
    ) -> SessionIngestResponse:
        """Internal method to ingest session data."""
        message_objects = [SessionIngestMessage(**msg) for msg in messages]
        request = SessionIngestRequest(
            messages=message_objects,
            session_id=session_id,
            model=model,
            task_key=task_key,
            job_id=job_id,
            instance_id=instance_id,
            status=SessionStatus(status) if status else None,
            metadata=metadata,
            started_at=started_at,
            ended_at=ended_at,
            verifier_execution_id=verifier_execution_id,
        )
        response = self.client.request(
            "POST",
            "/v1/sessions/ingest",
            json=request.model_dump(exclude_none=True),
        )
        return SessionIngestResponse(**response.json())

    def _ingest_raw(
        self,
        payload: Dict[str, Any],
    ) -> SessionIngestResponse:
        """Internal method to ingest raw session data as JSON.

        This sends the history and response as-is to the backend,
        letting the backend handle format normalization.
        """
        # Pre-serialize with our custom handler to ensure all types are JSON-safe
        json_str = json.dumps(payload, default=_json_default)
        clean_payload = json.loads(json_str)

        response = self.client.request(
            "POST",
            "/v1/traces/logs",
            json=clean_payload,
        )
        return SessionIngestResponse(**response.json())

    def start_session(
        self,
        session_id: Optional[str] = None,
        job_id: Optional[str] = None,
        config: Optional[Any] = None,
        model: Optional[str] = None,
        task_key: Optional[str] = None,
        instance_id: Optional[str] = None,
    ) -> Session:
        """Start a new session for logging agent interactions.

        This returns a Session object. The session is created on the backend
        when you call log() for the first time.

        Args:
            session_id: Optional existing session ID to resume
            job_id: Optional job ID to associate with the session
            config: Optional config object (e.g., GenerateContentConfig) to log
            model: Optional model name to log
            task_key: Optional Fleet task key
            instance_id: Optional Fleet instance ID

        Returns:
            Session object with log(), complete(), and fail() methods

        Example:
            session = fleet_client.start_session(config=config, model="gpt-4", task_key="task_123")

            # Log LLM calls during agent run
            session.log(history, response)

            # Complete when done
            session.complete()
        """
        return Session(
            client=self,
            session_id=session_id,
            job_id=job_id,
            config=config,
            model=model,
            task_key=task_key,
            instance_id=instance_id,
        )

    def trace_job(self, name: Optional[str] = None) -> str:
        """Create a new trace job.

        Args:
            name: Name of the job (generated server-side if not provided)

        Returns:
            The job_id string
        """
        from .models import TraceJobRequest, TraceJobResponse

        request = TraceJobRequest(name=name)
        response = self.client.request(
            "POST",
            "/v1/traces/jobs",
            json=request.model_dump(),
        )
        result = TraceJobResponse(**response.json())
        return result.job_id

    def create_session(
        self,
        model: Optional[str] = None,
        task_key: Optional[str] = None,
        job_id: Optional[str] = None,
        instance_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        started_at: Optional[str] = None,
        initial_message: Optional[Dict[str, Any]] = None,
    ) -> SessionIngestResponse:
        """Create a new session, optionally with an initial message.

        This is useful for streaming scenarios where you want to create
        a session first and then append messages one by one.

        Args:
            model: Model identifier (e.g., "anthropic/claude-sonnet-4")
            task_key: Task key to associate with the session
            job_id: Job ID to associate with the session
            instance_id: Instance ID to associate with the session
            metadata: Additional metadata for the session
            started_at: ISO timestamp when session started
            initial_message: Optional first message dict with 'role' and 'content'

        Returns:
            SessionIngestResponse containing session_id

        Example:
            # Create session and get ID
            session = fleet.create_session(
                model="anthropic/claude-sonnet-4",
                task_key="my_task",
                started_at=datetime.now().isoformat()
            )
            
            # Append messages as they happen
            fleet.append_message(session.session_id, {"role": "user", "content": "Hello"})
            fleet.append_message(session.session_id, {"role": "assistant", "content": "Hi!"})
        """
        # Use a placeholder message if none provided
        if initial_message:
            messages = [initial_message]
        else:
            messages = [{"role": "system", "content": "[session created]"}]

        return self._ingest(
            messages=messages,
            model=model,
            task_key=task_key,
            job_id=job_id,
            instance_id=instance_id,
            status="running",
            metadata=metadata,
            started_at=started_at,
        )

    def append_message(
        self,
        session_id: str,
        message: Dict[str, Any],
        status: Optional[str] = None,
        ended_at: Optional[str] = None,
    ) -> SessionIngestResponse:
        """Append a single message to an existing session.

        This is useful for streaming scenarios where you want to send
        messages one by one as they happen.

        Args:
            session_id: The session ID to append to
            message: Message dict with 'role' and 'content' keys.
                Optional keys: 'tool_calls', 'tool_call_id', 'timestamp', 'tokens', 'metadata'
            status: Optional status update ("running", "completed", "failed")
            ended_at: ISO timestamp when session ended (set when completing)

        Returns:
            SessionIngestResponse with updated message count

        Example:
            # Append user message
            fleet.append_message(session_id, {"role": "user", "content": "What's 2+2?"})
            
            # Append assistant response
            fleet.append_message(session_id, {"role": "assistant", "content": "4"})
            
            # Complete the session
            fleet.append_message(
                session_id,
                {"role": "assistant", "content": "Done!"},
                status="completed",
                ended_at=datetime.now().isoformat()
            )
        """
        return self._ingest(
            messages=[message],
            session_id=session_id,
            status=status,
            ended_at=ended_at,
        )

    def complete_session(
        self,
        session_id: str,
        status: str = "completed",
        ended_at: Optional[str] = None,
        final_message: Optional[Dict[str, Any]] = None,
    ) -> SessionIngestResponse:
        """Mark a session as complete.

        Args:
            session_id: The session ID to complete
            status: Final status ("completed", "failed", "cancelled")
            ended_at: ISO timestamp when session ended (defaults to now)
            final_message: Optional final message to append

        Returns:
            SessionIngestResponse with final state
        """
        from datetime import datetime as dt
        
        if ended_at is None:
            ended_at = dt.now().isoformat()
        
        if final_message:
            messages = [final_message]
        else:
            messages = [{"role": "system", "content": f"[session {status}]"}]

        return self._ingest(
            messages=messages,
            session_id=session_id,
            status=status,
            ended_at=ended_at,
        )

    def _create_verifier_from_data(
        self, verifier_id: str, verifier_key: str, verifier_code: str, verifier_sha: str, verifier_runtime_version: Optional[str] = None
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
            verifier_runtime_version=verifier_runtime_version or "",
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


def _send_heartbeat(client: SyncWrapper, instance_id: str, region: Optional[str] = None) -> HeartbeatResponse:
    """Send heartbeat to keep instance alive."""
    body = {}
    if region:
        body["region"] = region
    
    response = client.request(
        "POST",
        f"/v1/env/instances/{instance_id}/heartbeat",
        json=body
    )
    return HeartbeatResponse(**response.json())


def _delete_instances_batch(
    client: SyncWrapper, run_id: Optional[str] = None, profile_id: Optional[str] = None
) -> List[InstanceResponse]:
    """Delete instances using the batch endpoint with flexible filtering."""
    params = {}
    if run_id:
        params["run_id"] = run_id
    if profile_id:
        params["profile_id"] = profile_id
    
    if not params:
        raise ValueError("At least one of run_id or profile_id must be provided")
    
    response = client.request("DELETE", "/v1/env/instances/batch", params=params)
    return [InstanceResponse(**instance_data) for instance_data in response.json()]


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
    verifier_runtime_version: Optional[str] = None,
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

    # Add verifier_runtime_version if present
    if verifier_runtime_version:
        request_data["verifier_runtime_version"] = verifier_runtime_version

    # Debug logging
    # logger.debug(
    #     f"Sending verifier execute request: key={key}, sha256={bundle_sha[:8]}..., function_name={function_name}"
    # )
    # logger.debug(f"Request has bundle: {needs_upload}")
    # logger.debug(f"Using client with base_url: {client.base_url}")
    # logger.debug(f"Request data keys: {list(request_data.keys())}")
    # logger.debug(
    #     f"Bundle size: {len(request_data.get('bundle', ''))} chars"
    #     if "bundle" in request_data
    #     else "No bundle"
    # )

    # Note: This should be called on the instance URL, not the orchestrator
    # The instance has manager URLs for verifier execution
    response = client.request("POST", "/v1/verifiers/execute", json=request_data)

    # Debug the response
    response_json = response.json()
    # logger.debug(f"Verifier execute response: {response_json}")

    return VerifiersExecuteResponse(**response_json)
