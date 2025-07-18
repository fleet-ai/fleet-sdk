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

"""Fleet Python SDK - Environment-based AI agent interactions."""

from .exceptions import (
    FleetError,
    FleetAPIError,
    FleetTimeoutError,
    FleetConfigurationError,
)
from .client import Fleet, Environment
from .models import InstanceRecord
from .instance.models import Resource, ResetResponse
from .verifiers import (
    verifier,
    SyncVerifiedFunction,
    DatabaseSnapshot,
    IgnoreConfig,
    SnapshotDiff,
    TASK_SUCCESSFUL_SCORE,
)

# Create a module-level env attribute for convenient access
from . import env

__version__ = "0.1.0"

__all__ = [
    # Core classes
    "Fleet",
    "Environment",
    # Models
    "InstanceRecord", 
    "Resource",
    "ResetResponse",
    # Exceptions
    "FleetError",
    "FleetAPIError", 
    "FleetTimeoutError",
    "FleetConfigurationError",
    # Verifiers
    "verifier",
    "SyncVerifiedFunction",
    "DatabaseSnapshot",
    "IgnoreConfig", 
    "SnapshotDiff",
    "TASK_SUCCESSFUL_SCORE",
    # Environment module
    "env",
    # Version
    "__version__",
]