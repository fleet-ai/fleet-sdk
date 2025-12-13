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

"""No-op telemetry backend for testing and disabled telemetry."""

import uuid
from typing import Any, Dict, List, Optional

from .base import TelemetryBackend


class NoopBackend(TelemetryBackend):
    """No-op backend that discards all events.
    
    Useful for:
    - Testing without a real backend
    - Disabling telemetry while maintaining the same code path
    - Development without infrastructure
    """
    
    async def connect(self) -> None:
        """No-op connect."""
        pass
    
    async def disconnect(self) -> None:
        """No-op disconnect."""
        pass
    
    async def create_session(
        self,
        session_id: str,
        team_id: str,
        model: str,
        job_id: Optional[str] = None,
        task_key: Optional[str] = None,
        eval_task_id: Optional[str] = None,
        instance_id: Optional[str] = None,
        attempt: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Return the session ID without persisting."""
        return session_id
    
    async def update_session(
        self,
        session_id: str,
        status: str,
        error: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> None:
        """No-op update."""
        pass
    
    async def log_message(
        self,
        session_id: str,
        position: int,
        role: str,
        content: Any,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
        tokens: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Return a generated message ID without persisting."""
        return str(uuid.uuid4())
    
    async def log_messages_batch(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        start_position: int,
    ) -> List[str]:
        """Return generated message IDs without persisting."""
        return [str(uuid.uuid4()) for _ in messages]

