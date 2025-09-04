"""
Base test classes for Fleet SDK integration tests.
"""

import pytest
from typing import Any, Dict, List, Optional
from fleet import Fleet, AsyncFleet


class BaseFleetTest:
    """Base class for Fleet SDK tests."""
    
    def assert_valid_response(self, response: Any, expected_type: Optional[type] = None) -> None:
        """Assert that a response is valid."""
        assert response is not None
        if expected_type:
            assert isinstance(response, expected_type)
    
    def assert_environment_list(self, environments: List) -> None:
        """Assert that environment list is valid."""
        assert isinstance(environments, list)
        assert len(environments) > 0
        for env in environments:
            # Check for either 'key' or 'env_key' attribute
            assert hasattr(env, 'key') or hasattr(env, 'env_key')
            assert hasattr(env, 'name')
            assert hasattr(env, 'default_version')
    
    def assert_instance_valid(self, instance) -> None:
        """Assert that an instance is valid."""
        assert hasattr(instance, 'instance_id')
        assert hasattr(instance, 'env_key')
        assert hasattr(instance, 'status')
        assert instance.instance_id is not None


class BaseEnvironmentTest(BaseFleetTest):
    """Base class for environment-related tests."""
    
    def test_environment_creation(self, fleet_client, test_env_key):
        """Test basic environment creation."""
        env = fleet_client.make(test_env_key)
        self.assert_instance_valid(env)
        assert env.env_key in test_env_key
        print(f"✅ Created environment: {env.instance_id}")
    
    def test_environment_resources(self, env):
        """Test accessing environment resources."""
        resources = env.resources()
        assert isinstance(resources, list)
        assert len(resources) > 0
        print(f"✅ Environment has {len(resources)} resources")
    
    def test_environment_reset(self, env):
        """Test environment reset functionality."""
        response = env.reset(seed=42)
        assert response is not None
        print("✅ Environment reset successful")
    
    def test_environment_step(self, env):
        """Test environment step functionality."""
        action = {"type": "test", "data": {"message": "Hello Fleet!"}}
        state, reward, done = env.instance.step(action)
        assert isinstance(reward, (int, float))
        assert isinstance(done, bool)
        print(f"✅ Environment step successful - reward: {reward}, done: {done}")


class BaseDatabaseTest(BaseFleetTest):
    """Base class for database-related tests."""
    
    def test_database_access(self, env):
        """Test database resource access."""
        db = env.db()
        assert db is not None
        print("✅ Database access successful")
    
    def test_database_describe(self, env):
        """Test database describe functionality."""
        db = env.db()
        schema = db.describe()
        assert schema is not None
        print("✅ Database describe successful")
    
    def test_database_query(self, env):
        """Test database query functionality."""
        db = env.db()
        result = db.query("SELECT 1 as test")
        assert result is not None
        print("✅ Database query successful")
    
    def test_database_exec(self, env):
        """Test database exec functionality."""
        db = env.db()
        result = db.exec("SELECT 1 as test")
        assert result is not None
        print("✅ Database exec successful")
    
    def test_database_state_access(self, env):
        """Test database state access."""
        db = env.state("sqlite://current")
        assert db is not None
        print("✅ Database state access successful")


class BaseBrowserTest(BaseFleetTest):
    """Base class for browser-related tests."""
    
    def test_browser_access(self, env):
        """Test browser resource access."""
        browser = env.browser()
        assert browser is not None
        print("✅ Browser access successful")
    
    def test_browser_cdp_url(self, env):
        """Test browser CDP URL access."""
        browser = env.browser()
        cdp_url = browser.cdp_url()
        assert cdp_url is not None
        assert isinstance(cdp_url, str)
        print("✅ Browser CDP URL successful")
    
    def test_browser_devtools_url(self, env):
        """Test browser devtools URL access."""
        browser = env.browser()
        devtools_url = browser.devtools_url()
        assert devtools_url is not None
        assert isinstance(devtools_url, str)
        print("✅ Browser devtools URL successful")


class BaseVerifierTest(BaseFleetTest):
    """Base class for verifier-related tests."""
    
    def test_verifier_decorator(self):
        """Test verifier decorator functionality."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_verifier")
        def test_verifier_func(env, test_param: str = "test") -> float:
            return 1.0 if test_param == "test" else 0.0
        
        assert hasattr(test_verifier_func, 'key')
        assert test_verifier_func.key == "test_verifier"
        print("✅ Verifier decorator works")
    
    def test_verifier_execution(self):
        """Test verifier execution."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_execution")
        def test_verifier_func(env, test_param: str = "test") -> float:
            return 1.0 if test_param == "test" else 0.0
        
        # Mock environment for testing
        class MockEnv:
            pass
        
        result = test_verifier_func(MockEnv(), "test")
        assert result == 1.0
        print("✅ Verifier execution works")


class BaseAsyncTest(BaseFleetTest):
    """Base class for async tests."""
    
    @pytest.mark.asyncio
    async def test_async_environment_creation(self, async_fleet_client, test_env_key):
        """Test async environment creation."""
        env = await async_fleet_client.make(test_env_key)
        self.assert_instance_valid(env)
        assert env.env_key in test_env_key
        print(f"✅ Created async environment: {env.instance_id}")
    
    @pytest.mark.asyncio
    async def test_async_database_operations(self, async_env):
        """Test async database operations."""
        db = async_env.db()
        schema = await db.describe()
        assert schema is not None
        
        result = await db.query("SELECT 1 as test")
        assert result is not None
        print("✅ Async database operations work")
    
    @pytest.mark.asyncio
    async def test_async_browser_operations(self, async_env):
        """Test async browser operations."""
        browser = async_env.browser()
        cdp_url = await browser.cdp_url()
        devtools_url = await browser.devtools_url()
        
        assert cdp_url is not None
        assert devtools_url is not None
        print("✅ Async browser operations work")
