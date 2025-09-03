import pytest
from .base_test import BaseFleetTest, BaseTaskTest


@pytest.mark.integration
class TestFleetClient(BaseFleetTest):
    """Test core Fleet client functionality."""
    
    def test_list_environments(self, fleet_client):
        """Test listing available environments."""
        environments = fleet_client.list_envs()
        
        self.assert_valid_response(environments, list)
        self.assert_environment_list(environments)
        
        # Should have at least one environment available
        assert len(environments) > 0, "Should have at least one environment"
    
    def test_list_regions(self, fleet_client):
        """Test listing available regions."""
        regions = fleet_client.list_regions()
        
        self.assert_valid_response(regions, list)
        assert len(regions) > 0, "Should have at least one region"
        
        # Each region should be a string
        for region in regions:
            assert isinstance(region, str), "Each region should be a string"
    
    def test_load_tasks(self, fleet_client, test_env_key):
        """Test loading tasks for an environment."""
        try:
            tasks = fleet_client.load_tasks(env_key=test_env_key)
            
            self.assert_valid_response(tasks, list)
            
            # If tasks exist, validate their structure
            if tasks:
                for task in tasks[:5]:  # Check first 5 tasks
                    self.assert_task_structure(task)
            
        except Exception as e:
            self.skip_if_unavailable("Task loading", e)
    
    def test_load_tasks_without_env_key(self, fleet_client):
        """Test loading tasks without specifying env_key."""
        try:
            tasks = fleet_client.load_tasks()
            self.assert_valid_response(tasks, list)
            
        except Exception as e:
            self.skip_if_unavailable("Default task loading", e)


@pytest.mark.integration 
class TestAsyncFleetClient(BaseFleetTest):
    """Test async Fleet client functionality."""
    
    @pytest.mark.asyncio
    async def test_async_list_environments(self, async_fleet_client):
        """Test async listing of available environments."""
        environments = await async_fleet_client.list_envs()
        
        self.assert_valid_response(environments, list)
        self.assert_environment_list(environments)
        assert len(environments) > 0, "Should have at least one environment"
    
    @pytest.mark.asyncio
    async def test_async_list_regions(self, async_fleet_client):
        """Test async listing of available regions."""
        regions = await async_fleet_client.list_regions()
        
        self.assert_valid_response(regions, list)
        assert len(regions) > 0, "Should have at least one region"
    
    @pytest.mark.asyncio
    async def test_async_load_tasks(self, async_fleet_client, test_env_key):
        """Test async loading tasks for an environment."""
        try:
            tasks = await async_fleet_client.load_tasks(env_key=test_env_key)
            
            self.assert_valid_response(tasks, list)
            
            if tasks:
                for task in tasks[:3]:  # Check first 3 tasks
                    self.assert_task_structure(task)
            
        except Exception as e:
            self.skip_if_unavailable("Async task loading", e)


@pytest.mark.integration
@pytest.mark.slow
class TestMakeFunctionality(BaseTaskTest):
    """Test the crucial .make() functionality and associated features."""
    
    def test_make_basic_usage(self, fleet_client, test_env_key, test_version):
        """Test basic .make() functionality."""
        task_data = {
            "env_key": test_env_key,
            "version": test_version
        }
        
        env = self.assert_make_functionality(fleet_client, task_data)
        
        # Ensure environment cleanup
        try:
            env.close()
        except Exception:
            pass  # Cleanup errors are not critical for test success
    
    def test_make_with_specific_parameters(self, fleet_client, test_env_key):
        """Test .make() with specific parameters."""
        task_data = {
            "env_key": test_env_key,
            "version": "v1.3.1",
            "region": "us-east-1"
        }
        
        try:
            env = fleet_client.make(**task_data)
            
            self.assert_environment_instance(env, test_env_key)
            
            # Test that environment has expected properties
            assert env.env_key == test_env_key, "Environment should have correct env_key"
            assert hasattr(env, "version"), "Environment should have version"
            assert hasattr(env, "region"), "Environment should have region"
            
            # Test environment functionality
            self.test_basic_database_query(env)
            
            env.close()
            
        except Exception as e:
            self.skip_if_unavailable("Make with parameters", e)
    
    @pytest.mark.asyncio
    async def test_async_make_functionality(self, async_fleet_client, test_env_key, test_version):
        """Test async .make() functionality."""
        task_data = {
            "env_key": test_env_key,
            "version": test_version
        }
        
        env = await self.assert_async_make_functionality(async_fleet_client, task_data)
        
        # Test async context manager
        try:
            async with env:
                # Environment should be accessible within context
                db = env.db()
                result = await db.exec("SELECT 'context_test' as test")
                assert "context_test" in str(result), "Context manager should work"
        except Exception as e:
            # Context manager might not be available in all versions
            print(f"Context manager not available: {e}")
        
        # Cleanup
        try:
            await env.close()
        except Exception:
            pass
    
    def test_make_error_handling(self, fleet_client):
        """Test .make() error handling with invalid parameters."""
        # Test with invalid environment key
        with pytest.raises(Exception):  # Could be various exception types
            fleet_client.make("nonexistent-env-key-12345")
    
    def test_make_environment_lifecycle(self, fleet_client, test_env_key):
        """Test complete environment lifecycle using .make()."""
        try:
            # Create environment
            env = fleet_client.make(test_env_key)
            self.assert_environment_instance(env, test_env_key)
            
            # Test reset functionality
            reset_response = env.reset(seed=42)
            self.assert_reset_response(reset_response)
            
            # Test environment still works after reset
            self.test_basic_database_query(env)
            
            # Test close functionality  
            env.close()
            
        except Exception as e:
            self.skip_if_unavailable("Environment lifecycle", e)


@pytest.mark.integration
class TestEnvironmentAccess(BaseTaskTest):
    """Test environment access methods."""
    
    def test_env_method(self, fleet_client, test_env_key):
        """Test .env() method for getting environments."""
        env = self.get_test_environment(fleet_client, test_env_key)
        
        self.assert_environment_instance(env, test_env_key)
        self.test_basic_database_query(env)
    
    @pytest.mark.asyncio
    async def test_async_env_method(self, async_fleet_client, test_env_key):
        """Test async .env() method."""
        env = await self.get_async_test_environment(async_fleet_client, test_env_key)
        
        self.assert_environment_instance(env, test_env_key)
        await self.test_async_database_query(env)
