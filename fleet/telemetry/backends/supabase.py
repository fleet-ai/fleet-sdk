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

"""Supabase telemetry backend for direct database writes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import TelemetryBackend


class SupabaseBackend(TelemetryBackend):
    """Telemetry backend that writes directly to Supabase.
    
    This backend writes session and message data directly to Supabase tables:
    - sessions: Session metadata and status
    - session_messages: Individual messages within sessions
    
    Suitable for:
    - Low to medium volume (<10K events/sec)
    - When real-time UI updates via Supabase Realtime are needed
    - Simple deployment without additional infrastructure
    
    Args:
        supabase_url: Supabase project URL
        supabase_key: Supabase service key (with write access)
    """
    
    def __init__(self, supabase_url: str, supabase_key: str):
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self._client: Optional[Any] = None
    
    async def connect(self) -> None:
        """Initialize Supabase client connection."""
        try:
            from supabase import acreate_client
            self._client = await acreate_client(self.supabase_url, self.supabase_key)
        except ImportError:
            raise ImportError(
                "supabase package is required for SupabaseBackend. "
                "Install it with: pip install supabase"
            )
    
    async def disconnect(self) -> None:
        """Close Supabase client connection."""
        # Supabase async client doesn't require explicit cleanup
        self._client = None
    
    def _utc_now(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
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
        """Create a new session in Supabase."""
        if not self._client:
            raise RuntimeError("Backend not connected. Call connect() first.")
        
        now = self._utc_now()
        
        session_row = {
            "team_id": team_id,
            "status": "running",
            "model": model,
            "attempt": attempt,
            "created_at": now,
            "started_at": now,
            "metadata": {
                "source": "fleet-sdk",
                "task_key": task_key,
                **(metadata or {}),
            },
        }
        
        # Add optional fields
        if job_id:
            session_row["job_id"] = job_id
        if eval_task_id:
            session_row["eval_task"] = eval_task_id
        if instance_id:
            session_row["instance"] = instance_id
        
        try:
            res = await self._client.table("sessions").insert(session_row).execute()
            data = getattr(res, "data", None)
            if not data:
                raise RuntimeError(f"Failed to create session: {res}")
            
            return data[0]["id"]
            
        except Exception as e:
            # Handle model foreign key constraint errors
            error_str = str(e)
            if "sessions_model_fkey" in error_str or "foreign key constraint" in error_str.lower():
                # Model not in models table - create session without model
                del session_row["model"]
                session_row["metadata"]["model_not_in_table"] = model
                
                res = await self._client.table("sessions").insert(session_row).execute()
                data = getattr(res, "data", None)
                if not data:
                    raise RuntimeError(f"Failed to create session: {res}")
                
                return data[0]["id"]
            raise
    
    async def update_session(
        self,
        session_id: str,
        status: str,
        error: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update session status in Supabase."""
        if not self._client:
            raise RuntimeError("Backend not connected. Call connect() first.")
        
        update = {
            "status": status,
            "ended_at": self._utc_now(),
        }
        
        if error:
            update["error"] = error
        
        await self._client.table("sessions").update(update).eq("id", session_id).execute()
    
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
        """Log a message to Supabase."""
        if not self._client:
            raise RuntimeError("Backend not connected. Call connect() first.")
        
        message_row = {
            "session_id": session_id,
            "position": position,
            "role": role,
            "content": content,
            "created_at": self._utc_now(),
        }
        
        if tool_calls:
            message_row["tool_calls"] = tool_calls
        if tool_call_id:
            message_row["tool_call_id"] = tool_call_id
        if tokens:
            message_row["tokens"] = tokens
        if metadata:
            message_row["metadata"] = metadata
        
        res = await self._client.table("session_messages").insert(message_row).execute()
        data = getattr(res, "data", None)
        if not data:
            raise RuntimeError(f"Failed to insert message: {res}")
        
        return data[0]["id"]
    
    async def log_messages_batch(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        start_position: int,
    ) -> List[str]:
        """Log multiple messages in a batch to Supabase."""
        if not self._client:
            raise RuntimeError("Backend not connected. Call connect() first.")
        
        now = self._utc_now()
        rows = []
        
        for i, msg in enumerate(messages):
            row = {
                "session_id": session_id,
                "position": start_position + i,
                "role": msg.get("role", "user"),
                "content": msg.get("content"),
                "created_at": now,
            }
            if msg.get("tool_calls"):
                row["tool_calls"] = msg["tool_calls"]
            if msg.get("tool_call_id"):
                row["tool_call_id"] = msg["tool_call_id"]
            if msg.get("tokens"):
                row["tokens"] = msg["tokens"]
            if msg.get("metadata"):
                row["metadata"] = msg["metadata"]
            
            rows.append(row)
        
        # Insert in batches of 50 to avoid payload limits
        batch_size = 50
        message_ids = []
        
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            res = await self._client.table("session_messages").insert(batch).execute()
            data = getattr(res, "data", [])
            message_ids.extend([d["id"] for d in data])
        
        return message_ids

