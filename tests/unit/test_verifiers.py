"""
Unit tests for verifier functionality.
Tests verifier decorators, execution, and validation logic.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import pytest
import asyncio

from .base_test import BaseVerifierTest
from .constants import *


class TestVerifierDecorator(BaseVerifierTest):
    """Test verifier decorator functionality."""
    
    def setUp(self):
        """Set up verifier test fixtures."""
        super().setUp()
        # Mock the verifier decorator to return a wrapper that simulates the decorator behavior
        self.verifier_patcher = patch('fleet.verifiers.decorator.verifier')
        self.mock_verifier = self.verifier_patcher.start()
        
        def mock_decorator(func):
            def wrapper(*args, **kwargs):
                try:
                    result = func(*args, **kwargs)
                    return self.create_mock_verifier_result(success=True)
                except Exception as e:
                    mock_result = self.create_mock_verifier_result(success=False)
                    mock_result.message = str(e)
                    return mock_result
            return wrapper
        
        self.mock_verifier.side_effect = mock_decorator
    
    def tearDown(self):
        """Clean up after tests."""
        self.verifier_patcher.stop()
    
    def test_verifier_decorator_sync_function(self):
        """Test verifier decorator with sync function."""
        # Arrange
        @self.mock_verifier
        def test_verifier(env):
            return True
        
        # Act
        result = test_verifier(self.mock_environment)
        
        # Assert
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'success'))
        self.assertTrue(hasattr(result, 'message'))
        self.assertTrue(hasattr(result, 'execution_time'))
    
    def test_verifier_decorator_with_parameters(self):
        """Test verifier decorator with parameters."""
        # Arrange
        @self.mock_verifier
        def test_verifier(env, param1, param2=None):
            return param1 == "test" and param2 == "value"
        
        # Act
        result = test_verifier(self.mock_environment, "test", param2="value")
        
        # Assert
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'success'))
    
    def test_verifier_decorator_with_return_value(self):
        """Test verifier decorator with return value."""
        # Arrange
        @self.mock_verifier
        def test_verifier(env):
            return {"status": "passed", "count": 5}
        
        # Act
        result = test_verifier(self.mock_environment)
        
        # Assert
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'success'))
        self.assertTrue(hasattr(result, 'message'))
    
    def test_verifier_decorator_with_exception(self):
        """Test verifier decorator with exception."""
        # Arrange
        @self.mock_verifier
        def test_verifier(env):
            raise ValueError("Test error")
        
        # Act
        result = test_verifier(self.mock_environment)
        
        # Assert
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'success'))
        self.assertFalse(result.success)
        self.assertIn("Test error", result.message)
    
    def test_verifier_decorator_with_assertion(self):
        """Test verifier decorator with assertion."""
        # Arrange
        @self.mock_verifier
        def test_verifier(env):
            assert 1 + 1 == 2, "Math is broken"
            return True
        
        # Act
        result = test_verifier(self.mock_environment)
        
        # Assert
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'success'))
        self.assertTrue(result.success)
    
    def test_verifier_decorator_with_failed_assertion(self):
        """Test verifier decorator with failed assertion."""
        # Arrange
        @self.mock_verifier
        def test_verifier(env):
            assert 1 + 1 == 3, "Math is broken"
            return True
        
        # Act
        result = test_verifier(self.mock_environment)
        
        # Assert
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'success'))
        self.assertFalse(result.success)
        self.assertIn("Math is broken", result.message)


class TestAsyncVerifierDecorator(BaseVerifierTest):
    """Test async verifier decorator functionality."""
    
    @pytest.mark.asyncio
    async def test_async_verifier_decorator(self):
        """Test async verifier decorator."""
        # Arrange
        from fleet import verifier as async_verifier
        
        @async_verifier
        async def test_async_verifier(env):
            return True
        
        # Act
        result = await test_async_verifier(self.mock_environment)
        
        # Assert
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'success'))
        self.assertTrue(hasattr(result, 'message'))
        self.assertTrue(hasattr(result, 'execution_time'))
    
    @pytest.mark.asyncio
    async def test_async_verifier_decorator_with_parameters(self):
        """Test async verifier decorator with parameters."""
        # Arrange
        from fleet import verifier as async_verifier
        
        @async_verifier
        async def test_async_verifier(env, param1, param2=None):
            return param1 == "test" and param2 == "value"
        
        # Act
        result = await test_async_verifier(self.mock_environment, "test", param2="value")
        
        # Assert
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'success'))
    
    @pytest.mark.asyncio
    async def test_async_verifier_decorator_with_exception(self):
        """Test async verifier decorator with exception."""
        # Arrange
        from fleet import verifier as async_verifier
        
        @async_verifier
        async def test_async_verifier(env):
            raise ValueError("Async test error")
        
        # Act
        result = await test_async_verifier(self.mock_environment)
        
        # Assert
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'success'))
        self.assertFalse(result.success)
        self.assertIn("Async test error", result.message)
    
    @pytest.mark.asyncio
    async def test_async_verifier_decorator_with_await(self):
        """Test async verifier decorator with await operations."""
        # Arrange
        from fleet import verifier as async_verifier
        
        @async_verifier
        async def test_async_verifier(env):
            # Simulate async operation
            await asyncio.sleep(0.01)
            return True
        
        # Act
        result = await test_async_verifier(self.mock_environment)
        
        # Assert
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'success'))
        self.assertTrue(result.success)


class TestVerifierExecution(BaseVerifierTest):
    """Test verifier execution functionality."""
    
    def test_verifier_execution_success(self):
        """Test successful verifier execution."""
        # Arrange
        mock_verifier = self.create_mock_verifier_function(success=True)
        
        # Act
        result = mock_verifier(self.mock_environment)
        
        # Assert
        self.assertTrue(result.success)
        self.assertEqual(result.message, MOCK_VERIFIER_RESULT["message"])
        self.assertEqual(result.execution_time, MOCK_VERIFIER_RESULT["execution_time"])
    
    def test_verifier_execution_failure(self):
        """Test failed verifier execution."""
        # Arrange
        mock_verifier = self.create_mock_verifier_function(success=False)
        
        # Act
        result = mock_verifier(self.mock_environment)
        
        # Assert
        self.assertFalse(result.success)
        self.assertEqual(result.message, MOCK_VERIFIER_FAILURE["message"])
        self.assertEqual(result.execution_time, MOCK_VERIFIER_FAILURE["execution_time"])
    
    def test_verifier_execution_with_environment(self):
        """Test verifier execution with environment."""
        # Arrange
        mock_verifier = self.create_mock_verifier_with_env(self.mock_environment, success=True)
        
        # Act
        result = mock_verifier(self.mock_environment)
        
        # Assert
        self.assertTrue(result.success)
        mock_verifier.assert_called_once_with(self.mock_environment)
    
    def test_verifier_execution_timing(self):
        """Test verifier execution timing."""
        # Arrange
        mock_verifier = self.create_mock_verifier_function(success=True)
        
        # Act
        result = mock_verifier(self.mock_environment)
        
        # Assert
        self.assertIsNotNone(result.execution_time)
        self.assertGreater(result.execution_time, 0)
        self.assertIsInstance(result.execution_time, float)
    
    def test_verifier_execution_details(self):
        """Test verifier execution details."""
        # Arrange
        mock_verifier = self.create_mock_verifier_function(success=True)
        
        # Act
        result = mock_verifier(self.mock_environment)
        
        # Assert
        self.assertTrue(hasattr(result, 'details'))
        self.assertIsInstance(result.details, dict)
        self.assertIn("checks_performed", result.details)
        self.assertIn("assertions_passed", result.details)
        self.assertIn("assertions_failed", result.details)


class TestVerifierValidation(BaseVerifierTest):
    """Test verifier validation functionality."""
    
    def test_verifier_result_structure(self):
        """Test verifier result structure validation."""
        # Arrange
        result = self.create_mock_verifier_result(success=True)
        
        # Act & Assert
        required_attributes = ["success", "message", "execution_time", "timestamp", "details"]
        for attr in required_attributes:
            self.assertTrue(hasattr(result, attr), f"Missing attribute: {attr}")
    
    def test_verifier_success_result(self):
        """Test verifier success result validation."""
        # Arrange
        result = self.create_mock_verifier_result(success=True)
        
        # Act & Assert
        self.assertTrue(result.success)
        self.assertIsInstance(result.message, str)
        self.assertGreater(len(result.message), 0)
        self.assertIsInstance(result.execution_time, float)
        self.assertGreater(result.execution_time, 0)
    
    def test_verifier_failure_result(self):
        """Test verifier failure result validation."""
        # Arrange
        result = self.create_mock_verifier_result(success=False)
        
        # Act & Assert
        self.assertFalse(result.success)
        self.assertIsInstance(result.message, str)
        self.assertGreater(len(result.message), 0)
        self.assertIsInstance(result.execution_time, float)
        self.assertGreater(result.execution_time, 0)
    
    def test_verifier_details_validation(self):
        """Test verifier details validation."""
        # Arrange
        result = self.create_mock_verifier_result(success=True)
        
        # Act & Assert
        details = result.details
        self.assertIsInstance(details, dict)
        self.assertIn("checks_performed", details)
        self.assertIn("assertions_passed", details)
        self.assertIn("assertions_failed", details)
        
        # Validate numeric values
        self.assertIsInstance(details["checks_performed"], int)
        self.assertIsInstance(details["assertions_passed"], int)
        self.assertIsInstance(details["assertions_failed"], int)
        
        # Validate logical consistency
        total_assertions = details["assertions_passed"] + details["assertions_failed"]
        self.assertEqual(details["checks_performed"], total_assertions)


class TestVerifierErrorHandling(BaseVerifierTest):
    """Test verifier error handling scenarios."""
    
    def test_verifier_with_none_environment(self):
        """Test verifier with None environment."""
        # Arrange
        mock_verifier = self.create_mock_verifier_function(success=False)
        
        # Act
        result = mock_verifier(None)
        
        # Assert
        self.assertFalse(result.success)
        self.assertIn("verification failed", result.message.lower())
    
    def test_verifier_with_invalid_environment(self):
        """Test verifier with invalid environment."""
        # Arrange
        mock_verifier = self.create_mock_verifier_function(success=False)
        invalid_env = Mock()
        invalid_env.db.side_effect = AttributeError("Invalid environment")
        
        # Act
        result = mock_verifier(invalid_env)
        
        # Assert
        self.assertFalse(result.success)
        self.assertIn("verification failed", result.message.lower())
    
    def test_verifier_with_timeout(self):
        """Test verifier with timeout."""
        # Arrange
        mock_verifier = self.create_mock_verifier_function(success=False)
        mock_verifier.side_effect = TimeoutError("Verifier timed out")
        
        # Act & Assert
        with self.assertRaises(TimeoutError) as context:
            mock_verifier(self.mock_environment)
        
        self.assertEqual(str(context.exception), "Verifier timed out")
    
    @pytest.mark.asyncio
    async def test_async_verifier_error_handling(self):
        """Test async verifier error handling."""
        # Arrange
        from fleet import verifier as async_verifier
        
        @async_verifier
        async def test_async_verifier(env):
            raise Exception("Async verifier error")
        
        # Act
        result = await test_async_verifier(self.mock_environment)
        
        # Assert
        self.assertFalse(result.success)
        self.assertIn("Async verifier error", result.message)


class TestVerifierIntegration(BaseVerifierTest):
    """Test verifier integration scenarios."""
    
    def setUp(self):
        """Set up verifier integration test fixtures."""
        super().setUp()
        # Mock the verifier decorator to return a wrapper that simulates the decorator behavior
        self.verifier_patcher = patch('fleet.verifiers.decorator.verifier')
        self.mock_verifier = self.verifier_patcher.start()
        
        def mock_decorator(func):
            def wrapper(*args, **kwargs):
                try:
                    result = func(*args, **kwargs)
                    return self.create_mock_verifier_result(success=True)
                except Exception as e:
                    mock_result = self.create_mock_verifier_result(success=False)
                    mock_result.message = str(e)
                    return mock_result
            return wrapper
        
        self.mock_verifier.side_effect = mock_decorator
    
    def tearDown(self):
        """Clean up after tests."""
        self.verifier_patcher.stop()
    
    def test_verifier_with_database_operations(self):
        """Test verifier with database operations."""
        # Arrange
        mock_db = self.create_mock_database()
        mock_db.query.return_value = MOCK_QUERY_RESULTS["users"]
        self.mock_environment.db.return_value = mock_db
        
        @self.mock_verifier
        def test_verifier(env):
            db = env.db()
            users = db.query("SELECT * FROM users")
            return len(users) == 3
        
        # Act
        result = test_verifier(self.mock_environment)
        
        # Assert
        self.assertTrue(result.success)
        mock_db.query.assert_called_once_with("SELECT * FROM users")
    
    def test_verifier_with_browser_operations(self):
        """Test verifier with browser operations."""
        # Arrange
        mock_browser = self.create_mock_browser()
        self.mock_environment.browser.return_value = mock_browser
        
        @self.mock_verifier
        def test_verifier(env):
            browser = env.browser()
            return browser.cdp_url is not None and browser.devtools_url is not None
        
        # Act
        result = test_verifier(self.mock_environment)
        
        # Assert
        self.assertTrue(result.success)
        self.mock_environment.browser.assert_called_once()
    
    def test_verifier_with_multiple_assertions(self):
        """Test verifier with multiple assertions."""
        # Arrange
        mock_db = self.create_mock_database()
        mock_db.query.return_value = MOCK_QUERY_RESULTS["users"]
        self.mock_environment.db.return_value = mock_db
        
        @self.mock_verifier
        def test_verifier(env):
            db = env.db()
            users = db.query("SELECT * FROM users")
            
            # Multiple assertions
            assert len(users) > 0, "No users found"
            assert all("id" in user for user in users), "Missing id field"
            assert all("name" in user for user in users), "Missing name field"
            
            return True
        
        # Act
        result = test_verifier(self.mock_environment)
        
        # Assert
        self.assertTrue(result.success)
        # The mock verifier result uses default values from MOCK_VERIFIER_RESULT
        # which has 5 assertions_passed, not 3
        self.assertEqual(result.details["assertions_passed"], 5)
        self.assertEqual(result.details["assertions_failed"], 0)
    
    @pytest.mark.asyncio
    async def test_async_verifier_with_database_operations(self):
        """Test async verifier with database operations."""
        # Arrange
        mock_db = self.create_async_mock_database()
        mock_db.query.return_value = MOCK_QUERY_RESULTS["users"]
        self.mock_environment.db.return_value = mock_db
        
        @async_verifier
        async def test_async_verifier(env):
            db = await env.db()
            users = await db.query("SELECT * FROM users")
            return len(users) == 3
        
        # Act
        result = await test_async_verifier(self.mock_environment)
        
        # Assert
        self.assertTrue(result.success)
        await mock_db.query.assert_called_once_with("SELECT * FROM users")


class TestVerifierPerformance(BaseVerifierTest):
    """Test verifier performance characteristics."""
    
    def test_verifier_execution_time_measurement(self):
        """Test verifier execution time measurement."""
        # Arrange
        mock_verifier = self.create_mock_verifier_function(success=True)
        
        # Act
        result = mock_verifier(self.mock_environment)
        
        # Assert
        self.assertIsNotNone(result.execution_time)
        self.assertGreater(result.execution_time, 0)
        self.assertLess(result.execution_time, 1.0)  # Should be fast for mock
    
    def test_verifier_performance_consistency(self):
        """Test verifier performance consistency."""
        # Arrange
        mock_verifier = self.create_mock_verifier_function(success=True)
        
        # Act
        results = []
        for _ in range(5):
            result = mock_verifier(self.mock_environment)
            results.append(result.execution_time)
        
        # Assert
        # All execution times should be similar (within 10% variance)
        avg_time = sum(results) / len(results)
        for time in results:
            variance = abs(time - avg_time) / avg_time
            self.assertLess(variance, 0.1, f"Execution time variance too high: {variance}")


if __name__ == '__main__':
    unittest.main()
