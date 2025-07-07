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

from . import env
from .exceptions import FleetError, FleetAPIError, FleetTimeoutError, FleetConfigurationError
from .config import get_config, FleetConfig
from .client import FleetAPIClient, InstanceRequest, InstanceResponse, EnvDetails as APIEnvironment, HealthResponse, ManagerURLs, InstanceURLs
from .manager_client import FleetManagerClient, ManagerHealthResponse, TimestampResponse

__version__ = "0.1.1"
__all__ = [
    "env",
    "FleetError",
    "FleetAPIError", 
    "FleetTimeoutError",
    "FleetConfigurationError",
    "get_config",
    "FleetConfig",
    "FleetAPIClient",
    "InstanceRequest",
    "InstanceResponse",
    "APIEnvironment",
    "HealthResponse",
    "ManagerURLs",
    "InstanceURLs",
    "FleetManagerClient",
    "ManagerHealthResponse",
    "TimestampResponse",
] 