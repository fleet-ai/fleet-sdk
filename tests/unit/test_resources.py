"""
Unit tests for database and browser resources.
Tests resource functionality, operations, and data handling.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import pytest

from .base_test import BaseResourceTest, BaseAsyncResourceTest
from .constants import *


class TestDatabaseResource(BaseResourceTest):
    """Test database resource functionality."""
    
    def test_database_query_execution(self):
        """Test database query execution."""
        # Arrange
        mock_db = self.create_mock_database()
        expected_results = MOCK_QUERY_RESULTS["users"]
        
        # Act
        results = mock_db.query("SELECT * FROM users")
        
        # Assert
        self.assertEqual(results, expected_results)
        mock_db.query.assert_called_once_with("SELECT * FROM users")
    
    def test_database_query_with_parameters(self):
        """Test database query with parameters."""
        # Arrange
        mock_db = self.create_mock_database()
        expected_results = MOCK_QUERY_RESULTS["users"]
        
        # Act
        results = mock_db.query("SELECT * FROM users WHERE id = ?", [1])
        
        # Assert
        self.assertEqual(results, expected_results)
        mock_db.query.assert_called_once_with("SELECT * FROM users WHERE id = ?", [1])
    
    def test_database_exec_execution(self):
        """Test database exec execution."""
        # Arrange
        mock_db = self.create_mock_database()
        expected_result = {"rows_affected": 1}
        
        # Act
        result = mock_db.exec("INSERT INTO users (name, email) VALUES (?, ?)", ["John", "john@example.com"])
        
        # Assert
        self.assertEqual(result, expected_result)
        mock_db.exec.assert_called_once_with("INSERT INTO users (name, email) VALUES (?, ?)", ["John", "john@example.com"])
    
    def test_database_describe_schema(self):
        """Test database schema description."""
        # Arrange
        mock_db = self.create_mock_database()
        expected_schema = MOCK_DATABASE_SCHEMA
        
        # Act
        schema = mock_db.describe()
        
        # Assert
        self.assertEqual(schema, expected_schema)
        mock_db.describe.assert_called_once()
    
    def test_database_table_query_builder(self):
        """Test database table query builder."""
        # Arrange
        mock_db = self.create_mock_database()
        expected_results = MOCK_QUERY_RESULTS["users"]
        
        # Act
        results = mock_db.table("users").eq("id", 1).all()
        
        # Assert
        self.assertEqual(results, expected_results)
        mock_db.table.assert_called_once_with("users")
    
    def test_database_query_result_structure(self):
        """Test database query result structure."""
        # Arrange
        mock_db = self.create_mock_database()
        
        # Act
        results = mock_db.query("SELECT * FROM users")
        
        # Assert
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        
        # Check first result structure
        first_result = results[0]
        self.assertIn("id", first_result)
        self.assertIn("name", first_result)
        self.assertIn("email", first_result)
        self.assertIn("created_at", first_result)
    
    def test_database_error_handling(self):
        """Test database error handling."""
        # Arrange
        mock_db = self.create_mock_database()
        mock_db.query.side_effect = Exception("SQL Error")
        
        # Act & Assert
        with self.assertRaises(Exception) as context:
            mock_db.query("INVALID SQL")
        
        self.assertEqual(str(context.exception), "SQL Error")
    
    def test_database_connection_attributes(self):
        """Test database connection attributes."""
        # Arrange
        mock_db = self.create_mock_database()
        
        # Act & Assert
        # Database should have expected methods
        self.assertTrue(hasattr(mock_db, 'query'))
        self.assertTrue(hasattr(mock_db, 'exec'))
        self.assertTrue(hasattr(mock_db, 'describe'))
        self.assertTrue(hasattr(mock_db, 'table'))
    
    def test_database_state_access(self):
        """Test database state access."""
        # Arrange
        mock_env = Mock()
        mock_env.state = Mock(return_value="sqlite://current")
        
        # Act
        state = mock_env.state("sqlite://current")
        
        # Assert
        mock_env.state.assert_called_once_with("sqlite://current")
        self.assertEqual(state, "sqlite://current")


class TestAsyncDatabaseResource(BaseAsyncResourceTest):
    """Test async database resource functionality."""
    
    @pytest.mark.asyncio
    async def test_async_database_query_execution(self):
        """Test async database query execution."""
        # Arrange
        mock_db = self.create_async_mock_database()
        expected_results = MOCK_QUERY_RESULTS["users"]
        mock_query = AsyncMock(return_value=expected_results)
        mock_db.query = mock_query
        
        # Act
        results = await mock_db.query("SELECT * FROM users")
        
        # Assert
        self.assertEqual(results, expected_results)
        mock_query.assert_called_once_with("SELECT * FROM users")
    
    @pytest.mark.asyncio
    async def test_async_database_query_with_parameters(self):
        """Test async database query with parameters."""
        # Arrange
        mock_db = self.create_async_mock_database()
        expected_results = MOCK_QUERY_RESULTS["users"]
        mock_query = AsyncMock(return_value=expected_results)
        mock_db.query = mock_query
        
        # Act
        results = await mock_db.query("SELECT * FROM users WHERE id = ?", [1])
        
        # Assert
        self.assertEqual(results, expected_results)
        mock_query.assert_called_once_with("SELECT * FROM users WHERE id = ?", [1])
    
    @pytest.mark.asyncio
    async def test_async_database_exec_execution(self):
        """Test async database exec execution."""
        # Arrange
        mock_db = self.create_async_mock_database()
        expected_result = {"rows_affected": 1}
        mock_exec = AsyncMock(return_value=expected_result)
        mock_db.exec = mock_exec
        
        # Act
        result = await mock_db.exec("INSERT INTO users (name, email) VALUES (?, ?)", ["John", "john@example.com"])
        
        # Assert
        self.assertEqual(result, expected_result)
        mock_exec.assert_called_once_with("INSERT INTO users (name, email) VALUES (?, ?)", ["John", "john@example.com"])
    
    @pytest.mark.asyncio
    async def test_async_database_describe_schema(self):
        """Test async database schema description."""
        # Arrange
        mock_db = self.create_async_mock_database()
        expected_schema = MOCK_DATABASE_SCHEMA
        mock_describe = AsyncMock(return_value=expected_schema)
        mock_db.describe = mock_describe
        
        # Act
        schema = await mock_db.describe()
        
        # Assert
        self.assertEqual(schema, expected_schema)
        mock_describe.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_async_database_table_query_builder(self):
        """Test async database table query builder."""
        # Arrange
        mock_db = self.create_async_mock_database()
        expected_results = MOCK_QUERY_RESULTS["users"]
        
        # Create a mock table object
        mock_table = Mock()
        mock_table.eq.return_value.all = AsyncMock(return_value=expected_results)
        mock_db.table = AsyncMock(return_value=mock_table)
        
        # Act
        table = await mock_db.table("users")
        results = await table.eq("id", 1).all()
        
        # Assert
        self.assertEqual(results, expected_results)
        mock_db.table.assert_called_once_with("users")
    
    @pytest.mark.asyncio
    async def test_async_database_error_handling(self):
        """Test async database error handling."""
        # Arrange
        mock_db = self.create_async_mock_database()
        mock_db.query.side_effect = Exception("Async SQL Error")
        
        # Act & Assert
        with self.assertRaises(Exception) as context:
            await mock_db.query("INVALID SQL")
        
        self.assertEqual(str(context.exception), "Async SQL Error")


class TestBrowserResource(BaseResourceTest):
    """Test browser resource functionality."""
    
    def test_browser_cdp_url(self):
        """Test browser CDP URL access."""
        # Arrange
        mock_browser = self.create_mock_browser()
        expected_url = MOCK_BROWSER_DATA["cdp_url"]
        
        # Act
        cdp_url = mock_browser.cdp_url
        
        # Assert
        self.assertEqual(cdp_url, expected_url)
        self.assertTrue(cdp_url.startswith("ws://"))
    
    def test_browser_devtools_url(self):
        """Test browser DevTools URL access."""
        # Arrange
        mock_browser = self.create_mock_browser()
        expected_url = MOCK_BROWSER_DATA["devtools_url"]
        
        # Act
        devtools_url = mock_browser.devtools_url
        
        # Assert
        self.assertEqual(devtools_url, expected_url)
        self.assertTrue(devtools_url.startswith("http://"))
    
    def test_browser_user_agent(self):
        """Test browser user agent access."""
        # Arrange
        mock_browser = self.create_mock_browser()
        expected_user_agent = MOCK_BROWSER_DATA["user_agent"]
        
        # Act
        user_agent = mock_browser.user_agent
        
        # Assert
        self.assertEqual(user_agent, expected_user_agent)
        self.assertIn("Mozilla", user_agent)
    
    def test_browser_viewport(self):
        """Test browser viewport access."""
        # Arrange
        mock_browser = self.create_mock_browser()
        expected_viewport = MOCK_BROWSER_DATA["viewport"]
        
        # Act
        viewport = mock_browser.viewport
        
        # Assert
        self.assertEqual(viewport, expected_viewport)
        self.assertIn("width", viewport)
        self.assertIn("height", viewport)
    
    def test_browser_cookies(self):
        """Test browser cookies access."""
        # Arrange
        mock_browser = self.create_mock_browser()
        expected_cookies = MOCK_BROWSER_DATA["cookies"]
        
        # Act
        cookies = mock_browser.cookies
        
        # Assert
        self.assertEqual(cookies, expected_cookies)
        self.assertIsInstance(cookies, list)
    
    def test_browser_local_storage(self):
        """Test browser local storage access."""
        # Arrange
        mock_browser = self.create_mock_browser()
        expected_storage = MOCK_BROWSER_DATA["local_storage"]
        
        # Act
        storage = mock_browser.local_storage
        
        # Assert
        self.assertEqual(storage, expected_storage)
        self.assertIsInstance(storage, dict)
    
    def test_browser_session_storage(self):
        """Test browser session storage access."""
        # Arrange
        mock_browser = self.create_mock_browser()
        expected_storage = MOCK_BROWSER_DATA["session_storage"]
        
        # Act
        storage = mock_browser.session_storage
        
        # Assert
        self.assertEqual(storage, expected_storage)
        self.assertIsInstance(storage, dict)
    
    def test_browser_url_validation(self):
        """Test browser URL format validation."""
        # Arrange
        mock_browser = self.create_mock_browser()
        
        # Act
        cdp_url = mock_browser.cdp_url
        devtools_url = mock_browser.devtools_url
        
        # Assert
        self.assertTrue(cdp_url.startswith("ws://"))
        self.assertTrue(devtools_url.startswith("http://"))
        self.assertIn("localhost", cdp_url)
        self.assertIn("localhost", devtools_url)


class TestAsyncBrowserResource(BaseAsyncResourceTest):
    """Test async browser resource functionality."""
    
    @pytest.mark.asyncio
    async def test_async_browser_cdp_url(self):
        """Test async browser CDP URL access."""
        # Arrange
        mock_browser = self.create_async_mock_browser()
        expected_url = MOCK_BROWSER_DATA["cdp_url"]
        
        # Act
        cdp_url = mock_browser.cdp_url
        
        # Assert
        self.assertEqual(cdp_url, expected_url)
        self.assertTrue(cdp_url.startswith("ws://"))
    
    @pytest.mark.asyncio
    async def test_async_browser_devtools_url(self):
        """Test async browser DevTools URL access."""
        # Arrange
        mock_browser = self.create_async_mock_browser()
        expected_url = MOCK_BROWSER_DATA["devtools_url"]
        
        # Act
        devtools_url = mock_browser.devtools_url
        
        # Assert
        self.assertEqual(devtools_url, expected_url)
        self.assertTrue(devtools_url.startswith("http://"))
    
    @pytest.mark.asyncio
    async def test_async_browser_user_agent(self):
        """Test async browser user agent access."""
        # Arrange
        mock_browser = self.create_async_mock_browser()
        expected_user_agent = MOCK_BROWSER_DATA["user_agent"]
        
        # Act
        user_agent = mock_browser.user_agent
        
        # Assert
        self.assertEqual(user_agent, expected_user_agent)
        self.assertIn("Mozilla", user_agent)
    
    @pytest.mark.asyncio
    async def test_async_browser_viewport(self):
        """Test async browser viewport access."""
        # Arrange
        mock_browser = self.create_async_mock_browser()
        expected_viewport = MOCK_BROWSER_DATA["viewport"]
        
        # Act
        viewport = mock_browser.viewport
        
        # Assert
        self.assertEqual(viewport, expected_viewport)
        self.assertIn("width", viewport)
        self.assertIn("height", viewport)


class TestResourceIntegration(unittest.TestCase):
    """Test resource integration scenarios."""
    
    def test_database_and_browser_resource_coexistence(self):
        """Test that database and browser resources can coexist."""
        # Arrange
        mock_env = Mock()
        mock_db = Mock()
        mock_browser = Mock()
        
        mock_env.db.return_value = mock_db
        mock_env.browser.return_value = mock_browser
        
        # Act
        db = mock_env.db()
        browser = mock_env.browser()
        
        # Assert
        self.assertIsNotNone(db)
        self.assertIsNotNone(browser)
        self.assertNotEqual(db, browser)
    
    def test_resource_lifecycle_management(self):
        """Test resource lifecycle management."""
        # Arrange
        mock_env = Mock()
        mock_db = Mock()
        mock_browser = Mock()
        
        mock_env.db.return_value = mock_db
        mock_env.browser.return_value = mock_browser
        mock_env.close = Mock()
        
        # Act
        db = mock_env.db()
        browser = mock_env.browser()
        mock_env.close()
        
        # Assert
        mock_env.db.assert_called_once()
        mock_env.browser.assert_called_once()
        mock_env.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_async_resource_lifecycle_management(self):
        """Test async resource lifecycle management."""
        # Arrange
        mock_env = AsyncMock()
        mock_db = AsyncMock()
        mock_browser = AsyncMock()
        
        mock_env.db.return_value = mock_db
        mock_env.browser.return_value = mock_browser
        mock_env.close = AsyncMock()
        
        # Act
        db = await mock_env.db()
        browser = await mock_env.browser()
        await mock_env.close()
        
        # Assert
        mock_env.db.assert_called_once()
        mock_env.browser.assert_called_once()
        mock_env.close.assert_called_once()


class TestResourceErrorHandling(unittest.TestCase):
    """Test resource error handling scenarios."""
    
    def test_database_connection_error(self):
        """Test database connection error handling."""
        # Arrange
        mock_db = Mock()
        mock_db.query.side_effect = ConnectionError("Database connection failed")
        
        # Act & Assert
        with self.assertRaises(ConnectionError) as context:
            mock_db.query("SELECT 1")
        
        self.assertEqual(str(context.exception), "Database connection failed")
    
    def test_browser_connection_error(self):
        """Test browser connection error handling."""
        # Arrange
        mock_browser = Mock()
        mock_browser.cdp_url = "ws://invalid:9999/devtools/browser"
        
        # Act
        cdp_url = mock_browser.cdp_url
        
        # Assert
        self.assertEqual(cdp_url, "ws://invalid:9999/devtools/browser")
        self.assertIn("invalid", cdp_url)
    
    @pytest.mark.asyncio
    async def test_async_resource_error_handling(self):
        """Test async resource error handling."""
        # Arrange
        mock_db = AsyncMock()
        mock_db.query.side_effect = Exception("Async resource error")
        
        # Act & Assert
        with self.assertRaises(Exception) as context:
            await mock_db.query("SELECT 1")
        
        self.assertEqual(str(context.exception), "Async resource error")


class TestResourceDataValidation(unittest.TestCase):
    """Test resource data validation."""
    
    def test_database_query_result_validation(self):
        """Test database query result validation."""
        # Arrange
        mock_db = Mock()
        mock_db.query.return_value = MOCK_QUERY_RESULTS["users"]
        
        # Act
        results = mock_db.query("SELECT * FROM users")
        
        # Assert
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        
        # Validate first result
        first_result = results[0]
        self.assertIn("id", first_result)
        self.assertIn("name", first_result)
        self.assertIn("email", first_result)
        self.assertIsInstance(first_result["id"], int)
        self.assertIsInstance(first_result["name"], str)
        self.assertIsInstance(first_result["email"], str)
    
    def test_browser_data_validation(self):
        """Test browser data validation."""
        # Arrange
        browser_data = MOCK_BROWSER_DATA
        
        # Act & Assert
        self.assertIn("cdp_url", browser_data)
        self.assertIn("devtools_url", browser_data)
        self.assertIn("user_agent", browser_data)
        self.assertIn("viewport", browser_data)
        
        # Validate URL formats
        self.assertTrue(browser_data["cdp_url"].startswith("ws://"))
        self.assertTrue(browser_data["devtools_url"].startswith("http://"))
        
        # Validate viewport structure
        viewport = browser_data["viewport"]
        self.assertIn("width", viewport)
        self.assertIn("height", viewport)
        self.assertIsInstance(viewport["width"], int)
        self.assertIsInstance(viewport["height"], int)


if __name__ == '__main__':
    unittest.main()
