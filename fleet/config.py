DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 300.0

# Instance creates can legitimately take several minutes (node launch, image
# pull, seed hydration), so they get their own HTTP budget instead of
# DEFAULT_TIMEOUT. The server is told to wait CREATE_MAX_WAIT_MARGIN_S less
# than the client so slow creates come back as responses, not read timeouts.
DEFAULT_CREATE_TIMEOUT = 900.0
CREATE_MAX_WAIT_MARGIN_S = 30

GLOBAL_BASE_URL = "https://orchestrator.fleetai.com"
REGION_BASE_URL = {
    "us-west-1": "https://us-west-1.fleetai.com",
    "us-east-1": "https://us-east-1.fleetai.com",
    "eu-west-2": "https://eu-west-2.fleetai.com",
    "staging": "https://staging.fleetai.com",
}