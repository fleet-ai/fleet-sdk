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

"""Type definitions for Fleet telemetry."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class MessageRole(str, Enum):
    """Role of a message in a session."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class SessionStatus(str, Enum):
    """Status of a session."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolCall(TypedDict, total=False):
    """OpenAI-style tool call structure."""
    id: str
    type: str  # "function"
    function: Dict[str, Any]  # {"name": str, "arguments": str}


class SessionEvent(TypedDict, total=False):
    """Event payload for session lifecycle."""
    event_type: str
    session_id: str
    team_id: str
    job_id: Optional[str]
    model: str
    task_key: Optional[str]
    instance_id: Optional[str]
    status: str
    timestamp: str
    metadata: Dict[str, Any]


class MessageEvent(TypedDict, total=False):
    """Event payload for session messages."""
    event_type: str
    session_id: str
    position: int
    role: str
    content: Any
    tool_calls: Optional[List[ToolCall]]
    tool_call_id: Optional[str]
    tokens: Optional[int]
    timestamp: str
    metadata: Dict[str, Any]

