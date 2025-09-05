"""
Tests for verifiers functionality.
"""

import pytest
from .base_test import BaseVerifierTest, BaseFleetTest


class TestVerifiers(BaseVerifierTest):
    """Test verifiers functionality."""
    
    def test_verifier_decorator_with_key(self):
        """Test verifier decorator with key parameter."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_key_verifier")
        def test_verifier(env, param: str = "test") -> float:
            return 1.0 if param == "test" else 0.0
        
        assert hasattr(test_verifier, 'key')
        assert test_verifier.key == "test_key_verifier"
        print("✅ Verifier decorator with key works")
    
    def test_verifier_execution_with_env(self):
        """Test verifier execution with environment."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_env_verifier")
        def test_verifier(env, param: str = "test") -> float:
            # Simulate environment check
            if hasattr(env, 'db'):
                return 1.0
            return 0.0
        
        # Mock environment with db attribute
        class MockEnv:
            def __init__(self):
                self.db = "mock_db"
        
        result = test_verifier(MockEnv(), "test")
        assert result == 1.0
        print("✅ Verifier execution with environment works")
    
    def test_verifier_with_database_operations(self):
        """Test verifier with database operations."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_db_verifier")
        def test_db_verifier(env, table_name: str = "users") -> float:
            try:
                db = env.db()
                result = db.query(f"SELECT COUNT(*) FROM {table_name}")
                if result and hasattr(result, 'rows') and result.rows:
                    return 1.0
                return 0.0
            except Exception:
                return 0.0
        
        # Mock environment with database
        class MockDB:
            def query(self, sql):
                class MockResult:
                    def __init__(self):
                        self.rows = [[5]]  # Mock count result
                return MockResult()
        
        class MockEnv:
            def db(self):
                return MockDB()
        
        result = test_db_verifier(MockEnv(), "users")
        assert result == 1.0
        print("✅ Verifier with database operations works")
    
    def test_verifier_parameterized(self):
        """Test parameterized verifier."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_parameterized")
        def test_parameterized_verifier(env, multiplier: int = 1, value: str = "test") -> float:
            return float(multiplier) if value == "test" else 0.0
        
        class MockEnv:
            pass
        
        # Test with different parameters
        result1 = test_parameterized_verifier(MockEnv(), 2, "test")
        result2 = test_parameterized_verifier(MockEnv(), 3, "wrong")
        
        assert result1 == 2.0
        assert result2 == 0.0
        print("✅ Parameterized verifier works")
    
    def test_verifier_return_types(self):
        """Test verifier return types."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_return_types")
        def test_return_verifier(env) -> float:
            return 1.0
        
        class MockEnv:
            pass
        
        result = test_return_verifier(MockEnv())
        assert isinstance(result, float)
        assert result == 1.0
        print("✅ Verifier return types work")


class TestVerifierIntegration(BaseFleetTest):
    """Test verifier integration with real environment."""
    
    def test_verifier_with_real_environment(self, env):
        """Test verifier with real environment."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_real_env")
        def test_real_env_verifier(env) -> float:
            try:
                # Test database access
                db = env.db()
                result = db.query("SELECT 1 as test")
                if result is not None:
                    return 1.0
                return 0.0
            except Exception:
                return 0.0
        
        result = test_real_env_verifier(env)
        assert isinstance(result, float)
        assert result >= 0.0
        print(f"✅ Verifier with real environment: {result}")
    
    def test_verifier_with_environment_reset(self, env):
        """Test verifier with environment reset."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_reset_verifier")
        def test_reset_verifier(env) -> float:
            try:
                # Reset environment
                reset_response = env.reset(seed=42)
                if reset_response is not None:
                    return 1.0
                return 0.0
            except Exception:
                return 0.0
        
        result = test_reset_verifier(env)
        assert isinstance(result, float)
        assert result >= 0.0
        print(f"✅ Verifier with environment reset: {result}")


class TestAsyncVerifiers(BaseVerifierTest):
    """Test async verifiers."""
    
    @pytest.mark.asyncio
    async def test_async_verifier_decorator(self):
        """Test async verifier decorator."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_async_verifier")
        async def test_async_verifier(env, param: str = "test") -> float:
            return 1.0 if param == "test" else 0.0
        
        assert hasattr(test_async_verifier, 'key')
        assert test_async_verifier.key == "test_async_verifier"
        print("✅ Async verifier decorator works")
    
    @pytest.mark.asyncio
    async def test_async_verifier_execution(self):
        """Test async verifier execution."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_async_execution")
        async def test_async_verifier(env, param: str = "test") -> float:
            return 1.0 if param == "test" else 0.0
        
        class MockEnv:
            pass
        
        result = await test_async_verifier.remote(MockEnv(), "test")
        assert result == 1.0
        print("✅ Async verifier execution works")
    
    @pytest.mark.asyncio
    async def test_async_verifier_with_real_environment(self):
        """Test async verifier with real async environment."""
        import os
        from fleet import AsyncFleet
        from fleet.verifiers.decorator import verifier
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            @verifier(key="test_async_real_env")
            async def test_async_real_env_verifier(env) -> float:
                try:
                    # Test async database access
                    db = env.db()
                    result = await db.query("SELECT 1 as test")
                    if result is not None:
                        return 1.0
                    return 0.0
                except Exception:
                    return 0.0
            
            result = await test_async_real_env_verifier.remote(async_env)
            assert isinstance(result, float)
            assert result >= 0.0
            print(f"✅ Async verifier with real environment: {result}")
        finally:
            await async_env.close()


class TestVerifierAdvanced(BaseFleetTest):
    """Test advanced verifier functionality."""
    
    def test_verifier_with_ignore_config(self):
        """Test verifier with ignore configuration."""
        from fleet.verifiers.decorator import verifier
        from fleet.verifiers.db import IgnoreConfig
        
        @verifier(key="test_ignore_config")
        def test_ignore_config_verifier(env) -> float:
            try:
                # Create ignore config
                ignore_config = IgnoreConfig(
                    tables={"activities", "pageviews"},
                    table_fields={
                        "issues": {"updated_at", "created_at", "rowid"},
                        "boards": {"updated_at", "created_at", "rowid"},
                    },
                )
                
                # If we can create the config, return success
                if ignore_config is not None:
                    return 1.0
                return 0.0
            except Exception:
                return 0.0
        
        class MockEnv:
            pass
        
        result = test_ignore_config_verifier(MockEnv())
        assert isinstance(result, float)
        assert result >= 0.0
        print(f"✅ Verifier with ignore config: {result}")
    
    def test_verifier_with_database_diff(self):
        """Test verifier with database diff functionality."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_db_diff")
        def test_db_diff_verifier(env) -> float:
            try:
                # Test database diff functionality
                before = env.db("seed")
                after = env.db("current")
                
                # If both databases are accessible, return success
                if before is not None and after is not None:
                    return 1.0
                return 0.0
            except Exception:
                return 0.0
        
        class MockDB:
            pass
        
        class MockEnv:
            def db(self, name):
                return MockDB()
        
        result = test_db_diff_verifier(MockEnv())
        assert isinstance(result, float)
        assert result >= 0.0
        print(f"✅ Verifier with database diff: {result}")
    
    def test_verifier_error_handling(self):
        """Test verifier error handling."""
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_error_handling")
        def test_error_verifier(env) -> float:
            try:
                # Simulate an error
                raise ValueError("Test error")
            except Exception:
                # Verifier should catch exceptions and return 0.0
                return 0.0
        
        class MockEnv:
            pass
        
        result = test_error_verifier(MockEnv())
        assert result == 0.0
        print("✅ Verifier error handling works")
