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

"""
Fleet Telemetry Module - Real-time agent session and message tracking.

This module provides telemetry for Fleet agents, allowing real-time visibility
into agent execution through the Fleet UI.

Usage:
    import fleet

    # Configure Fleet with telemetry enabled
    fleet.configure(
        api_key="...",
        telemetry_enabled=True,
        supabase_url="https://your-project.supabase.co",
        supabase_key="your-service-key",
        team_id="your-team-id",
    )

    # Track a session
    async with fleet.telemetry.track_session(
        model="gpt-4o",
        task_key="my-task",
    ) as session:
        session.log_user_message("Hello!")
        session.log_assistant_message("Hi there!", tool_calls=[...])
        session.log_tool_result(tool_call_id="tc_123", content="Result")

    # Sessions appear in Fleet UI in real-time!
"""

from .config import TelemetryConfig, configure_telemetry, get_config
from .tracker import SessionTracker, track_session
from .types import MessageRole, SessionStatus

__all__ = [
    # Configuration
    "TelemetryConfig",
    "configure_telemetry",
    "get_config",
    # Session tracking
    "SessionTracker",
    "track_session",
    # Types
    "MessageRole",
    "SessionStatus",
]

