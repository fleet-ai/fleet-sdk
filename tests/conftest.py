"""
Pytest configuration and shared fixtures for Fleet SDK integration tests.
"""

import os
import sys
import pytest
from pathlib import Path

# Ensure we're testing the local SDK version, not installed one
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import fleet
from fleet import Fleet, AsyncFleet


def pytest_addoption(parser):
    """Add command line options."""
    parser.addoption(
        "--api-key", 
        action="store", 
        help="Fleet API key for integration tests"
    )


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "integration: integration tests with real API calls")
    config.addinivalue_line("markers", "slow: slow running tests")
    config.addinivalue_line("markers", "requires_instance: tests requiring environment instance")


@pytest.fixture(scope="session")
def api_key(request):
    """Get API key from environment or command line."""
    # Try command line first
    api_key_value = request.config.getoption("--api-key")
    
    # Fall back to environment variable
    if not api_key_value:
        api_key_value = os.getenv("FLEET_API_KEY")
    
    if not api_key_value:
        pytest.skip("No API key provided. Set FLEET_API_KEY environment variable or use --api-key option")
    
    return api_key_value


@pytest.fixture(scope="session")
def fleet_client(api_key):
    """Create sync Fleet client for testing."""
    return Fleet(api_key=api_key)


@pytest.fixture(scope="session") 
def async_fleet_client(api_key):
    """Create async Fleet client for testing."""
    return AsyncFleet(api_key=api_key)


@pytest.fixture(scope="session")
def test_env_key():
    """Default environment key for testing."""
    return os.getenv("FLEET_TEST_ENV_KEY", "fira")


@pytest.fixture(scope="session")
def test_version():
    """Default version for testing."""
    return os.getenv("FLEET_TEST_VERSION", "v1.3.1")


@pytest.fixture(scope="function")
def env(fleet_client, test_env_key):
    """Create a Fleet environment for testing."""
    try:
        environment = fleet_client.make(test_env_key)
        yield environment
    finally:
        # Cleanup: terminate the environment
        try:
            environment.instance.terminate()
        except Exception:
            pass  # Ignore cleanup errors


@pytest.fixture(scope="function")
async def async_env(async_fleet_client, test_env_key):
    """Create an async Fleet environment for testing."""
    try:
        environment = await async_fleet_client.make(test_env_key)
        yield environment
    finally:
        # Cleanup: terminate the environment
        try:
            await environment.instance.terminate()
        except Exception:
            pass  # Ignore cleanup errors
