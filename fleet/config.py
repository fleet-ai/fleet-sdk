DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 300.0

GLOBAL_BASE_URL = "https://orchestrator.fleetai.com"
REGION_BASE_URL = {
    "us-west-1": "https://us-west-1.fleetai.com",
    "us-east-1": "https://us-east-1.fleetai.com",
    "eu-west-2": "https://eu-west-2.fleetai.com",
    "staging": "https://staging.fleetai.com",
}

# Re-export telemetry config for convenience
from .telemetry.config import TelemetryConfig, configure_telemetry, get_config as get_telemetry_config