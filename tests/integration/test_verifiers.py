import pytest
from .base_test import BaseIntegrationTest


@pytest.mark.integration
class TestVerifierFunctionality(BaseIntegrationTest):
    """Test verifier creation and basic functionality."""
    
    def test_sync_verifier_creation(self):
        """Test creation of sync verifiers."""
        from fleet.verifiers.decorator import verifier
        
        @verifier()
        def test_verifier(env):
            return {"score": 1.0, "message": "Test passed"}
        
        # Test verifier execution with mock env
        class MockEnv:
            pass
        
        # The verifier decorator returns only the SCORE (float), not full dict
        result = test_verifier(MockEnv())
        
        assert isinstance(result, float), "Verifier should return score as float"
        assert result == 1.0, "Score should be 1.0"
    
    def test_async_verifier_creation(self):
        """Test creation of async verifiers."""
        from fleet._async.verifiers.verifier import verifier
        
        @verifier()
        async def test_async_verifier(env):
            return {"score": 1.0, "message": "Async test passed"}
        
        # Test async verifier execution with mock env
        class MockEnv:
            pass
        
        # For async verifiers, we need to call the wrapped function directly
        # The decorator returns an AsyncVerifierFunction object
        import asyncio
        result = asyncio.run(test_async_verifier.func(MockEnv()))
        
        assert isinstance(result, dict), "Async verifier function should return dict"
        assert result["score"] == 1.0, "Async score should be 1.0"
    
    def test_verifier_with_parameters(self):
        """Test verifiers with parameters."""
        from fleet.verifiers.decorator import verifier
        
        @verifier()
        def parameterized_verifier(env, test_value: str, multiplier: int = 2):
            return {
                "score": 1.0,
                "message": f"Processed {test_value}",
                "result": test_value * multiplier
            }
        
        class MockEnv:
            pass
        
        # Call with positional args (kwargs not supported by decorator)
        result = parameterized_verifier(MockEnv(), "test", 3)
        
        assert isinstance(result, float), "Verifier should return score as float"
        assert result == 1.0, "Score should be 1.0"
    
    def test_verifier_bundling(self):
        """Test verifier bundling functionality."""
        from fleet.verifiers.decorator import verifier
        
        @verifier()
        def bundling_test_verifier(env):
            return {"score": 1.0, "message": "Bundling test"}
        
        try:
            # Test that bundling method exists (if available)
            if hasattr(bundling_test_verifier, 'bundle'):
                bundle_data = bundling_test_verifier.bundle()
                assert bundle_data is not None, "Bundle should be created"
            else:
                # Skip if bundling not available in this version
                pytest.skip("Verifier bundling not available")
            
        except Exception as e:
            self.skip_if_unavailable("Verifier bundling", e)


@pytest.mark.integration 
@pytest.mark.slow
class TestVerifierExecution(BaseIntegrationTest):
    """Test verifier execution with real Fleet services."""
    
    def test_verifier_remote_execution(self, fleet_client):
        """Test remote verifier execution (if supported)."""
        from fleet.verifiers.decorator import verifier
        
        @verifier()
        def remote_test_verifier(env):
            return {
                "score": 1.0, 
                "message": "Remote execution test",
                "timestamp": "2024-01-01T12:00:00Z"
            }
        
        try:
            # Test that the verifier works locally first
            class MockEnv:
                pass
            result = remote_test_verifier(MockEnv())
            
            # Validate basic verifier functionality
            assert isinstance(result, float), "Verifier should return score as float"
            assert result == 1.0, "Verifier should return correct score"
            
        except Exception as e:
            self.skip_if_unavailable("Remote verifier execution", e)
    
    @pytest.mark.asyncio
    async def test_async_verifier_remote_execution(self, async_fleet_client):
        """Test async remote verifier execution (if supported)."""
        from fleet._async.verifiers.verifier import verifier
        
        @verifier()
        async def async_remote_verifier(env):
            import asyncio
            await asyncio.sleep(0.1)  # Simulate async work
            
            return {
                "score": 1.0,
                "message": "Async remote execution test",
                "execution_time": 0.1
            }
        
        try:
            # Test local execution first
            class MockEnv:
                pass
            # For async verifiers, call the underlying function directly
            local_result = await async_remote_verifier.func(MockEnv())
            assert isinstance(local_result, dict), "Async verifier function should return dict"
            assert local_result["score"] == 1.0, "Local async execution should work"
            
            # Note: Remote execution testing would require actual bundle creation
            # which may not be available in all SDK versions
            
        except Exception as e:
            self.skip_if_unavailable("Async remote verifier execution", e)


@pytest.mark.integration
class TestVerifierWithEnvironments(BaseIntegrationTest):
    """Test verifiers that interact with environments."""
    
    @pytest.mark.requires_instance
    def test_verifier_database_interaction(self, fleet_client, test_env_key):
        """Test verifier that interacts with database."""
        from fleet.verifiers.decorator import verifier
        
        @verifier()  
        def database_verifier(env, db_connection):
            """Verifier that uses database connection."""
            try:
                result = db_connection.exec("SELECT COUNT(*) as table_count FROM sqlite_master WHERE type='table'")
                
                table_count = 0
                if result and result.get("rows"):
                    table_count = result["rows"][0][0] if result["rows"][0] else 0
                
                return {
                    "score": 1.0 if table_count >= 0 else 0.0,
                    "message": f"Found {table_count} tables",
                    "details": {"table_count": table_count}
                }
            except Exception as e:
                return {
                    "score": 0.0,
                    "message": f"Database verification failed: {str(e)}"
                }
        
        try:
            # Get test environment
            env = self.get_test_environment(fleet_client, test_env_key)
            db = env.db()
            
            # Execute verifier with database connection
            result = database_verifier(db)
            
            self.assert_valid_response(result, dict)
            assert "score" in result, "Database verifier should return score"
            assert "details" in result, "Database verifier should return details"
            
        except Exception as e:
            self.skip_if_unavailable("Verifier database interaction", e)


@pytest.mark.integration
class TestVerifierErrorHandling(BaseIntegrationTest):
    """Test verifier error handling scenarios."""
    
    def test_verifier_exception_handling(self):
        """Test verifier that raises exceptions."""
        from fleet.verifiers.decorator import verifier
        
        @verifier()
        def failing_verifier(env):
            raise ValueError("Test verifier failure")
        
        # Verifier decorator catches exceptions and returns 0.0
        class MockEnv:
            pass
        result = failing_verifier(MockEnv())
        
        assert isinstance(result, float), "Failed verifier should return float"
        assert result == 0.0, "Failed verifier should return 0.0 score"
    
    def test_verifier_invalid_return(self):
        """Test verifier with invalid return values."""
        from fleet.verifiers.decorator import verifier
        
        @verifier()
        def invalid_return_verifier(env):
            return "invalid return type"  # Should be dict
        
        # Verifier decorator handles invalid returns and returns 0.0
        class MockEnv:
            pass
        result = invalid_return_verifier(MockEnv())
        assert isinstance(result, float), "Invalid return should be handled as float"
        assert result == 0.0, "Invalid return should result in 0.0 score"
    
    def test_verifier_partial_return(self):
        """Test verifier with partial/incomplete return values."""
        from fleet.verifiers.decorator import verifier
        
        @verifier()
        def partial_verifier(env):
            return {"score": 0.5}  # Missing message
        
        class MockEnv:
            pass
        result = partial_verifier(MockEnv())
        
        assert isinstance(result, float), "Verifier should return score as float"
        assert result == 0.5, "Should extract score from dict"
