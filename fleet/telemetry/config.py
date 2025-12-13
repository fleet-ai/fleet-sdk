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

"""Telemetry configuration management."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Literal, Optional

BackendType = Literal["supabase", "kafka", "noop"]


@dataclass
class TelemetryConfig:
    """Configuration for Fleet telemetry.
    
    Attributes:
        enabled: Whether telemetry is enabled
        backend: Backend type ("supabase", "kafka", "noop")
        team_id: Fleet team ID (required when enabled)
        job_id: Optional default job ID to group sessions
        
        # Supabase backend settings
        supabase_url: Supabase project URL
        supabase_key: Supabase service key
        
        # Kafka backend settings
        kafka_brokers: Comma-separated Kafka broker addresses
        kafka_topic: Kafka topic for events (default: "fleet.telemetry.events")
        kafka_security_protocol: Kafka security protocol
        kafka_sasl_mechanism: SASL mechanism for authentication
        kafka_sasl_username: SASL username
        kafka_sasl_password: SASL password
    """
    enabled: bool = False
    backend: BackendType = "supabase"
    team_id: Optional[str] = None
    job_id: Optional[str] = None
    
    # Supabase settings
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    
    # Kafka settings
    kafka_brokers: Optional[str] = None
    kafka_topic: str = "fleet.telemetry.events"
    kafka_security_protocol: str = "PLAINTEXT"
    kafka_sasl_mechanism: Optional[str] = None
    kafka_sasl_username: Optional[str] = None
    kafka_sasl_password: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> "TelemetryConfig":
        """Load telemetry configuration from environment variables.
        
        Environment variables:
            FLEET_TELEMETRY_ENABLED: "true" to enable telemetry
            FLEET_TELEMETRY_BACKEND: "supabase", "kafka", or "noop"
            FLEET_TEAM_ID: Team ID for telemetry
            FLEET_JOB_ID: Optional default job ID
            
            # Supabase
            SUPABASE_URL: Supabase project URL
            SUPABASE_SERVICE_KEY or SUPABASE_KEY: Supabase key
            
            # Kafka
            KAFKA_BROKERS: Broker addresses
            KAFKA_TOPIC: Topic name (default: fleet.telemetry.events)
            KAFKA_SECURITY_PROTOCOL: Security protocol
            KAFKA_SASL_MECHANISM: SASL mechanism
            KAFKA_SASL_USERNAME: SASL username
            KAFKA_SASL_PASSWORD: SASL password
        """
        enabled = os.getenv("FLEET_TELEMETRY_ENABLED", "").lower() in ("true", "1", "yes")
        backend = os.getenv("FLEET_TELEMETRY_BACKEND", "supabase")
        
        return cls(
            enabled=enabled,
            backend=backend,  # type: ignore
            team_id=os.getenv("FLEET_TEAM_ID"),
            job_id=os.getenv("FLEET_JOB_ID"),
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_key=os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY"),
            kafka_brokers=os.getenv("KAFKA_BROKERS"),
            kafka_topic=os.getenv("KAFKA_TOPIC", "fleet.telemetry.events"),
            kafka_security_protocol=os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
            kafka_sasl_mechanism=os.getenv("KAFKA_SASL_MECHANISM"),
            kafka_sasl_username=os.getenv("KAFKA_SASL_USERNAME"),
            kafka_sasl_password=os.getenv("KAFKA_SASL_PASSWORD"),
        )
    
    def validate(self) -> None:
        """Validate configuration.
        
        Raises:
            ValueError: If configuration is invalid
        """
        if not self.enabled:
            return
        
        if not self.team_id:
            raise ValueError("team_id is required when telemetry is enabled")
        
        if self.backend == "supabase":
            if not self.supabase_url:
                raise ValueError("supabase_url is required for Supabase backend")
            if not self.supabase_key:
                raise ValueError("supabase_key is required for Supabase backend")
        
        elif self.backend == "kafka":
            if not self.kafka_brokers:
                raise ValueError("kafka_brokers is required for Kafka backend")


# Global configuration singleton
_config: Optional[TelemetryConfig] = None
_config_lock = threading.Lock()


def configure_telemetry(config: TelemetryConfig) -> None:
    """Set the global telemetry configuration.
    
    Args:
        config: Telemetry configuration
    """
    global _config
    config.validate()
    with _config_lock:
        _config = config


def get_config() -> TelemetryConfig:
    """Get the global telemetry configuration.
    
    If not explicitly configured, attempts to load from environment variables.
    
    Returns:
        Current telemetry configuration
    """
    global _config
    if _config is None:
        with _config_lock:
            if _config is None:
                _config = TelemetryConfig.from_env()
    return _config


def reset_config() -> None:
    """Reset the global telemetry configuration."""
    global _config
    with _config_lock:
        _config = None

