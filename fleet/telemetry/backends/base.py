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

"""Abstract base class for telemetry backends."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class TelemetryBackend(ABC):
    """Abstract base class for telemetry backends.
    
    Backends are responsible for persisting telemetry events to a storage system.
    All methods should be non-blocking and handle errors gracefully.
    """
    
    @abstractmethod
    async def connect(self) -> None:
        """Initialize connection to the backend.
        
        Called when a SessionTracker enters its context manager.
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the backend.
        
        Called when a SessionTracker exits its context manager.
        """
        pass
    
    @abstractmethod
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
        """Create a new session record.
        
        Args:
            session_id: Unique session identifier
            team_id: Team ID
            model: Model name (e.g., "gpt-4o")
            job_id: Optional job ID to group sessions
            task_key: Optional task key
            eval_task_id: Optional eval_task record ID
            instance_id: Optional Fleet instance ID
            attempt: Attempt number (default 1)
            metadata: Additional metadata
        
        Returns:
            Session ID (may be different from input if backend generates it)
        """
        pass
    
    @abstractmethod
    async def update_session(
        self,
        session_id: str,
        status: str,
        error: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update session status.
        
        Args:
            session_id: Session ID to update
            status: New status ("running", "completed", "failed", "cancelled")
            error: Error message if status is "failed"
            metadata_update: Additional metadata to merge
        """
        pass
    
    @abstractmethod
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
        """Log a message to a session.
        
        Args:
            session_id: Session ID
            position: Message position in sequence
            role: Message role ("user", "assistant", "system", "tool")
            content: Message content (string or structured)
            tool_calls: Tool calls for assistant messages
            tool_call_id: Tool call ID for tool result messages
            tokens: Token count (optional)
            metadata: Additional metadata
        
        Returns:
            Message ID
        """
        pass
    
    @abstractmethod
    async def log_messages_batch(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        start_position: int,
    ) -> List[str]:
        """Log multiple messages in a batch.
        
        More efficient than individual log_message calls for imports.
        
        Args:
            session_id: Session ID
            messages: List of message dicts
            start_position: Starting position number
        
        Returns:
            List of message IDs
        """
        pass

