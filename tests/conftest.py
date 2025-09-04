"""
Pytest configuration and shared fixtures for Fleet SDK integration tests.
"""

import pytest
import os
import sys
from typing import List

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--api-key",
        action="store",
        default=None,
        help="Fleet API key for integration tests"
    )

def pytest_collection_modifyitems(config, items):
    """Mark tests based on command line options."""
    api_key = config.getoption("--api-key")
    
    for item in items:
        # Mark all integration tests
        item.add_marker(pytest.mark.integration)
        
        # Skip slow tests by default unless explicitly requested
        if "slow" in item.keywords:
            item.add_marker(pytest.mark.slow)

@pytest.fixture
def api_key(request):
    """Get API key from command line or environment variable."""
    api_key = request.config.getoption("--api-key")
    if api_key is None:
        api_key = os.getenv("FLEET_API_KEY")
    return api_key

@pytest.fixture
def test_env_key():
    """Get test environment key with fallback options."""
    # Use user-defined test environment if available
    user_env = os.getenv("FLEET_TEST_ENV_KEY")
    if user_env:
        return user_env
    
    # Fallback to available environments
    available_envs = [
        "dropbox:Forge1.1.0",
        "hubspot:Forge1.1.0", 
        "ramp:Forge1.1.0"
    ]
    
    # Return first available environment
    return available_envs[0]

@pytest.fixture
def fleet_client(api_key):
    """Create Fleet client for testing."""
    if not api_key:
        pytest.skip("API key required for integration tests")
    
    from fleet import Fleet
    return Fleet(api_key=api_key)

@pytest.fixture
def async_fleet_client(api_key):
    """Create async Fleet client for testing."""
    if not api_key:
        pytest.skip("API key required for integration tests")
    
    from fleet import AsyncFleet
    return AsyncFleet(api_key=api_key)

@pytest.fixture
def env(fleet_client, test_env_key):
    """Create environment instance for testing."""
    env = None
    try:
        env = fleet_client.make(test_env_key)
        yield env
    finally:
        if env and hasattr(env, 'close'):
            env.close()
        elif env and hasattr(env, 'instance') and hasattr(env.instance, 'terminate'):
            env.instance.terminate()

@pytest.fixture
async def async_env(async_fleet_client, test_env_key):
    """Create async environment instance for testing."""
    try:
        env = await async_fleet_client.make(test_env_key)
        yield env
    finally:
        if hasattr(env, 'close'):
            await env.close()
        elif hasattr(env, 'instance') and hasattr(env.instance, 'terminate'):
            await env.instance.terminate()
