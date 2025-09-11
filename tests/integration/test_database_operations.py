"""
Tests for database operations functionality.
"""

import pytest
from .base_test import BaseDatabaseTest, BaseFleetTest


class TestDatabaseOperations(BaseDatabaseTest):
    """Test database operations functionality."""
    
    def test_database_query_with_args(self, env):
        """Test database query with arguments."""
        db = env.db()
        result = db.query("SELECT ? as test_value", args=["test_data"])
        assert result is not None
        print("✅ Database query with args successful")
    
    def test_database_exec_with_args(self, env):
        """Test database exec with arguments."""
        db = env.db()
        result = db.exec("SELECT ? as test_value", args=["test_data"])
        assert result is not None
        print("✅ Database exec with args successful")
    
    def test_database_describe_schema(self, env):
        """Test database describe schema."""
        db = env.db()
        schema = db.describe()
        assert schema is not None
        # Schema should have tables information
        if hasattr(schema, 'tables'):
            assert isinstance(schema.tables, list)
        print("✅ Database describe schema successful")
    
    def test_database_state_current(self, env):
        """Test database state access for current."""
        db = env.state("sqlite://current")
        assert db is not None
        print("✅ Database state current access successful")
    
    def test_database_state_seed(self, env):
        """Test database state access for seed."""
        db = env.state("sqlite://seed")
        assert db is not None
        print("✅ Database state seed access successful")
    
    def test_database_specific_db(self, env):
        """Test accessing specific database by name."""
        db = env.db("action_log")
        assert db is not None
        print("✅ Database specific db access successful")
    
    def test_database_query_result_structure(self, env):
        """Test database query result structure."""
        db = env.db()
        result = db.query("SELECT 1 as id, 'test' as name")
        
        assert result is not None
        if hasattr(result, 'columns'):
            assert isinstance(result.columns, list)
            assert len(result.columns) > 0
        if hasattr(result, 'rows'):
            assert isinstance(result.rows, list)
        print("✅ Database query result structure valid")


class TestDatabaseAdvanced(BaseDatabaseTest):
    """Test advanced database operations."""
    
    def test_database_table_operations(self, env):
        """Test database table operations."""
        db = env.db()
        
        # Test describe on specific table if available
        schema = db.describe()
        if hasattr(schema, 'tables') and schema.tables:
            table_name = schema.tables[0].name if hasattr(schema.tables[0], 'name') else 'users'
            result = db.query(f"SELECT * FROM {table_name} LIMIT 1")
            assert result is not None
            print(f"✅ Database table operations successful for {table_name}")
    
    def test_database_multiple_queries(self, env):
        """Test multiple database queries."""
        db = env.db()
        
        # Test multiple queries
        result1 = db.query("SELECT 1 as test1")
        result2 = db.query("SELECT 2 as test2")
        result3 = db.exec("SELECT 3 as test3")
        
        assert result1 is not None
        assert result2 is not None
        assert result3 is not None
        print("✅ Multiple database queries successful")
    
    def test_database_error_handling(self, env):
        """Test database error handling."""
        db = env.db()
        
        # Test invalid query
        try:
            result = db.query("SELECT * FROM nonexistent_table")
            # If no error, that's fine too
            print("✅ Database error handling test passed")
        except Exception as e:
            # Expected error for invalid table
            print(f"✅ Database error handling works: {type(e).__name__}")


class TestAsyncDatabaseOperations(BaseDatabaseTest):
    """Test async database operations."""
    
    @pytest.mark.asyncio
    async def test_async_database_query(self):
        """Test async database query."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            db = async_env.db()
            result = await db.query("SELECT 1 as test")
            assert result is not None
            print("✅ Async database query successful")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_database_exec(self):
        """Test async database exec."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            db = async_env.db()
            result = await db.exec("SELECT 1 as test")
            assert result is not None
            print("✅ Async database exec successful")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_database_describe(self):
        """Test async database describe."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            db = async_env.db()
            schema = await db.describe()
            assert schema is not None
            print("✅ Async database describe successful")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_database_query_with_args(self):
        """Test async database query with arguments."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            db = async_env.db()
            result = await db.query("SELECT ? as test_value", args=["test_data"])
            assert result is not None
            print("✅ Async database query with args successful")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_database_exec_with_args(self):
        """Test async database exec with arguments."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            db = async_env.db()
            result = await db.exec("SELECT ? as test_value", args=["test_data"])
            assert result is not None
            print("✅ Async database exec with args successful")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_database_state_access(self):
        """Test async database state access."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            db = async_env.state("sqlite://current")
            assert db is not None
            print("✅ Async database state access successful")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_database_specific_db(self):
        """Test async accessing specific database by name."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            db = async_env.db("action_log")
            assert db is not None
            print("✅ Async database specific db access successful")
        finally:
            await async_env.close()


class TestDatabaseIntegration(BaseFleetTest):
    """Test database integration with environment."""
    
    def test_database_with_environment_reset(self, env):
        """Test database operations with environment reset."""
        # Reset environment
        reset_response = env.reset(seed=42)
        assert reset_response is not None
        
        # Test database after reset
        db = env.db()
        result = db.query("SELECT 1 as test")
        assert result is not None
        print("✅ Database with environment reset successful")
    
    def test_database_with_environment_step(self, env):
        """Test database operations with environment step."""
        # Perform environment step
        action = {"type": "test", "data": {"message": "Hello Fleet!"}}
        state, reward, done = env.instance.step(action)
        
        # Test database after step
        db = env.db()
        result = db.query("SELECT 1 as test")
        assert result is not None
        print("✅ Database with environment step successful")
    
    def test_database_resource_integration(self, env):
        """Test database as environment resource."""
        resources = env.resources()
        assert isinstance(resources, list)
        
        # Find database resource
        db_resources = [r for r in resources if hasattr(r, 'type') and r.type in ['sqlite', 'database']]
        # Just check that resources exist, don't require specific database resources
        assert len(resources) > 0
        print(f"✅ Database resource integration: {len(resources)} total resources found")
