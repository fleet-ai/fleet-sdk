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

"""Session tracker for real-time agent telemetry."""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from .backends.base import TelemetryBackend
from .backends.noop import NoopBackend
from .config import TelemetryConfig, get_config
from .types import MessageRole, SessionStatus

logger = logging.getLogger("fleet.telemetry")


def _get_backend(config: TelemetryConfig) -> TelemetryBackend:
    """Create a backend instance based on configuration."""
    if not config.enabled:
        return NoopBackend()
    
    if config.backend == "noop":
        return NoopBackend()
    
    elif config.backend == "supabase":
        from .backends.supabase import SupabaseBackend
        if not config.supabase_url or not config.supabase_key:
            raise ValueError("Supabase URL and key are required for Supabase backend")
        return SupabaseBackend(config.supabase_url, config.supabase_key)
    
    elif config.backend == "kafka":
        from .backends.kafka import KafkaBackend
        if not config.kafka_brokers:
            raise ValueError("Kafka brokers are required for Kafka backend")
        return KafkaBackend(
            brokers=config.kafka_brokers,
            topic=config.kafka_topic,
            security_protocol=config.kafka_security_protocol,
            sasl_mechanism=config.kafka_sasl_mechanism,
            sasl_username=config.kafka_sasl_username,
            sasl_password=config.kafka_sasl_password,
        )
    
    else:
        raise ValueError(f"Unknown backend: {config.backend}")


class SessionTracker:
    """Tracks agent sessions and messages in real-time.
    
    SessionTracker provides a high-level interface for logging agent execution
    to the Fleet platform. It handles:
    - Session lifecycle (start, complete, fail)
    - Message logging (user, assistant, tool)
    - Tool call tracking
    - Automatic error handling
    
    Usage:
        from fleet.telemetry import SessionTracker
        
        async with SessionTracker(model="gpt-4o", task_key="my-task") as session:
            session.log_user_message("Hello!")
            session.log_assistant_message("Hi there!", tool_calls=[...])
            session.log_tool_result(tool_call_id="tc_123", content="Result")
        
        # Session automatically completed when context exits
    
    Args:
        model: Model name (e.g., "gpt-4o", "claude-sonnet-4-20250514")
        task_key: Optional task key for grouping
        job_id: Optional job ID for grouping (overrides config)
        instance_id: Optional Fleet instance ID
        eval_task_id: Optional eval_task record ID
        attempt: Attempt number (default 1)
        metadata: Additional metadata to store with session
        config: Optional custom TelemetryConfig (uses global if not provided)
    """
    
    def __init__(
        self,
        model: str,
        task_key: Optional[str] = None,
        job_id: Optional[str] = None,
        instance_id: Optional[str] = None,
        eval_task_id: Optional[str] = None,
        attempt: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
        config: Optional[TelemetryConfig] = None,
    ):
        self._config = config or get_config()
        self._backend: Optional[TelemetryBackend] = None
        
        # Session parameters
        self._model = model
        self._task_key = task_key
        self._job_id = job_id or self._config.job_id
        self._instance_id = instance_id
        self._eval_task_id = eval_task_id
        self._attempt = attempt
        self._metadata = metadata or {}
        
        # Session state
        self._session_id: Optional[str] = None
        self._position: int = 0
        self._started: bool = False
        self._completed: bool = False
    
    @property
    def session_id(self) -> Optional[str]:
        """Get the current session ID."""
        return self._session_id
    
    @property
    def position(self) -> int:
        """Get the current message position."""
        return self._position
    
    @property
    def is_active(self) -> bool:
        """Check if session is active (started but not completed)."""
        return self._started and not self._completed
    
    async def __aenter__(self) -> "SessionTracker":
        """Enter async context: connect backend and start session."""
        self._backend = _get_backend(self._config)
        await self._backend.connect()
        
        # Generate session ID
        self._session_id = str(uuid.uuid4())
        
        # Create session in backend
        if self._config.team_id:
            try:
                self._session_id = await self._backend.create_session(
                    session_id=self._session_id,
                    team_id=self._config.team_id,
                    model=self._model,
                    job_id=self._job_id,
                    task_key=self._task_key,
                    eval_task_id=self._eval_task_id,
                    instance_id=self._instance_id,
                    attempt=self._attempt,
                    metadata=self._metadata,
                )
                self._started = True
                logger.debug(f"Session started: {self._session_id}")
            except Exception as e:
                logger.warning(f"Failed to create session: {e}")
                # Continue with local-only tracking
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context: complete session and disconnect."""
        if self._started and not self._completed:
            if exc_type is not None:
                # Exception occurred - mark as failed
                await self.complete(
                    status=SessionStatus.FAILED,
                    error=str(exc_val),
                )
            else:
                # Normal exit - mark as completed
                await self.complete(status=SessionStatus.COMPLETED)
        
        if self._backend:
            await self._backend.disconnect()
            self._backend = None
        
        # Don't suppress exceptions
        return False
    
    async def complete(
        self,
        status: SessionStatus = SessionStatus.COMPLETED,
        error: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Manually complete the session.
        
        Args:
            status: Final status (default: COMPLETED)
            error: Error message if status is FAILED
            metadata_update: Additional metadata to merge
        """
        if not self._session_id or not self._backend:
            return
        
        try:
            await self._backend.update_session(
                session_id=self._session_id,
                status=status.value if isinstance(status, SessionStatus) else status,
                error=error,
                metadata_update=metadata_update,
            )
            self._completed = True
            logger.debug(f"Session completed: {self._session_id} ({status})")
        except Exception as e:
            logger.warning(f"Failed to complete session: {e}")
    
    async def log_message(
        self,
        role: MessageRole,
        content: Any,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
        tokens: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Log a message to the session.
        
        Args:
            role: Message role (user, assistant, system, tool)
            content: Message content (string or structured)
            tool_calls: Tool calls for assistant messages
            tool_call_id: Tool call ID for tool result messages
            tokens: Token count (optional)
            metadata: Additional metadata
        
        Returns:
            Message ID if logged successfully, None otherwise
        """
        if not self._session_id or not self._backend:
            return None
        
        try:
            message_id = await self._backend.log_message(
                session_id=self._session_id,
                position=self._position,
                role=role.value if isinstance(role, MessageRole) else role,
                content=content,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
                tokens=tokens,
                metadata=metadata,
            )
            self._position += 1
            logger.debug(f"Message logged: {role} at position {self._position - 1}")
            return message_id
        except Exception as e:
            logger.warning(f"Failed to log message: {e}")
            return None
    
    async def log_user_message(self, content: str) -> Optional[str]:
        """Convenience method to log a user message."""
        return await self.log_message(role=MessageRole.USER, content=content)
    
    async def log_system_message(self, content: str) -> Optional[str]:
        """Convenience method to log a system message."""
        return await self.log_message(role=MessageRole.SYSTEM, content=content)
    
    async def log_assistant_message(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tokens: Optional[int] = None,
    ) -> Optional[str]:
        """Convenience method to log an assistant message.
        
        Args:
            content: Text content (can be None if only tool_calls)
            tool_calls: List of tool calls in OpenAI format
            tokens: Token count from usage
        """
        return await self.log_message(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
            tokens=tokens,
        )
    
    async def log_tool_call(
        self,
        name: str,
        arguments: Dict[str, Any],
        tool_call_id: str,
    ) -> Optional[str]:
        """Log an assistant message with a single tool call.
        
        This is a convenience method that creates the proper OpenAI tool call
        structure. For multiple tool calls in one message, use log_assistant_message.
        
        Args:
            name: Tool/function name
            arguments: Tool arguments
            tool_call_id: Unique ID for this tool call
        """
        tool_calls = [{
            "id": tool_call_id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(arguments) if isinstance(arguments, dict) else arguments,
            },
        }]
        return await self.log_message(
            role=MessageRole.ASSISTANT,
            content=None,
            tool_calls=tool_calls,
        )
    
    async def log_tool_result(
        self,
        tool_call_id: str,
        content: Any,
        is_error: bool = False,
    ) -> Optional[str]:
        """Log a tool result message.
        
        Args:
            tool_call_id: ID of the tool call this responds to
            content: Tool result content
            is_error: Whether this is an error result
        """
        return await self.log_message(
            role=MessageRole.TOOL,
            content=content,
            tool_call_id=tool_call_id,
            metadata={"is_error": is_error} if is_error else None,
        )
    
    async def log_messages_batch(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[str]:
        """Log multiple messages at once (more efficient for imports).
        
        Args:
            messages: List of message dicts with role, content, etc.
        
        Returns:
            List of message IDs
        """
        if not self._session_id or not self._backend:
            return []
        
        try:
            message_ids = await self._backend.log_messages_batch(
                session_id=self._session_id,
                messages=messages,
                start_position=self._position,
            )
            self._position += len(messages)
            return message_ids
        except Exception as e:
            logger.warning(f"Failed to log message batch: {e}")
            return []


@asynccontextmanager
async def track_session(
    model: str,
    task_key: Optional[str] = None,
    job_id: Optional[str] = None,
    instance_id: Optional[str] = None,
    config: Optional[TelemetryConfig] = None,
    **kwargs,
):
    """Convenience async context manager for tracking a session.
    
    This is the recommended way to track agent sessions.
    
    Usage:
        async with track_session(model="gpt-4o", task_key="my-task") as session:
            await session.log_user_message("Hello!")
            await session.log_assistant_message("Hi!")
    
    Args:
        model: Model name
        task_key: Optional task key
        job_id: Optional job ID (overrides config)
        instance_id: Optional Fleet instance ID
        config: Optional custom TelemetryConfig
        **kwargs: Additional arguments passed to SessionTracker
    
    Yields:
        SessionTracker instance
    """
    tracker = SessionTracker(
        model=model,
        task_key=task_key,
        job_id=job_id,
        instance_id=instance_id,
        config=config,
        **kwargs,
    )
    
    async with tracker:
        yield tracker

