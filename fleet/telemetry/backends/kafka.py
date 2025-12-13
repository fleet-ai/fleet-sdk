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

"""Kafka telemetry backend for high-volume event streaming."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import TelemetryBackend


class KafkaBackend(TelemetryBackend):
    """Telemetry backend that writes events to Apache Kafka.
    
    This backend produces events to a Kafka topic, which can then be consumed
    by multiple downstream systems (hot writer to Supabase, cold writer to S3).
    
    Suitable for:
    - High volume (100K+ events/sec)
    - Multi-consumer architectures (hot + cold storage)
    - Durable event replay capability
    
    Event Types:
    - session.created: New session started
    - session.updated: Session status changed
    - message.logged: New message in session
    
    Args:
        brokers: Comma-separated Kafka broker addresses
        topic: Kafka topic for events
        security_protocol: Security protocol (PLAINTEXT, SSL, SASL_PLAINTEXT, SASL_SSL)
        sasl_mechanism: SASL mechanism (PLAIN, SCRAM-SHA-256, SCRAM-SHA-512)
        sasl_username: SASL username
        sasl_password: SASL password
    """
    
    def __init__(
        self,
        brokers: str,
        topic: str = "fleet.telemetry.events",
        security_protocol: str = "PLAINTEXT",
        sasl_mechanism: Optional[str] = None,
        sasl_username: Optional[str] = None,
        sasl_password: Optional[str] = None,
    ):
        self.brokers = brokers
        self.topic = topic
        self.security_protocol = security_protocol
        self.sasl_mechanism = sasl_mechanism
        self.sasl_username = sasl_username
        self.sasl_password = sasl_password
        self._producer: Optional[Any] = None
    
    async def connect(self) -> None:
        """Initialize Kafka producer."""
        try:
            from confluent_kafka import Producer
        except ImportError:
            raise ImportError(
                "confluent-kafka package is required for KafkaBackend. "
                "Install it with: pip install confluent-kafka"
            )
        
        config = {
            "bootstrap.servers": self.brokers,
            "linger.ms": 5,  # Batch for 5ms for better throughput
            "batch.num.messages": 1000,
            "compression.type": "lz4",
            "acks": "all",  # Durability
        }
        
        if self.security_protocol != "PLAINTEXT":
            config["security.protocol"] = self.security_protocol
        
        if self.sasl_mechanism:
            config["sasl.mechanism"] = self.sasl_mechanism
            if self.sasl_username:
                config["sasl.username"] = self.sasl_username
            if self.sasl_password:
                config["sasl.password"] = self.sasl_password
        
        self._producer = Producer(config)
    
    async def disconnect(self) -> None:
        """Flush and close Kafka producer."""
        if self._producer:
            # Flush any pending messages (wait up to 10 seconds)
            self._producer.flush(timeout=10)
            self._producer = None
    
    def _utc_now(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    def _produce(self, event_type: str, data: Dict[str, Any]) -> None:
        """Produce an event to Kafka (non-blocking)."""
        if not self._producer:
            raise RuntimeError("Backend not connected. Call connect() first.")
        
        event = {
            "event_type": event_type,
            "timestamp": self._utc_now(),
            **data,
        }
        
        # Use session_id as partition key for ordering within a session
        key = data.get("session_id", "").encode("utf-8")
        value = json.dumps(event).encode("utf-8")
        
        self._producer.produce(
            self.topic,
            key=key,
            value=value,
            callback=self._delivery_callback,
        )
        
        # Non-blocking poll to trigger callbacks
        self._producer.poll(0)
    
    @staticmethod
    def _delivery_callback(err, msg):
        """Callback for message delivery confirmation."""
        if err:
            # Log error but don't raise - telemetry should not block agent
            import logging
            logging.getLogger("fleet.telemetry").warning(
                f"Kafka delivery failed: {err}"
            )
    
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
        """Create session event in Kafka."""
        self._produce("session.created", {
            "session_id": session_id,
            "team_id": team_id,
            "model": model,
            "job_id": job_id,
            "task_key": task_key,
            "eval_task_id": eval_task_id,
            "instance_id": instance_id,
            "attempt": attempt,
            "status": "running",
            "metadata": metadata or {},
        })
        
        return session_id
    
    async def update_session(
        self,
        session_id: str,
        status: str,
        error: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update session event in Kafka."""
        self._produce("session.updated", {
            "session_id": session_id,
            "status": status,
            "error": error,
            "metadata_update": metadata_update,
        })
    
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
        """Log message event to Kafka."""
        message_id = str(uuid.uuid4())
        
        self._produce("message.logged", {
            "message_id": message_id,
            "session_id": session_id,
            "position": position,
            "role": role,
            "content": content,
            "tool_calls": tool_calls,
            "tool_call_id": tool_call_id,
            "tokens": tokens,
            "metadata": metadata,
        })
        
        return message_id
    
    async def log_messages_batch(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        start_position: int,
    ) -> List[str]:
        """Log multiple messages to Kafka."""
        message_ids = []
        
        for i, msg in enumerate(messages):
            message_id = str(uuid.uuid4())
            message_ids.append(message_id)
            
            self._produce("message.logged", {
                "message_id": message_id,
                "session_id": session_id,
                "position": start_position + i,
                "role": msg.get("role", "user"),
                "content": msg.get("content"),
                "tool_calls": msg.get("tool_calls"),
                "tool_call_id": msg.get("tool_call_id"),
                "tokens": msg.get("tokens"),
                "metadata": msg.get("metadata"),
            })
        
        return message_ids

