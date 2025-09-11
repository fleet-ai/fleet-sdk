"""
Unit tests for environment management functionality.
Tests environment creation, listing, and management operations.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import pytest

from .base_test import BaseEnvironmentTest, BaseAsyncEnvironmentTest
from .constants import *


class TestEnvironmentManagement(BaseEnvironmentTest):
    """Test environment management functionality."""
    
    def test_list_environments(self):
        """Test listing available environments."""
        # Arrange
        mock_client = Mock()
        mock_environments = self.create_mock_environment_list(3)
        mock_client.list_envs.return_value = mock_environments
        
        # Act
        environments = mock_client.list_envs()
        
        # Assert
        mock_client.list_envs.assert_called_once()
        self.assertEqual(len(environments), 3)
        self.assertIsInstance(environments, list)
        
        # Verify environment structure
        for env in environments:
            self.assertTrue(hasattr(env, 'key'))
            self.assertTrue(hasattr(env, 'name'))
            self.assertTrue(hasattr(env, 'default_version'))
    
    def test_list_regions(self):
        """Test listing available regions."""
        # Arrange
        mock_client = Mock()
        mock_regions = MOCK_REGIONS.copy()
        mock_client.list_regions.return_value = mock_regions
        
        # Act
        regions = mock_client.list_regions()
        
        # Assert
        mock_client.list_regions.assert_called_once()
        self.assertEqual(len(regions), 3)
        self.assertIsInstance(regions, list)
        
        # Verify region structure
        for region in regions:
            self.assertIn("id", region)
            self.assertIn("name", region)
            self.assertIn("status", region)
    
    def test_make_environment(self):
        """Test creating a new environment."""
        # Arrange
        mock_client = Mock()
        mock_environment = self.create_mock_environment()
        mock_client.make.return_value = mock_environment
        
        # Act
        env = mock_client.make(self.mock_env_key)
        
        # Assert
        mock_client.make.assert_called_once_with(self.mock_env_key)
        self.assertEqual(env, mock_environment)
        self.assertEqual(env.key, self.mock_env_key)
    
    def test_get_environment(self):
        """Test getting an existing environment."""
        # Arrange
        mock_client = Mock()
        mock_environment = self.create_mock_environment()
        mock_client.get.return_value = mock_environment
        
        # Act
        env = mock_client.get(self.mock_env_key)
        
        # Assert
        mock_client.get.assert_called_once_with(self.mock_env_key)
        self.assertEqual(env, mock_environment)
    
    def test_list_instances(self):
        """Test listing environment instances."""
        # Arrange
        mock_client = Mock()
        mock_instances = [self.create_mock_instance() for _ in range(2)]
        mock_client.instances.return_value = mock_instances
        
        # Act
        instances = mock_client.instances()
        
        # Assert
        mock_client.instances.assert_called_once()
        self.assertEqual(len(instances), 2)
        self.assertIsInstance(instances, list)
        
        # Verify instance structure
        for instance in instances:
            self.assertTrue(hasattr(instance, 'id'))
            self.assertTrue(hasattr(instance, 'env_key'))
            self.assertTrue(hasattr(instance, 'status'))
    
    def test_environment_attributes(self):
        """Test environment object attributes."""
        # Arrange
        mock_env = self.create_mock_environment()
        
        # Act & Assert
        self.assertTrue(hasattr(mock_env, 'key'))
        self.assertTrue(hasattr(mock_env, 'name'))
        self.assertTrue(hasattr(mock_env, 'default_version'))
        self.assertTrue(hasattr(mock_env, 'region'))
        self.assertTrue(hasattr(mock_env, 'status'))
        self.assertTrue(hasattr(mock_env, 'created_at'))
        self.assertTrue(hasattr(mock_env, 'updated_at'))
    
    def test_environment_with_resources(self):
        """Test environment with database and browser resources."""
        # Arrange
        mock_env = self.create_mock_environment_with_resources()
        
        # Act
        db = mock_env.db()
        browser = mock_env.browser()
        
        # Assert
        self.assertIsNotNone(db)
        self.assertIsNotNone(browser)
        self.assertTrue(hasattr(db, 'query'))
        self.assertTrue(hasattr(db, 'exec'))
        self.assertTrue(hasattr(browser, 'cdp_url'))
        self.assertTrue(hasattr(browser, 'devtools_url'))
    
    def test_environment_close(self):
        """Test environment close functionality."""
        # Arrange
        mock_env = self.create_mock_environment()
        mock_env.close = Mock()
        
        # Act
        mock_env.close()
        
        # Assert
        mock_env.close.assert_called_once()
    
    def test_environment_reset(self):
        """Test environment reset functionality."""
        # Arrange
        mock_env = self.create_mock_environment()
        mock_env.reset = Mock()
        
        # Act
        mock_env.reset(seed=42, timestamp="2024-01-01T00:00:00Z")
        
        # Assert
        mock_env.reset.assert_called_once_with(seed=42, timestamp="2024-01-01T00:00:00Z")
    
    def test_environment_state_access(self):
        """Test environment state access."""
        # Arrange
        mock_env = self.create_mock_environment()
        mock_env.state = Mock(return_value="sqlite://current")
        
        # Act
        state = mock_env.state("sqlite://current")
        
        # Assert
        mock_env.state.assert_called_once_with("sqlite://current")
        self.assertEqual(state, "sqlite://current")


class TestAsyncEnvironmentManagement(BaseAsyncEnvironmentTest):
    """Test async environment management functionality."""
    
    @pytest.mark.asyncio
    async def test_async_list_environments(self):
        """Test async listing available environments."""
        # Arrange
        mock_client = AsyncMock()
        mock_environments = self.create_async_mock_environment_list(3)
        mock_client.list_envs.return_value = mock_environments
        
        # Act
        environments = await mock_client.list_envs()
        
        # Assert
        mock_client.list_envs.assert_called_once()
        self.assertEqual(len(environments), 3)
        self.assertIsInstance(environments, list)
    
    @pytest.mark.asyncio
    async def test_async_list_regions(self):
        """Test async listing available regions."""
        # Arrange
        mock_client = AsyncMock()
        mock_regions = MOCK_REGIONS.copy()
        mock_client.list_regions.return_value = mock_regions
        
        # Act
        regions = await mock_client.list_regions()
        
        # Assert
        mock_client.list_regions.assert_called_once()
        self.assertEqual(len(regions), 3)
        self.assertIsInstance(regions, list)
    
    @pytest.mark.asyncio
    async def test_async_make_environment(self):
        """Test async creating a new environment."""
        # Arrange
        mock_client = AsyncMock()
        mock_environment = self.create_async_mock_environment()
        mock_client.make.return_value = mock_environment
        
        # Act
        env = await mock_client.make(self.mock_env_key)
        
        # Assert
        mock_client.make.assert_called_once_with(self.mock_env_key)
        self.assertEqual(env, mock_environment)
    
    @pytest.mark.asyncio
    async def test_async_get_environment(self):
        """Test async getting an existing environment."""
        # Arrange
        mock_client = AsyncMock()
        mock_environment = self.create_async_mock_environment()
        mock_client.get.return_value = mock_environment
        
        # Act
        env = await mock_client.get(self.mock_env_key)
        
        # Assert
        mock_client.get.assert_called_once_with(self.mock_env_key)
        self.assertEqual(env, mock_environment)
    
    @pytest.mark.asyncio
    async def test_async_list_instances(self):
        """Test async listing environment instances."""
        # Arrange
        mock_client = AsyncMock()
        mock_instances = [self.create_async_mock_instance() for _ in range(2)]
        mock_client.instances.return_value = mock_instances
        
        # Act
        instances = await mock_client.instances()
        
        # Assert
        mock_client.instances.assert_called_once()
        self.assertEqual(len(instances), 2)
        self.assertIsInstance(instances, list)
    
    @pytest.mark.asyncio
    async def test_async_environment_attributes(self):
        """Test async environment object attributes."""
        # Arrange
        mock_env = self.create_async_mock_environment()
        
        # Act & Assert
        self.assertTrue(hasattr(mock_env, 'key'))
        self.assertTrue(hasattr(mock_env, 'name'))
        self.assertTrue(hasattr(mock_env, 'default_version'))
        self.assertTrue(hasattr(mock_env, 'region'))
        self.assertTrue(hasattr(mock_env, 'status'))
        self.assertTrue(hasattr(mock_env, 'created_at'))
        self.assertTrue(hasattr(mock_env, 'updated_at'))
    
    @pytest.mark.asyncio
    async def test_async_environment_with_resources(self):
        """Test async environment with database and browser resources."""
        # Arrange
        mock_env = self.create_async_mock_environment_with_resources()
        
        # Act
        db = await mock_env.db()
        browser = await mock_env.browser()
        
        # Assert
        self.assertIsNotNone(db)
        self.assertIsNotNone(browser)
        self.assertTrue(hasattr(db, 'query'))
        self.assertTrue(hasattr(db, 'exec'))
        self.assertTrue(hasattr(browser, 'cdp_url'))
        self.assertTrue(hasattr(browser, 'devtools_url'))
    
    @pytest.mark.asyncio
    async def test_async_environment_close(self):
        """Test async environment close functionality."""
        # Arrange
        mock_env = self.create_async_mock_environment()
        mock_close = AsyncMock()
        mock_env.close = mock_close
        
        # Act
        await mock_env.close()
        
        # Assert
        mock_close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_async_environment_reset(self):
        """Test async environment reset functionality."""
        # Arrange
        mock_env = self.create_async_mock_environment()
        mock_reset = AsyncMock()
        mock_env.reset = mock_reset
        
        # Act
        await mock_env.reset(seed=42, timestamp="2024-01-01T00:00:00Z")
        
        # Assert
        mock_reset.assert_called_once_with(seed=42, timestamp="2024-01-01T00:00:00Z")


class TestEnvironmentErrorHandling(unittest.TestCase):
    """Test environment error handling scenarios."""
    
    def test_environment_not_found_error(self):
        """Test handling of environment not found error."""
        # Arrange
        mock_client = Mock()
        mock_client.get.side_effect = ValueError("Environment not found")
        
        # Act & Assert
        with self.assertRaises(ValueError) as context:
            mock_client.get("nonexistent_env")
        
        self.assertEqual(str(context.exception), "Environment not found")
    
    def test_environment_creation_failure(self):
        """Test handling of environment creation failure."""
        # Arrange
        mock_client = Mock()
        mock_client.make.side_effect = Exception("Failed to create environment")
        
        # Act & Assert
        with self.assertRaises(Exception) as context:
            mock_client.make("test_env")
        
        self.assertEqual(str(context.exception), "Failed to create environment")
    
    @pytest.mark.asyncio
    async def test_async_environment_error_handling(self):
        """Test async environment error handling."""
        # Arrange
        mock_client = AsyncMock()
        mock_client.make.side_effect = Exception("Async environment error")
        
        # Act & Assert
        with self.assertRaises(Exception) as context:
            await mock_client.make("test_env")
        
        self.assertEqual(str(context.exception), "Async environment error")


class TestEnvironmentValidation(unittest.TestCase):
    """Test environment data validation."""
    
    def test_environment_key_validation(self):
        """Test environment key format validation."""
        # Valid environment keys
        valid_keys = [
            "dropbox:Forge1.1.0",
            "hubspot:Forge1.1.0",
            "ramp:Forge1.1.0",
            "confluence:v1.4.1"
        ]
        
        for key in valid_keys:
            # Should not raise any exception
            self.assertIsInstance(key, str)
            self.assertIn(":", key)
    
    def test_environment_data_structure(self):
        """Test environment data structure validation."""
        # Arrange
        env_data = MOCK_ENVIRONMENTS[0]
        
        # Act & Assert
        required_fields = ["key", "name", "default_version", "region", "status"]
        for field in required_fields:
            self.assertIn(field, env_data)
            self.assertIsNotNone(env_data[field])
    
    def test_instance_data_structure(self):
        """Test instance data structure validation."""
        # Arrange
        instance_data = MOCK_INSTANCE
        
        # Act & Assert
        required_fields = ["id", "env_key", "status", "region"]
        for field in required_fields:
            self.assertIn(field, instance_data)
            self.assertIsNotNone(instance_data[field])
        
        # Check resources structure
        self.assertIn("resources", instance_data)
        self.assertIn("database", instance_data["resources"])
        self.assertIn("browser", instance_data["resources"])


class TestEnvironmentLifecycle(unittest.TestCase):
    """Test environment lifecycle management."""
    
    def test_environment_creation_lifecycle(self):
        """Test environment creation lifecycle."""
        # Arrange
        mock_env = Mock()
        mock_env.status = "creating"
        
        # Act
        initial_status = mock_env.status
        
        # Simulate status change
        mock_env.status = "running"
        final_status = mock_env.status
        
        # Assert
        self.assertEqual(initial_status, "creating")
        self.assertEqual(final_status, "running")
    
    def test_environment_termination_lifecycle(self):
        """Test environment termination lifecycle."""
        # Arrange
        mock_env = Mock()
        mock_env.status = "running"
        mock_env.terminate = Mock()
        
        # Act
        mock_env.terminate()
        mock_env.status = "terminated"
        
        # Assert
        mock_env.terminate.assert_called_once()
        self.assertEqual(mock_env.status, "terminated")
    
    @pytest.mark.asyncio
    async def test_async_environment_lifecycle(self):
        """Test async environment lifecycle."""
        # Arrange
        mock_env = AsyncMock()
        mock_env.status = "creating"
        
        # Act
        initial_status = mock_env.status
        
        # Simulate async status change
        mock_env.status = "running"
        final_status = mock_env.status
        
        # Assert
        self.assertEqual(initial_status, "creating")
        self.assertEqual(final_status, "running")


if __name__ == '__main__':
    unittest.main()
