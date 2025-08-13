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
    FleetRateLimitError,
    FleetInstanceLimitError,
    FleetConfigurationError,
)
from .client import Fleet, SyncEnv
from ._async.client import AsyncFleet, AsyncEnv
from .models import InstanceResponse
from .instance.models import Resource, ResetResponse

# Import sync verifiers with explicit naming
from .verifiers import (
    verifier as verifier_sync,
    SyncVerifierFunction,
    DatabaseSnapshot,
    IgnoreConfig,
    SnapshotDiff,
    TASK_FAILED_SCORE,
    TASK_SUCCESSFUL_SCORE,
)

# Import async verifiers (default verifier is async for modern usage)
from ._async.verifiers import (
    verifier,
    AsyncVerifierFunction,
)

# Import async tasks (default tasks are async for modern usage)
from ._async.tasks import Task

# Import shared types
from .types import VerifierFunction

# Create a module-level env attribute for convenient access
from . import env

__version__ = "0.1.0"

__all__ = [
    # Core classes
    "Fleet",
    "SyncEnv",
    "AsyncFleet",
    "AsyncEnv",
    # Models
    "InstanceRecord", 
    "Resource",
    "ResetResponse",
    # Task models
    "Task",
    "VerifierFunction",
    # Exceptions
    "FleetError",
    "FleetAPIError", 
    "FleetTimeoutError",
    "FleetConfigurationError",
    # Verifiers (async is default)
    "verifier",
    "verifier_sync", 
    "AsyncVerifierFunction",
    "SyncVerifierFunction",
    "DatabaseSnapshot",
    "IgnoreConfig", 
    "SnapshotDiff",
    "TASK_FAILED_SCORE",
    "TASK_SUCCESSFUL_SCORE",
    # Environment module
    "env",
    # Version
    "__version__",
]