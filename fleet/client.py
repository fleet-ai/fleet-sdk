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
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Tuple

from .base import EnvironmentBase, SyncWrapper
from .models import (
    InstanceRequest,
    InstanceRecord,
    Environment as EnvironmentModel,
    VerifiersCheckResponse,
    VerificationResponse,
    VerifiersExecuteResponse,
    ToolLogEntry, ActionLogEntry, EnvironmentSnapshot, 
    SnapshotValidation, ToolLogResponse, ToolSessionStartRequest,
    ToolSessionStartResponse, ToolLogQueryRequest,
)

from .instance import (
    InstanceClient,
    ResetRequest,
    ResetResponse,
    ExecuteFunctionResponse,
)
from .config import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT, REGION_BASE_URL
from .instance.base import default_httpx_client
from .instance.client import ValidatorType
from .instance.models import (
    Resource as ResourceModel,
    CDPDescribeResponse,  # Add this
)
from .resources.base import Resource
from .resources.sqlite import SQLiteResource
from .resources.browser import BrowserResource

logger = logging.getLogger(__name__)

class LoggingBrowserResource(BrowserResource):
    """Browser resource wrapper that automatically logs all tool usage."""
    
    def __init__(self, resource: ResourceModel, client: "SyncWrapper", session_id: Optional[str] = None):
        super().__init__(resource, client)
        self._session_id = session_id
    
    def _log_tool_action(self, action: str, parameters: Dict[str, Any], result: Any = None, error: str = None):
        """Log a tool action to the tool_log table."""
        if not self._session_id:
            return
            
        start_time = time.time()
        try:
            self.client.request(
                "POST",
                "/log-tool",
                json={
                    "tool_name": "browser",
                    "action": action,
                    "parameters": parameters,
                    "result": result if result else {},
                    "success": error is None,
                    "error": error,
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "session_id": self._session_id,
                    "user_agent": "fleet-sdk"
                }
            )
        except Exception as e:
            logger.warning(f"Failed to log tool action: {e}")
    
    def start(self, width: int = 1920, height: int = 1080) -> CDPDescribeResponse:
        """Start browser and log the action."""
        parameters = {"width": width, "height": height, "resolution": f"{width}x{height}"}
        try:
            result = super().start(width, height)
            self._log_tool_action("start", parameters, {"success": True})
            return result
        except Exception as e:
            self._log_tool_action("start", parameters, error=str(e))
            raise
    
    def screenshot(self) -> Dict[str, Any]:
        """Take screenshot and log the action."""
        parameters = {}
        try:
            # This assumes there's a screenshot method - you may need to implement it
            result = {"url": self.devtools_url(), "timestamp": datetime.utcnow().isoformat()}
            self._log_tool_action("screenshot", parameters, result)
            return result
        except Exception as e:
            self._log_tool_action("screenshot", parameters, error=str(e))
            raise




class Environment(EnvironmentBase):
    def __init__(self, client: Optional[SyncWrapper], **kwargs):
        super().__init__(**kwargs)
        self._client = client
        self._instance: Optional[InstanceClient] = None
        self._session_id: Optional[str] = None

    @property
    def instance(self) -> InstanceClient:
        if self._instance is None:
            self._instance = InstanceClient(
                self.manager_url, self._client.httpx_client if self._client else None
            )
        return self._instance

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
        """Get browser resource with automatic logging."""
        base_browser = self.instance.browser(name)
        # Wrap it with logging capabilities
        return LoggingBrowserResource(
            base_browser.resource,
            base_browser.client,
            self._session_id
        )

    def state(self, uri: str) -> Resource:
        return self.instance.state(uri)

    def resources(self) -> List[Resource]:
        return self.instance.resources()

    def close(self) -> InstanceRecord:
        if hasattr(self, '_session_id') and self._session_id:
            try:
                self.instance._client.request(
                    "POST",
                    f"/end-tool-session/{self._session_id}"
                )
                logger.info(f"Ended tool logging session: {self._session_id}")
            except Exception as e:
                logger.warning(f"Failed to end tool logging session: {e}")
        
        return _delete_instance(self._load_client, self.instance_id)

    def verify(self, validator: ValidatorType) -> ExecuteFunctionResponse:
        return self.instance.verify(validator)

    def verify_raw(
        self, function_code: str, function_name: str
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

    def get_snapshot(self, browser_resource: Optional[BrowserResource] = None) -> EnvironmentSnapshot:
        """
        Get a snapshot of the current environment state including action logs and tool logs.
        
        Args:
            browser_resource: Optional browser resource to capture current state from
            
        Returns:
            EnvironmentSnapshot containing all logs and state information
        """
        # Get current timestamp
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        # Get session ID from current tool logs or generate new one
        session_id = self._get_current_session_id() or f"snapshot-{int(time.time())}"
        
        # Query tool logs
        tool_logs_response = self.instance._client.request(
            "POST",
            "/query-tool-logs",
            json={
                "session_id": session_id,
                "limit": None  # Get all logs for this session
            }
        )
        tool_logs_data = tool_logs_response.json()
        tool_logs = [ToolLogEntry(**entry) for entry in tool_logs_data.get("entries", [])]
        
        # Query action logs
        action_logs_query = """
            SELECT id, timestamp, action_type, payload, sql, args, path
            FROM action_log
            ORDER BY timestamp DESC
            LIMIT 10000
        """
        action_logs_response = self.instance._client.request(
            "POST",
            "/resources/sqlite/action_log/query",
            json={
                "query": action_logs_query,
                "read_only": True
            }
        )
        action_logs_data = action_logs_response.json()
        
        action_logs = []
        if action_logs_data.get("success") and action_logs_data.get("rows"):
            columns = action_logs_data["columns"]
            for row in action_logs_data["rows"]:
                entry_dict = dict(zip(columns, row))
                action_logs.append(ActionLogEntry(**entry_dict))
        
        # Get current page URL and viewport if browser is available
        page_url = ""
        viewport_size = (1920, 1080)  # Default
        
        if browser_resource:
            try:
                # Get current page URL via CDP
                cdp_info = browser_resource.describe()
                # You might need to implement a method to get current URL via CDP
                # For now, we'll look for the last navigation in tool logs
                for log in reversed(tool_logs):
                    if log.tool_name == "browser" and log.action == "screenshot":
                        if log.result and "url" in log.result:
                            page_url = log.result["url"]
                            break
                
                # Get viewport size from last browser start or from logs
                for log in reversed(tool_logs):
                    if log.tool_name == "browser" and log.action == "start":
                        if log.parameters and "resolution" in log.parameters:
                            res = log.parameters["resolution"].split("x")
                            viewport_size = (int(res[0]), int(res[1]))
                            break
            except Exception as e:
                logger.warning(f"Could not get browser state: {e}")
        
        # Create snapshot
        return EnvironmentSnapshot(
            env_key=self.env_key,
            instance_id=self.instance_id,
            timestamp=timestamp,
            session_id=session_id,
            tool_logs=tool_logs,
            action_logs=action_logs,
            page_url=page_url,
            viewport_size=viewport_size,
            metadata={
                "snapshot_version": "1.0",
                "tool_log_count": len(tool_logs),
                "action_log_count": len(action_logs)
            }
        )
    
    def _get_current_session_id(self) -> Optional[str]:
        """Get the current session ID from the environment."""
        # First try to use the stored session ID
        if hasattr(self, '_session_id') and self._session_id:
            return self._session_id
        
        # Otherwise, try to get the most recent session ID from tool logs
        try:
            response = self.instance._client.request(
                "POST",
                "/query-tool-logs",
                json={
                    "limit": 1
                }
            )
            data = response.json()
            if data.get("entries") and len(data["entries"]) > 0:
                return data["entries"][0].get("session_id")
        except Exception:
            pass
        return None


class Fleet:
    def __init__(
        self,
        api_key: Optional[str] = os.getenv("FLEET_API_KEY"),
        base_url: Optional[str] = None,
        httpx_client: Optional[httpx.Client] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
    ):
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
        self, env_key: str, region: Optional[str] = None, session_id: Optional[str] = None
    ) -> Environment:
        if ":" in env_key:
            env_key_part, version = env_key.split(":", 1)
            if not version.startswith("v"):
                version = f"v{version}"
        else:
            env_key_part = env_key
            version = None

        request = InstanceRequest(env_key=env_key_part, version=version, region=region)
        region_base_url = REGION_BASE_URL.get(region)
        response = self.client.request(
            "POST",
            "/v1/env/instances",
            json=request.model_dump(),
            base_url=region_base_url,
        )
        instance = Environment(client=self.client, **response.json())
        instance.instance.load()
        
        # Start tool logging session automatically
        if session_id is None:
            session_id = f"env-{instance.instance_id}-{int(time.time())}"
        
        try:
            instance.instance._client.request(
                "POST",
                "/start-tool-session",
                json={
                    "session_id": session_id,
                    "metadata": {
                        "env_key": env_key,
                        "instance_id": instance.instance_id,
                        "region": region or "default",
                        "started_at": datetime.utcnow().isoformat() + "Z"
                    }
                }
            )
            instance._session_id = session_id
            logger.info(f"Started tool logging session: {session_id}")
        except Exception as e:
            logger.warning(f"Failed to start tool logging session: {e}")
            instance._session_id = None
        
        return instance

    def instances(
        self, status: Optional[str] = None, region: Optional[str] = None
    ) -> List[Environment]:
        params = {}
        if status:
            params["status"] = status
        if region:
            params["region"] = region

        response = self.client.request("GET", "/v1/env/instances", params=params)
        return [
            Environment(client=self.client, **instance_data)
            for instance_data in response.json()
        ]

    def instance(self, instance_id: str) -> Environment:
        response = self.client.request("GET", f"/v1/env/instances/{instance_id}")
        instance = Environment(client=self.client, **response.json())
        instance.instance.load()
        return instance

    def check_bundle_exists(self, bundle_hash: str) -> VerifiersCheckResponse:
        return _check_bundle_exists(self.client, bundle_hash)

    def execute_verifier_remote(
        self, bundle_data: bytes, args: tuple, kwargs: dict, timeout: Optional[int] = 30
    ) -> VerifiersExecuteResponse:
        return _execute_verifier_remote(
            self.client, bundle_data, args, kwargs, timeout
        )

    def delete(self, instance_id: str) -> InstanceRecord:
        return _delete_instance(self.client, instance_id)

    def resume(
        self,
        snapshot: EnvironmentSnapshot,
        validate: bool = True,
        playback_speed: float = 1.0
    ) -> Tuple[Environment, SnapshotValidation]:
        """
        Resume an environment from a snapshot by recreating the state.
        
        Args:
            snapshot: EnvironmentSnapshot to resume from
            validate: Whether to validate the resumed state matches the snapshot
            playback_speed: Speed multiplier for replaying actions (1.0 = normal speed)
            
        Returns:
            Tuple of (new Environment instance, validation results)
        """
        # Create new environment instance
        new_env = self.make(snapshot.env_key)
        
        # Start a new tool session for tracking
        replay_session_id = f"replay-{snapshot.session_id}-{int(time.time())}"
        new_env.instance._client.request(
            "POST",
            "/start-tool-session",
            json={
                "session_id": replay_session_id,
                "metadata": {
                    "type": "snapshot_replay",
                    "original_session_id": snapshot.session_id,
                    "snapshot_timestamp": snapshot.timestamp
                }
            }
        )
        
        # Update tool logs with environment name before replay
        for log in snapshot.tool_logs:
            log_dict = log.dict()
            log_dict["session_id"] = replay_session_id
            log_dict["metadata"] = {
                "env_name": snapshot.env_key,
                "replay": True
            }
        
        # Start browser with same viewport
        browser = new_env.browser()
        browser.start(width=snapshot.viewport_size[0], height=snapshot.viewport_size[1])
        
        from fleet.playwright import FleetPlaywrightWrapper

        playwright_wrapper = FleetPlaywrightWrapper(
            cdp_url=browser.cdp_url(),
            instance_client=new_env.instance
        )
        
        # Replay tool logs in order
        validation_errors = []
        last_timestamp = None
        
        for i, tool_log in enumerate(snapshot.tool_logs):
            try:
                # Calculate wait time between actions
                if last_timestamp and playback_speed > 0:
                    current_ts = datetime.fromisoformat(tool_log.timestamp.rstrip('Z'))
                    last_ts = datetime.fromisoformat(last_timestamp.rstrip('Z'))
                    wait_time = (current_ts - last_ts).total_seconds() / playback_speed
                    if wait_time > 0:
                        time.sleep(min(wait_time, 5))  # Cap at 5 seconds
                
                # Replay the tool action
                _replay_tool_action(
                    playwright_wrapper,
                    tool_log,
                    new_env.instance._client,
                    replay_session_id
                )
                
                last_timestamp = tool_log.timestamp
                
            except Exception as e:
                error_msg = f"Failed to replay action {i}: {tool_log.tool_name}.{tool_log.action} - {e}"
                logger.error(error_msg)
                validation_errors.append(error_msg)
        
        # End replay session
        new_env.instance._client.request(
            "POST",
            f"/end-tool-session/{replay_session_id}"
        )
        
        # Validate if requested
        validation = SnapshotValidation(
            success=True,
            page_match=True,
            action_log_match=True,
            discrepancies=validation_errors,
            message="Replay completed"
        )
        
        if validate:
            validation = _validate_resumed_state(
                new_env,
                snapshot,
                playwright_wrapper,
                validation_errors
            )
        
        return new_env, validation


# Shared
def _delete_instance(client: SyncWrapper, instance_id: str) -> InstanceRecord:
    response = client.request("DELETE", f"/v1/env/instances/{instance_id}")
    return InstanceRecord(**response.json())


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
    response = client.request("POST", "/v1/verifiers/execute", json=request_data)
    
    # Debug the response
    response_json = response.json()
    logger.debug(f"Verifier execute response: {response_json}")

    return VerifiersExecuteResponse(**response_json)



def _replay_tool_action(
    playwright_wrapper: 'FleetPlaywrightWrapper',
    tool_log: ToolLogEntry,
    client: 'SyncWrapper',
    session_id: str
) -> None:
    """Replay a single tool action."""
    start_time = time.time()
    
    try:
        if tool_log.tool_name == "browser":
            # Map browser actions to playwright wrapper methods
            action_map = {
                "screenshot": lambda: playwright_wrapper.screenshot(),
                "left_click": lambda: playwright_wrapper.click(
                    tool_log.parameters.get("x"),
                    tool_log.parameters.get("y")
                ),
                "type": lambda: playwright_wrapper.type(
                    tool_log.parameters.get("text", "")
                ),
                "key": lambda: playwright_wrapper.key(
                    tool_log.parameters.get("text", "")
                ),
                "scroll": lambda: playwright_wrapper.scroll(
                    direction=tool_log.parameters.get("scroll_direction", "down"),
                    amount=tool_log.parameters.get("scroll_amount", 3)
                ),
                "mouse_move": lambda: playwright_wrapper.mouse_move(
                    tool_log.parameters.get("x"),
                    tool_log.parameters.get("y")
                ),
                "wait": lambda: time.sleep(
                    tool_log.parameters.get("duration", 1)
                ),
                # Add more action mappings as needed
            }
            
            if tool_log.action in action_map:
                result = action_map[tool_log.action]()
            else:
                logger.warning(f"Unknown browser action: {tool_log.action}")
                result = None
                
        elif tool_log.tool_name == "complete_task":
            # Don't replay task completion
            logger.info("Skipping complete_task during replay")
            return
            
        elif tool_log.tool_name == "report_issue":
            # Log but don't replay issue reports
            logger.info(f"Previous issue reported: {tool_log.parameters}")
            return
            
        elif tool_log.tool_name == "give_up":
            # Don't replay give up
            logger.warning(f"Original session gave up: {tool_log.parameters}")
            return
        
        # Log the replayed action
        duration_ms = int((time.time() - start_time) * 1000)
        
        client.request(
            "POST",
            "/log-tool",
            json={
                "tool_name": tool_log.tool_name,
                "action": tool_log.action,
                "parameters": tool_log.parameters,
                "result": result if result else tool_log.result,
                "success": True,
                "duration_ms": duration_ms,
                "session_id": session_id,
                "user_agent": "snapshot_replay"
            }
        )
        
    except Exception as e:
        # Log failure
        duration_ms = int((time.time() - start_time) * 1000)
        
        client.request(
            "POST",
            "/log-tool",
            json={
                "tool_name": tool_log.tool_name,
                "action": tool_log.action,
                "parameters": tool_log.parameters,
                "success": False,
                "error": str(e),
                "duration_ms": duration_ms,
                "session_id": session_id,
                "user_agent": "snapshot_replay"
            }
        )
        raise


def _validate_resumed_state(
    new_env: Environment,
    snapshot: EnvironmentSnapshot,
    playwright_wrapper: 'FleetPlaywrightWrapper',
    existing_errors: List[str]
) -> SnapshotValidation:
    """Validate that the resumed state matches the snapshot."""
    discrepancies = existing_errors.copy()
    
    # Check current page URL
    page_match = True
    try:
        current_screenshot = playwright_wrapper.screenshot()
        current_url = current_screenshot.get("url", "")
        
        if current_url != snapshot.page_url:
            page_match = False
            discrepancies.append(
                f"Page URL mismatch: expected '{snapshot.page_url}', got '{current_url}'"
            )
    except Exception as e:
        page_match = False
        discrepancies.append(f"Could not verify page URL: {e}")
    
    # Compare action logs
    action_log_match = True
    try:
        # Get new action logs
        new_snapshot = new_env.get_snapshot()
        
        # Compare counts
        if len(new_snapshot.action_logs) != len(snapshot.action_logs):
            action_log_match = False
            discrepancies.append(
                f"Action log count mismatch: expected {len(snapshot.action_logs)}, "
                f"got {len(new_snapshot.action_logs)}"
            )
        
        # Could do more detailed comparison here if needed
        
    except Exception as e:
        action_log_match = False
        discrepancies.append(f"Could not verify action logs: {e}")
    
    success = page_match and action_log_match and len(discrepancies) == 0
    
    return SnapshotValidation(
        success=success,
        page_match=page_match,
        action_log_match=action_log_match,
        discrepancies=discrepancies,
        message="Validation completed" if success else "Validation failed with discrepancies"
    )