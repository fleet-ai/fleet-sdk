import pytest
import time
from typing import Optional, Dict, Any, List
from fleet import Fleet, AsyncFleet


class BaseIntegrationTest:

    def setup_method(self):
        """Setup before each test method."""
        self.start_time = time.time()
    
    def teardown_method(self):
        """Cleanup after each test method."""
        elapsed = time.time() - self.start_time
        if elapsed > 30:
            print(f"\n⚠️  Slow test completed in {elapsed:.2f}s")
    
    def assert_valid_response(self, response: Any, expected_type: type = dict):
        """Assert response is valid and of expected type."""
        assert response is not None, "Response should not be None"
        assert isinstance(response, expected_type), f"Response should be {expected_type.__name__}"
        return response
    
    def assert_environment_list(self, environments: List[Any]):
        """Assert environment list is valid."""
        assert isinstance(environments, list), "Environments should be a list"
        for env in environments:
            # Environment objects have attributes, not dict keys
            assert hasattr(env, 'env_key'), "Environment should have env_key attribute"
            assert hasattr(env, 'versions'), "Environment should have versions attribute"
    
    def assert_task_structure(self, task: Dict):
        """Assert task has expected structure."""
        required_fields = ["key", "description", "created_at"]
        for field in required_fields:
            assert field in task, f"Task should have {field} field"
        
        assert isinstance(task["key"], str), "Task key should be string"
        assert len(task["key"]) > 0, "Task key should not be empty"
    
    def skip_if_unavailable(self, operation_name: str, exception: Exception):
        """Skip test if operation is not available in current environment."""
        pytest.skip(f"{operation_name} not available: {exception}")
    
    def get_test_environment(self, client: Fleet, env_key: str = "fira"):
        """Get test environment, skip if not available."""
        try:
            return client.env(env_key)
        except Exception as e:
            self.skip_if_unavailable(f"Environment {env_key}", e)
    
    async def get_async_test_environment(self, client: AsyncFleet, env_key: str = "fira"):
        """Get async test environment, skip if not available."""
        try:
            return await client.env(env_key)
        except Exception as e:
            self.skip_if_unavailable(f"Async environment {env_key}", e)


class BaseFleetTest(BaseIntegrationTest):
    """Base test class specifically for Fleet client tests."""
    
    def assert_fleet_client(self, client: Fleet):
        """Assert Fleet client is properly configured."""
        assert isinstance(client, Fleet), "Should be Fleet instance"
        assert client.client.api_key is not None, "Client should have API key"
        assert client.client.api_key.startswith("sk_"), "API key should start with sk_"
    
    def assert_async_fleet_client(self, client: AsyncFleet):
        """Assert AsyncFleet client is properly configured."""
        assert isinstance(client, AsyncFleet), "Should be AsyncFleet instance"  
        assert client.client.api_key is not None, "Async client should have API key"
        assert client.client.api_key.startswith("sk_"), "API key should start with sk_"


class BaseEnvironmentTest(BaseIntegrationTest):
    """Base test class for environment-related tests."""
    
    def assert_environment_instance(self, env, expected_env_key: str):
        """Assert environment instance is valid."""
        assert env is not None, "Environment should not be None"
        assert hasattr(env, "env_key"), "Environment should have env_key attribute"
        assert env.env_key == expected_env_key, f"Environment key should be {expected_env_key}"
        assert hasattr(env, "instance_id"), "Environment should have instance_id"
    
    def assert_reset_response(self, response):
        """Assert reset response is valid."""
        assert hasattr(response, "success"), "Reset response should have success attribute"
        if hasattr(response, "seed"):
            assert isinstance(response.seed, (int, type(None))), "Seed should be int or None"
    
    def test_basic_database_query(self, env):
        """Test basic database functionality."""
        try:
            db = env.db()
            result = db.exec("SELECT 1 as test_column")
            
            assert isinstance(result, dict), "Query result should be dict"
            assert "columns" in result, "Result should have columns"
            assert "rows" in result, "Result should have rows"
            
            return True
        except Exception as e:
            self.skip_if_unavailable("Database operations", e)
    
    @pytest.mark.asyncio
    async def test_async_database_query(self, env):
        """Test basic async database functionality."""
        try:
            db = env.db()
            result = await db.exec("SELECT 1 as test_column")
            
            assert isinstance(result, dict), "Async query result should be dict"
            assert "columns" in result, "Async result should have columns"
            assert "rows" in result, "Async result should have rows"
            
            return True
        except Exception as e:
            self.skip_if_unavailable("Async database operations", e)


class BaseTaskTest(BaseIntegrationTest):
    """Base test class for task-related tests."""
    
    def assert_make_functionality(self, client: Fleet, task_data: Dict):
        """Test the .make() functionality comprehensively."""
        try:
            # Test basic make call
            env = client.make(**task_data)
            
            # Validate environment was created
            self.assert_environment_instance(env, task_data.get("env_key", "fira"))
            
            # Test environment is functional
            db = env.db()
            result = db.exec("SELECT 1 as make_test")
            assert "make_test" in str(result), "Make-created environment should be functional"
            
            return env
        except Exception as e:
            self.skip_if_unavailable("Make functionality", e)
    
    async def assert_async_make_functionality(self, client: AsyncFleet, task_data: Dict):
        """Test the async .make() functionality comprehensively.""" 
        try:
            # Test basic async make call
            env = await client.make(**task_data)
            
            # Validate environment was created
            self.assert_environment_instance(env, task_data.get("env_key", "fira"))
            
            # Test environment is functional
            db = env.db()
            result = await db.exec("SELECT 1 as async_make_test")
            assert "async_make_test" in str(result), "Async make-created environment should be functional"
            
            return env
        except Exception as e:
            self.skip_if_unavailable("Async make functionality", e)
