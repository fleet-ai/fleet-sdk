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
from .client import Fleet, Environment
from ._async.client import AsyncFleet, AsyncEnvironment
from .models import InstanceRequest
from .instance import (
    InstanceClient,
    ResetRequest,
    ResetResponse,
    CDPDescribeResponse,
    ChromeStartRequest,
    ChromeStartResponse,
    ChromeStatusResponse,
)
from ._async.instance import AsyncInstanceClient
from .verifiers import (
    DatabaseSnapshot,
    IgnoreConfig,
    SnapshotDiff,
    TASK_SUCCESSFUL_SCORE,
)
from . import env

# Optional playwright integration
try:
    from .playwright import FleetPlaywrightWrapper
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    FleetPlaywrightWrapper = None
    _PLAYWRIGHT_AVAILABLE = False

__version__ = "0.1.1"
__all__ = [
    "env",
    "FleetError",
    "FleetAPIError",
    "FleetTimeoutError",
    "FleetConfigurationError",
    "Fleet",
    "Environment",
    "AsyncFleet",
    "AsyncEnvironment",
    "InstanceClient",
    "AsyncInstanceClient",
    "InstanceRequest",
    "ResetRequest",
    "ResetResponse",
    "CDPDescribeResponse",
    "ChromeStartRequest",
    "ChromeStartResponse",
    "ChromeStatusResponse",
    "DatabaseSnapshot",
    "IgnoreConfig",
    "SnapshotDiff",
    "TASK_SUCCESSFUL_SCORE",
]

# Add playwright wrapper to exports if available
if _PLAYWRIGHT_AVAILABLE:
    __all__.append("FleetPlaywrightWrapper")