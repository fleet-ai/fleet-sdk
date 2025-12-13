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

"""Telemetry backends for different storage systems."""

from .base import TelemetryBackend
from .noop import NoopBackend
from .supabase import SupabaseBackend

# Kafka is optional - only import if confluent-kafka is installed
try:
    from .kafka import KafkaBackend
    HAS_KAFKA = True
except ImportError:
    KafkaBackend = None  # type: ignore
    HAS_KAFKA = False

__all__ = [
    "TelemetryBackend",
    "NoopBackend",
    "SupabaseBackend",
    "KafkaBackend",
    "HAS_KAFKA",
]

