"""
Base test classes for unit tests.
Provides common functionality and patterns for all unit tests.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from typing import Any, Dict, List, Optional, Union
import asyncio
import pytest

from .constants import *
from .helpers import MockFactory, DataGenerator, AsyncMockHelper, _TestDataBuilder


class BaseUnitTest(unittest.TestCase):
    """Base class for all unit tests."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_factory = MockFactory()
        self.data_generator = DataGenerator()
        self.test_builder = _TestDataBuilder()
        
        # Common mock data
        self.mock_api_key = MOCK_API_KEY
        self.mock_env_key = MOCK_ENV_KEYS[0]
        self.mock_environment = self.mock_factory.create_mock_environment()
        self.mock_instance = self.mock_factory.create_mock_instance()
        self.mock_account = MOCK_ACCOUNT.copy()
    
    def tearDown(self):
        """Clean up after tests."""
        pass
    
    def assert_mock_called_with_args(self, mock_obj: Mock, *args, **kwargs):
        """Assert that a mock was called with specific arguments."""
        mock_obj.assert_called_with(*args, **kwargs)
    
    def assert_mock_called_once(self, mock_obj: Mock):
        """Assert that a mock was called exactly once."""
        self.assertEqual(mock_obj.call_count, 1)
    
    def assert_mock_not_called(self, mock_obj: Mock):
        """Assert that a mock was not called."""
        self.assertEqual(mock_obj.call_count, 0)
    
    def create_mock_response(self, status_code: int = 200, **kwargs) -> Mock:
        """Create a mock HTTP response."""
        return self.mock_factory.create_mock_response(status_code, **kwargs)
    
    def create_mock_environment(self, **overrides) -> Mock:
        """Create a mock environment."""
        return self.mock_factory.create_mock_environment(**overrides)
    
    def create_mock_instance(self, **overrides) -> Mock:
        """Create a mock instance."""
        return self.mock_factory.create_mock_instance(**overrides)
    
    def create_mock_database(self) -> Mock:
        """Create a mock database resource."""
        return self.mock_factory.create_mock_database_resource()
    
    def create_mock_browser(self) -> Mock:
        """Create a mock browser resource."""
        return self.mock_factory.create_mock_browser_resource()
    
    def create_mock_task(self, **overrides) -> Mock:
        """Create a mock task."""
        mock_task = self.mock_factory.create_mock_task(**overrides)
        # Ensure metadata is a real dictionary
        if not hasattr(mock_task, 'metadata') or mock_task.metadata is None:
            mock_task.metadata = {}
        elif isinstance(mock_task.metadata, dict):
            # If it's already a dict, make sure it's a copy
            mock_task.metadata = mock_task.metadata.copy()
        return mock_task
    
    def create_mock_verifier_result(self, success: bool = True) -> Mock:
        """Create a mock verifier result."""
        mock_result = Mock()
        if success:
            mock_result.success = True
            mock_result.message = MOCK_VERIFIER_RESULT["message"]
            mock_result.execution_time = MOCK_VERIFIER_RESULT["execution_time"]
            mock_result.timestamp = MOCK_VERIFIER_RESULT["timestamp"]
            mock_result.details = MOCK_VERIFIER_RESULT["details"]
        else:
            mock_result.success = False
            mock_result.message = MOCK_VERIFIER_FAILURE["message"]
            mock_result.execution_time = MOCK_VERIFIER_FAILURE["execution_time"]
            mock_result.timestamp = MOCK_VERIFIER_FAILURE["timestamp"]
            mock_result.details = MOCK_VERIFIER_FAILURE["details"]
        return mock_result


class BaseAsyncUnitTest(unittest.IsolatedAsyncioTestCase):
    """Base class for async unit tests."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_factory = MockFactory()
        self.data_generator = DataGenerator()
        self.async_helper = AsyncMockHelper()
        self.test_builder = _TestDataBuilder()
        
        # Common mock data
        self.mock_api_key = MOCK_API_KEY
        self.mock_env_key = MOCK_ENV_KEYS[0]
        self.mock_environment = self.async_helper.create_async_mock_environment()
        self.mock_instance = self.mock_factory.create_mock_instance()
        self.mock_account = MOCK_ACCOUNT.copy()
    
    def tearDown(self):
        """Clean up after tests."""
        pass
    
    async def assert_async_mock_called_with_args(self, mock_obj: AsyncMock, *args, **kwargs):
        """Assert that an async mock was called with specific arguments."""
        mock_obj.assert_called_with(*args, **kwargs)
    
    async def assert_async_mock_called_once(self, mock_obj: AsyncMock):
        """Assert that an async mock was called exactly once."""
        self.assertEqual(mock_obj.call_count, 1)
    
    async def assert_async_mock_not_called(self, mock_obj: AsyncMock):
        """Assert that an async mock was not called."""
        self.assertEqual(mock_obj.call_count, 0)
    
    def create_async_mock_response(self, status_code: int = 200, **kwargs) -> AsyncMock:
        """Create an async mock HTTP response."""
        return self.async_helper.create_async_mock_response(status_code, **kwargs)
    
    def create_async_mock_environment(self, **overrides) -> AsyncMock:
        """Create an async mock environment."""
        return self.async_helper.create_async_mock_environment(**overrides)
    
    def create_async_mock_database(self) -> AsyncMock:
        """Create an async mock database."""
        return self.async_helper.create_async_mock_database()
    
    def create_async_mock_browser(self) -> AsyncMock:
        """Create an async mock browser."""
        return self.async_helper.create_async_mock_browser()
    
    def create_async_mock_instance(self, **overrides) -> AsyncMock:
        """Create an async mock instance."""
        mock_instance = AsyncMock()
        instance_data = MOCK_INSTANCE.copy()
        instance_data.update(overrides)
        
        for key, value in instance_data.items():
            setattr(mock_instance, key, value)
        
        return mock_instance
    
    async def simulate_async_delay(self, min_time: float = 0.01, max_time: float = 0.1):
        """Simulate async operation delay."""
        from .helpers import PerformanceSimulator
        return await PerformanceSimulator.simulate_async_delay(min_time, max_time)


class BaseClientTest(BaseUnitTest):
    """Base class for client tests."""
    
    def setUp(self):
        """Set up client test fixtures."""
        super().setUp()
        self.client_config = MOCK_CONFIG.copy()
        self.client_config["api_key"] = self.mock_api_key
    
    def create_mock_client(self, **overrides) -> Mock:
        """Create a mock Fleet client."""
        mock_client = Mock()
        mock_client.api_key = self.mock_api_key
        mock_client.config = self.client_config.copy()
        mock_client.config.update(overrides)
        return mock_client
    
    def create_mock_http_client(self) -> Mock:
        """Create a mock HTTP client."""
        mock_http = Mock()
        mock_http.get = Mock()
        mock_http.post = Mock()
        mock_http.put = Mock()
        mock_http.delete = Mock()
        mock_http.patch = Mock()
        return mock_http


class BaseAsyncClientTest(BaseAsyncUnitTest):
    """Base class for async client tests."""
    
    def setUp(self):
        """Set up async client test fixtures."""
        super().setUp()
        self.client_config = MOCK_CONFIG.copy()
        self.client_config["api_key"] = self.mock_api_key
    
    def create_async_mock_client(self, **overrides) -> AsyncMock:
        """Create an async mock Fleet client."""
        mock_client = AsyncMock()
        mock_client.api_key = self.mock_api_key
        mock_client.config = self.client_config.copy()
        mock_client.config.update(overrides)
        return mock_client
    
    def create_async_mock_http_client(self) -> AsyncMock:
        """Create an async mock HTTP client."""
        mock_http = AsyncMock()
        mock_http.get = AsyncMock()
        mock_http.post = AsyncMock()
        mock_http.put = AsyncMock()
        mock_http.delete = AsyncMock()
        mock_http.patch = AsyncMock()
        return mock_http


class BaseEnvironmentTest(BaseUnitTest):
    """Base class for environment tests."""
    
    def setUp(self):
        """Set up environment test fixtures."""
        super().setUp()
        self.environment_data = MOCK_ENVIRONMENTS[0].copy()
        self.instance_data = MOCK_INSTANCE.copy()
    
    def create_mock_environment_with_resources(self) -> Mock:
        """Create a mock environment with resources."""
        mock_env = self.create_mock_environment()
        mock_env.db = Mock(return_value=self.create_mock_database())
        mock_env.browser = Mock(return_value=self.create_mock_browser())
        mock_env.mcp = Mock()
        mock_env.mcp.url = MOCK_MCP_DATA["url"]
        return mock_env
    
    def create_mock_environment_list(self, count: int = 3) -> List[Mock]:
        """Create a list of mock environments."""
        environments = []
        for i in range(count):
            env_data = MOCK_ENVIRONMENTS[i % len(MOCK_ENVIRONMENTS)].copy()
            env_data["key"] = f"env_{i}_{self.data_generator.generate_random_string(5)}"
            environments.append(self.create_mock_environment(**env_data))
        return environments


class BaseAsyncEnvironmentTest(BaseAsyncUnitTest):
    """Base class for async environment tests."""
    
    def setUp(self):
        """Set up async environment test fixtures."""
        super().setUp()
        self.environment_data = MOCK_ENVIRONMENTS[0].copy()
        self.instance_data = MOCK_INSTANCE.copy()
    
    def create_async_mock_environment_with_resources(self) -> AsyncMock:
        """Create an async mock environment with resources."""
        mock_env = self.create_async_mock_environment()
        mock_env.db = AsyncMock(return_value=self.create_async_mock_database())
        mock_env.browser = AsyncMock(return_value=self.create_async_mock_browser())
        mock_env.mcp = AsyncMock()
        mock_env.mcp.url = MOCK_MCP_DATA["url"]
        return mock_env
    
    def create_async_mock_environment_list(self, count: int = 3) -> List[AsyncMock]:
        """Create a list of async mock environments."""
        environments = []
        for i in range(count):
            env_data = MOCK_ENVIRONMENTS[i % len(MOCK_ENVIRONMENTS)].copy()
            env_data["key"] = f"env_{i}_{self.data_generator.generate_random_string(5)}"
            environments.append(self.create_async_mock_environment(**env_data))
        return environments


class BaseResourceTest(BaseUnitTest):
    """Base class for resource tests."""
    
    def setUp(self):
        """Set up resource test fixtures."""
        super().setUp()
        self.database_data = MOCK_DATABASE_SCHEMA.copy()
        self.browser_data = MOCK_BROWSER_DATA.copy()
    
    def create_mock_database_with_query_results(self, results: List[Dict] = None) -> Mock:
        """Create a mock database with specific query results."""
        mock_db = self.create_mock_database()
        if results is None:
            results = MOCK_QUERY_RESULTS["users"]
        mock_db.query.return_value = results
        return mock_db
    
    def create_mock_browser_with_urls(self, cdp_url: str = None, devtools_url: str = None) -> Mock:
        """Create a mock browser with specific URLs."""
        mock_browser = self.create_mock_browser()
        if cdp_url:
            mock_browser.cdp_url = cdp_url
        if devtools_url:
            mock_browser.devtools_url = devtools_url
        return mock_browser


class BaseAsyncResourceTest(BaseAsyncUnitTest):
    """Base class for async resource tests."""
    
    def setUp(self):
        """Set up async resource test fixtures."""
        super().setUp()
        self.database_data = MOCK_DATABASE_SCHEMA.copy()
        self.browser_data = MOCK_BROWSER_DATA.copy()
    
    def create_async_mock_database_with_query_results(self, results: List[Dict] = None) -> AsyncMock:
        """Create an async mock database with specific query results."""
        mock_db = self.create_async_mock_database()
        if results is None:
            results = MOCK_QUERY_RESULTS["users"]
        mock_db.query.return_value = results
        return mock_db
    
    def create_async_mock_browser_with_urls(self, cdp_url: str = None, devtools_url: str = None) -> AsyncMock:
        """Create an async mock browser with specific URLs."""
        mock_browser = self.create_async_mock_browser()
        if cdp_url:
            mock_browser.cdp_url = cdp_url
        if devtools_url:
            mock_browser.devtools_url = devtools_url
        return mock_browser


class BaseVerifierTest(BaseUnitTest):
    """Base class for verifier tests."""
    
    def setUp(self):
        """Set up verifier test fixtures."""
        super().setUp()
        self.verifier_result = MOCK_VERIFIER_RESULT.copy()
        self.verifier_failure = MOCK_VERIFIER_FAILURE.copy()
    
    def create_mock_verifier_function(self, success: bool = True) -> Mock:
        """Create a mock verifier function."""
        mock_verifier = Mock()
        result = self.create_mock_verifier_result(success)
        mock_verifier.return_value = result
        return mock_verifier
    
    def create_mock_verifier_with_env(self, env: Mock, success: bool = True) -> Mock:
        """Create a mock verifier function that takes an environment."""
        def mock_verifier_func(environment):
            return self.create_mock_verifier_result(success)
        return Mock(side_effect=mock_verifier_func)


class BaseTaskTest(BaseUnitTest):
    """Base class for task tests."""
    
    def setUp(self):
        """Set up task test fixtures."""
        super().setUp()
        self.task_data = MOCK_TASK.copy()
    
    def create_mock_task_with_verifier(self, verifier_success: bool = True) -> Mock:
        """Create a mock task with a verifier."""
        mock_task = self.create_mock_task()
        mock_task.verify = Mock(return_value=self.create_mock_verifier_result(verifier_success))
        return mock_task
    
    def create_mock_task_list(self, count: int = 3) -> List[Mock]:
        """Create a list of mock tasks."""
        tasks = []
        for i in range(count):
            task_data = self.task_data.copy()
            task_data["id"] = f"task_{i}_{self.data_generator.generate_random_string(5)}"
            task_data["name"] = f"Task {i}"
            tasks.append(self.create_mock_task(**task_data))
        return tasks


class BaseModelTest(BaseUnitTest):
    """Base class for model tests."""
    
    def setUp(self):
        """Set up model test fixtures."""
        super().setUp()
        self.model_data = {}
    
    def assert_model_has_attributes(self, model: Any, expected_attrs: List[str]):
        """Assert that a model has the expected attributes."""
        for attr in expected_attrs:
            self.assertTrue(hasattr(model, attr), f"Model missing attribute: {attr}")
    
    def assert_model_attribute_values(self, model: Any, expected_values: Dict[str, Any]):
        """Assert that model attributes have expected values."""
        for attr, expected_value in expected_values.items():
            actual_value = getattr(model, attr)
            self.assertEqual(actual_value, expected_value, 
                           f"Attribute {attr}: expected {expected_value}, got {actual_value}")
    
    def create_test_model_data(self, **overrides) -> Dict[str, Any]:
        """Create test data for model testing."""
        test_data = self.model_data.copy()
        test_data.update(overrides)
        return test_data
