"""
Unit tests for Fleet and AsyncFleet clients.
Tests client initialization, configuration, and basic functionality.
"""

import unittest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
import pytest

from .base_test import BaseClientTest, BaseAsyncClientTest
from .constants import *


class TestFleetClient(BaseClientTest):
    """Test Fleet client functionality."""
    
    def test_client_initialization_with_api_key(self):
        """Test Fleet client initialization with API key."""
        # Arrange
        mock_client = self.create_mock_client()
        
        # Act & Assert
        self.assertEqual(mock_client.api_key, self.mock_api_key)
        self.assertIsNotNone(mock_client.config)
    
    def test_client_initialization_without_api_key(self):
        """Test Fleet client initialization without API key."""
        # Arrange
        mock_client = self.create_mock_client()
        mock_client.api_key = None
        
        # Act & Assert
        self.assertIsNone(mock_client.api_key)
        self.assertIsNotNone(mock_client.config)
    
    def test_client_initialization_with_config(self):
        """Test Fleet client initialization with configuration."""
        # Arrange
        config = {"timeout": 60, "max_retries": 5}
        mock_client = self.create_mock_client(**config)
        
        # Act & Assert
        self.assertEqual(mock_client.api_key, self.mock_api_key)
        self.assertEqual(mock_client.config["timeout"], 60)
        self.assertEqual(mock_client.config["max_retries"], 5)
    
    def test_client_attributes(self):
        """Test Fleet client has expected attributes."""
        # Arrange
        mock_client = self.create_mock_client()
        
        # Act & Assert
        self.assertTrue(hasattr(mock_client, 'api_key'))
        self.assertTrue(hasattr(mock_client, 'config'))
        self.assertEqual(mock_client.api_key, self.mock_api_key)
        self.assertIsInstance(mock_client.config, dict)
    
    def test_client_make_environment(self):
        """Test Fleet client make environment method."""
        # Arrange
        mock_client = self.create_mock_client()
        mock_client.make.return_value = self.mock_environment
        
        # Act
        env = mock_client.make(self.mock_env_key)
        
        # Assert
        mock_client.make.assert_called_once_with(self.mock_env_key)
        self.assertEqual(env, self.mock_environment)
    
    def test_client_list_environments(self):
        """Test Fleet client list environments method."""
        # Arrange
        mock_client = self.create_mock_client()
        mock_environments = [self.create_mock_environment() for _ in range(3)]
        mock_client.list_envs.return_value = mock_environments
        
        # Act
        environments = mock_client.list_envs()
        
        # Assert
        mock_client.list_envs.assert_called_once()
        self.assertEqual(len(environments), 3)
        self.assertIsInstance(environments, list)
    
    def test_client_list_regions(self):
        """Test Fleet client list regions method."""
        # Arrange
        mock_client = self.create_mock_client()
        mock_regions = MOCK_REGIONS.copy()
        mock_client.list_regions.return_value = mock_regions
        
        # Act
        regions = mock_client.list_regions()
        
        # Assert
        mock_client.list_regions.assert_called_once()
        self.assertEqual(len(regions), 3)
        self.assertIsInstance(regions, list)
    
    def test_client_account_info(self):
        """Test Fleet client account info method."""
        # Arrange
        mock_client = self.create_mock_client()
        mock_client.account.return_value = self.mock_account
        
        # Act
        account = mock_client.account()
        
        # Assert
        mock_client.account.assert_called_once()
        self.assertEqual(account, self.mock_account)
    
    def test_client_error_handling(self):
        """Test Fleet client error handling."""
        # Arrange
        mock_client = self.create_mock_client()
        mock_client.make.side_effect = Exception("API Error")
        
        # Act & Assert
        with self.assertRaises(Exception) as context:
            mock_client.make(self.mock_env_key)
        
        self.assertEqual(str(context.exception), "API Error")
    
    def test_client_configuration_validation(self):
        """Test Fleet client configuration validation."""
        # Arrange
        mock_client = self.create_mock_client()
        
        # Act & Assert
        self.assertIsNotNone(mock_client.api_key)
        self.assertIsInstance(mock_client.config, dict)
        self.assertIn("timeout", mock_client.config)
        self.assertIn("max_retries", mock_client.config)


class TestAsyncFleetClient(BaseAsyncClientTest):
    """Test AsyncFleet client functionality."""
    
    @pytest.mark.asyncio
    async def test_async_client_initialization_with_api_key(self):
        """Test AsyncFleet client initialization with API key."""
        # Arrange
        mock_client = self.create_async_mock_client()
        
        # Act & Assert
        self.assertEqual(mock_client.api_key, self.mock_api_key)
        self.assertIsNotNone(mock_client.config)
    
    @pytest.mark.asyncio
    async def test_async_client_initialization_without_api_key(self):
        """Test AsyncFleet client initialization without API key."""
        # Arrange
        mock_client = self.create_async_mock_client()
        mock_client.api_key = None
        
        # Act & Assert
        self.assertIsNone(mock_client.api_key)
        self.assertIsNotNone(mock_client.config)
    
    @pytest.mark.asyncio
    async def test_async_client_initialization_with_config(self):
        """Test AsyncFleet client initialization with configuration."""
        # Arrange
        config = {"timeout": 60, "max_retries": 5}
        mock_client = self.create_async_mock_client(**config)
        
        # Act & Assert
        self.assertEqual(mock_client.api_key, self.mock_api_key)
        self.assertEqual(mock_client.config["timeout"], 60)
        self.assertEqual(mock_client.config["max_retries"], 5)
    
    @pytest.mark.asyncio
    async def test_async_client_attributes(self):
        """Test AsyncFleet client has expected attributes."""
        # Arrange
        mock_client = self.create_async_mock_client()
        
        # Act & Assert
        self.assertTrue(hasattr(mock_client, 'api_key'))
        self.assertTrue(hasattr(mock_client, 'config'))
        self.assertEqual(mock_client.api_key, self.mock_api_key)
        self.assertIsInstance(mock_client.config, dict)
    
    @pytest.mark.asyncio
    async def test_async_client_make_environment(self):
        """Test AsyncFleet client make environment method."""
        # Arrange
        mock_client = self.create_async_mock_client()
        mock_client.make.return_value = self.mock_environment
        
        # Act
        env = await mock_client.make(self.mock_env_key)
        
        # Assert
        mock_client.make.assert_called_once_with(self.mock_env_key)
        self.assertEqual(env, self.mock_environment)
    
    @pytest.mark.asyncio
    async def test_async_client_list_environments(self):
        """Test AsyncFleet client list environments method."""
        # Arrange
        mock_client = self.create_async_mock_client()
        mock_environments = [self.create_async_mock_environment() for _ in range(3)]
        mock_client.list_envs.return_value = mock_environments
        
        # Act
        environments = await mock_client.list_envs()
        
        # Assert
        mock_client.list_envs.assert_called_once()
        self.assertEqual(len(environments), 3)
        self.assertIsInstance(environments, list)
    
    @pytest.mark.asyncio
    async def test_async_client_list_regions(self):
        """Test AsyncFleet client list regions method."""
        # Arrange
        mock_client = self.create_async_mock_client()
        mock_regions = MOCK_REGIONS.copy()
        mock_client.list_regions.return_value = mock_regions
        
        # Act
        regions = await mock_client.list_regions()
        
        # Assert
        mock_client.list_regions.assert_called_once()
        self.assertEqual(len(regions), 3)
        self.assertIsInstance(regions, list)
    
    @pytest.mark.asyncio
    async def test_async_client_account_info(self):
        """Test AsyncFleet client account info method."""
        # Arrange
        mock_client = self.create_async_mock_client()
        mock_client.account.return_value = self.mock_account
        
        # Act
        account = await mock_client.account()
        
        # Assert
        mock_client.account.assert_called_once()
        self.assertEqual(account, self.mock_account)
    
    @pytest.mark.asyncio
    async def test_async_client_error_handling(self):
        """Test AsyncFleet client error handling."""
        # Arrange
        mock_client = self.create_async_mock_client()
        mock_client.make.side_effect = Exception("API Error")
        
        # Act & Assert
        with self.assertRaises(Exception) as context:
            await mock_client.make(self.mock_env_key)
        
        self.assertEqual(str(context.exception), "API Error")
    
    @pytest.mark.asyncio
    async def test_async_client_configuration_validation(self):
        """Test AsyncFleet client configuration validation."""
        # Arrange
        mock_client = self.create_async_mock_client()
        
        # Act & Assert
        self.assertIsNotNone(mock_client.api_key)
        self.assertIsInstance(mock_client.config, dict)
        self.assertIn("timeout", mock_client.config)
        self.assertIn("max_retries", mock_client.config)


class TestClientComparison(unittest.TestCase):
    """Test comparison between Fleet and AsyncFleet clients."""
    
    def test_client_interface_consistency(self):
        """Test that Fleet and AsyncFleet have consistent interfaces."""
        # Arrange
        mock_fleet = Mock()
        mock_async_fleet = AsyncMock()
        
        # Add common methods to both clients
        common_methods = ['make', 'list_envs', 'list_regions', 'account']
        
        for method in common_methods:
            setattr(mock_fleet, method, Mock())
            setattr(mock_async_fleet, method, AsyncMock())
        
        # Act & Assert
        for method in common_methods:
            self.assertTrue(hasattr(mock_fleet, method))
            self.assertTrue(hasattr(mock_async_fleet, method))
    
    def test_client_configuration_consistency(self):
        """Test that Fleet and AsyncFleet have consistent configuration."""
        # Arrange
        mock_fleet = Mock()
        mock_async_fleet = AsyncMock()
        
        # Set up configuration
        config = MOCK_CONFIG.copy()
        mock_fleet.config = config
        mock_async_fleet.config = config
        
        # Act & Assert
        self.assertEqual(mock_fleet.config, mock_async_fleet.config)
        self.assertIn("timeout", mock_fleet.config)
        self.assertIn("timeout", mock_async_fleet.config)
        self.assertIn("max_retries", mock_fleet.config)
        self.assertIn("max_retries", mock_async_fleet.config)


class TestClientErrorHandling(unittest.TestCase):
    """Test client error handling scenarios."""
    
    def test_invalid_api_key_error(self):
        """Test handling of invalid API key."""
        # Arrange
        mock_client = Mock()
        mock_client.make.side_effect = ValueError("Invalid API key")
        
        # Act & Assert
        with self.assertRaises(ValueError) as context:
            mock_client.make("test_env")
        
        self.assertEqual(str(context.exception), "Invalid API key")
    
    def test_network_error_handling(self):
        """Test handling of network errors."""
        # Arrange
        mock_client = Mock()
        mock_client.make.side_effect = ConnectionError("Network error")
        
        # Act & Assert
        with self.assertRaises(ConnectionError) as context:
            mock_client.make("test_env")
        
        self.assertEqual(str(context.exception), "Network error")
    
    def test_timeout_error_handling(self):
        """Test handling of timeout errors."""
        # Arrange
        mock_client = Mock()
        mock_client.make.side_effect = TimeoutError("Request timed out")
        
        # Act & Assert
        with self.assertRaises(TimeoutError) as context:
            mock_client.make("test_env")
        
        self.assertEqual(str(context.exception), "Request timed out")
    
    @pytest.mark.asyncio
    async def test_async_error_handling(self):
        """Test async error handling."""
        # Arrange
        mock_client = AsyncMock()
        mock_client.make.side_effect = Exception("Async error")
        
        # Act & Assert
        with self.assertRaises(Exception) as context:
            await mock_client.make("test_env")
        
        self.assertEqual(str(context.exception), "Async error")


if __name__ == '__main__':
    unittest.main()
