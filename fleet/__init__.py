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
from .client import Fleet, AsyncFleet, InstanceRequest
from .env import (
    ResetRequest,
    ResetResponse,
    CDPDescribeResponse,
    ChromeStartRequest,
    ChromeStartResponse,
    ChromeStatusResponse,
)

__version__ = "0.1.1"
__all__ = [
    "env",
    "FleetError",
    "FleetAPIError",
    "FleetTimeoutError",
    "FleetConfigurationError",
    "Fleet",
    "AsyncFleet",
    "InstanceRequest",
    "ResetRequest",
    "ResetResponse",
    "CDPDescribeResponse",
    "ChromeStartRequest",
    "ChromeStartResponse",
    "ChromeStatusResponse",
]
