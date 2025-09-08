"""
Helper utilities for unit tests.
Provides mock factories, data generators, and common test utilities.
"""

import json
import random
import string
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, MagicMock
import asyncio

from .constants import *


class MockFactory:
    """Factory class for creating mock objects."""
    
    @staticmethod
    def create_mock_response(
        status_code: int = 200,
        json_data: Optional[Dict] = None,
        text_data: Optional[str] = None,
        headers: Optional[Dict] = None
    ) -> Mock:
        """Create a mock HTTP response."""
        response = Mock()
        response.status_code = status_code
        response.headers = headers or {"Content-Type": "application/json"}
        
        if json_data:
            response.json.return_value = json_data
        if text_data:
            response.text = text_data
        if not json_data and not text_data:
            response.json.return_value = {"success": True}
            
        return response
    
    @staticmethod
    def create_mock_environment(
        env_key: Optional[str] = None,
        **overrides
    ) -> Mock:
        """Create a mock environment object."""
        env_data = MOCK_ENVIRONMENTS[0].copy()
        if env_key:
            env_data["key"] = env_key
        env_data.update(overrides)
        
        mock_env = Mock()
        mock_env.key = env_data["key"]
        mock_env.name = env_data["name"]
        mock_env.default_version = env_data["default_version"]
        mock_env.region = env_data["region"]
        mock_env.status = env_data["status"]
        mock_env.created_at = env_data["created_at"]
        mock_env.updated_at = env_data["updated_at"]
        
        return mock_env
    
    @staticmethod
    def create_mock_instance(
        instance_id: Optional[str] = None,
        env_key: Optional[str] = None,
        **overrides
    ) -> Mock:
        """Create a mock instance object."""
        instance_data = MOCK_INSTANCE.copy()
        if instance_id:
            instance_data["id"] = instance_id
        if env_key:
            instance_data["env_key"] = env_key
        instance_data.update(overrides)
        
        mock_instance = Mock()
        mock_instance.id = instance_data["id"]
        mock_instance.env_key = instance_data["env_key"]
        mock_instance.status = instance_data["status"]
        mock_instance.region = instance_data["region"]
        mock_instance.created_at = instance_data["created_at"]
        mock_instance.updated_at = instance_data["updated_at"]
        mock_instance.terminated_at = instance_data["terminated_at"]
        mock_instance.resources = instance_data["resources"]
        
        return mock_instance
    
    @staticmethod
    def create_mock_database_resource() -> Mock:
        """Create a mock database resource."""
        mock_db = Mock()
        mock_db.query.return_value = MOCK_QUERY_RESULTS["users"]
        mock_db.exec.return_value = {"rows_affected": 1}
        mock_db.describe.return_value = MOCK_DATABASE_SCHEMA
        mock_db.table.return_value = Mock()
        mock_db.table.return_value.eq.return_value = Mock()
        mock_db.table.return_value.eq.return_value.all.return_value = MOCK_QUERY_RESULTS["users"]
        
        return mock_db
    
    @staticmethod
    def create_mock_browser_resource() -> Mock:
        """Create a mock browser resource."""
        mock_browser = Mock()
        mock_browser.cdp_url = MOCK_BROWSER_DATA["cdp_url"]
        mock_browser.devtools_url = MOCK_BROWSER_DATA["devtools_url"]
        mock_browser.user_agent = MOCK_BROWSER_DATA["user_agent"]
        mock_browser.viewport = MOCK_BROWSER_DATA["viewport"]
        mock_browser.cookies = MOCK_BROWSER_DATA["cookies"]
        mock_browser.local_storage = MOCK_BROWSER_DATA["local_storage"]
        mock_browser.session_storage = MOCK_BROWSER_DATA["session_storage"]
        
        return mock_browser
    
    @staticmethod
    def create_mock_verifier_result(success: bool = True) -> Mock:
        """Create a mock verifier result."""
        result_data = MOCK_VERIFIER_RESULT if success else MOCK_VERIFIER_FAILURE
        
        mock_result = Mock()
        mock_result.success = result_data["success"]
        mock_result.message = result_data["message"]
        mock_result.execution_time = result_data["execution_time"]
        mock_result.timestamp = result_data["timestamp"]
        mock_result.details = result_data["details"]
        
        return mock_result
    
    @staticmethod
    def create_mock_task(
        task_id: Optional[str] = None,
        env_id: Optional[str] = None,
        **overrides
    ) -> Mock:
        """Create a mock task object."""
        task_data = MOCK_TASK.copy()
        if task_id:
            task_data["id"] = task_id
        if env_id:
            task_data["env_id"] = env_id
        task_data.update(overrides)
        
        mock_task = Mock()
        mock_task.id = task_data["id"]
        mock_task.name = task_data["name"]
        mock_task.description = task_data["description"]
        mock_task.env_id = task_data["env_id"]
        mock_task.version = task_data["version"]
        mock_task.status = task_data["status"]
        mock_task.created_at = task_data["created_at"]
        mock_task.updated_at = task_data["updated_at"]
        mock_task.metadata = task_data["metadata"].copy()  # Ensure it's a real dict, not a reference
        
        return mock_task


class DataGenerator:
    """Utility class for generating test data."""
    
    @staticmethod
    def generate_random_string(length: int = 10) -> str:
        """Generate a random string."""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
    
    @staticmethod
    def generate_random_email() -> str:
        """Generate a random email address."""
        username = DataGenerator.generate_random_string(8)
        domain = random.choice(["example.com", "test.com", "mock.org"])
        return f"{username}@{domain}"
    
    @staticmethod
    def generate_random_timestamp() -> str:
        """Generate a random ISO timestamp."""
        now = datetime.now(timezone.utc)
        random_offset = random.randint(-86400, 86400)  # ±1 day
        timestamp = datetime.fromtimestamp(now.timestamp() + random_offset, tz=timezone.utc)
        return timestamp.isoformat()
    
    @staticmethod
    def generate_mock_user(**overrides) -> Dict[str, Any]:
        """Generate a mock user data."""
        user_data = {
            "id": random.randint(1, 1000),
            "name": f"User {DataGenerator.generate_random_string(5)}",
            "email": DataGenerator.generate_random_email(),
            "created_at": DataGenerator.generate_random_timestamp()
        }
        user_data.update(overrides)
        return user_data
    
    @staticmethod
    def generate_mock_order(**overrides) -> Dict[str, Any]:
        """Generate a mock order data."""
        order_data = {
            "id": random.randint(1, 1000),
            "user_id": random.randint(1, 100),
            "amount": round(random.uniform(10.0, 1000.0), 2),
            "status": random.choice(["pending", "completed", "cancelled"]),
            "created_at": DataGenerator.generate_random_timestamp()
        }
        order_data.update(overrides)
        return order_data
    
    @staticmethod
    def generate_mock_environment_list(count: int = 3) -> List[Dict[str, Any]]:
        """Generate a list of mock environments."""
        environments = []
        for i in range(count):
            env_data = MOCK_ENVIRONMENTS[i % len(MOCK_ENVIRONMENTS)].copy()
            env_data["key"] = f"env_{i}_{DataGenerator.generate_random_string(5)}"
            environments.append(env_data)
        return environments


class AsyncMockHelper:
    """Helper for creating async mocks."""
    
    @staticmethod
    def create_async_mock_response(
        status_code: int = 200,
        json_data: Optional[Dict] = None,
        text_data: Optional[str] = None,
        headers: Optional[Dict] = None
    ) -> AsyncMock:
        """Create an async mock HTTP response."""
        response = AsyncMock()
        response.status_code = status_code
        response.headers = headers or {"Content-Type": "application/json"}
        
        if json_data:
            response.json.return_value = json_data
        if text_data:
            response.text = text_data
        if not json_data and not text_data:
            response.json.return_value = {"success": True}
            
        return response
    
    @staticmethod
    def create_async_mock_environment(**overrides) -> AsyncMock:
        """Create an async mock environment."""
        mock_env = AsyncMock()
        mock_env.key = overrides.get("key", MOCK_ENVIRONMENTS[0]["key"])
        mock_env.name = overrides.get("name", MOCK_ENVIRONMENTS[0]["name"])
        mock_env.default_version = overrides.get("default_version", MOCK_ENVIRONMENTS[0]["default_version"])
        mock_env.region = overrides.get("region", MOCK_ENVIRONMENTS[0]["region"])
        mock_env.status = overrides.get("status", MOCK_ENVIRONMENTS[0]["status"])
        mock_env.created_at = overrides.get("created_at", MOCK_ENVIRONMENTS[0]["created_at"])
        mock_env.updated_at = overrides.get("updated_at", MOCK_ENVIRONMENTS[0]["updated_at"])
        
        # Mock async methods
        mock_env.close = AsyncMock()
        mock_env.reset = AsyncMock()
        mock_env.db = AsyncMock()
        mock_env.browser = AsyncMock()
        
        return mock_env
    
    @staticmethod
    def create_async_mock_database() -> AsyncMock:
        """Create an async mock database."""
        mock_db = AsyncMock()
        mock_db.query = AsyncMock(return_value=MOCK_QUERY_RESULTS["users"])
        mock_db.exec = AsyncMock(return_value={"rows_affected": 1})
        mock_db.describe = AsyncMock(return_value=MOCK_DATABASE_SCHEMA)
        
        # Mock table query builder
        mock_table = AsyncMock()
        mock_table.eq = AsyncMock(return_value=mock_table)
        mock_table.all = AsyncMock(return_value=MOCK_QUERY_RESULTS["users"])
        mock_db.table = AsyncMock(return_value=mock_table)
        
        return mock_db
    
    @staticmethod
    def create_async_mock_browser() -> AsyncMock:
        """Create an async mock browser."""
        mock_browser = AsyncMock()
        mock_browser.cdp_url = MOCK_BROWSER_DATA["cdp_url"]
        mock_browser.devtools_url = MOCK_BROWSER_DATA["devtools_url"]
        mock_browser.user_agent = MOCK_BROWSER_DATA["user_agent"]
        mock_browser.viewport = MOCK_BROWSER_DATA["viewport"]
        mock_browser.cookies = MOCK_BROWSER_DATA["cookies"]
        mock_browser.local_storage = MOCK_BROWSER_DATA["local_storage"]
        mock_browser.session_storage = MOCK_BROWSER_DATA["session_storage"]
        
        return mock_browser


class _TestDataBuilder:
    """Builder pattern for creating complex test data."""
    
    def __init__(self):
        self.data = {}
    
    def with_id(self, id_value: str) -> 'TestDataBuilder':
        """Add ID to test data."""
        self.data["id"] = id_value
        return self
    
    def with_name(self, name: str) -> 'TestDataBuilder':
        """Add name to test data."""
        self.data["name"] = name
        return self
    
    def with_status(self, status: str) -> 'TestDataBuilder':
        """Add status to test data."""
        self.data["status"] = status
        return self
    
    def with_metadata(self, metadata: Dict[str, Any]) -> 'TestDataBuilder':
        """Add metadata to test data."""
        self.data["metadata"] = metadata
        return self
    
    def with_timestamp(self, timestamp: Optional[str] = None) -> 'TestDataBuilder':
        """Add timestamp to test data."""
        if timestamp is None:
            timestamp = DataGenerator.generate_random_timestamp()
        self.data["created_at"] = timestamp
        self.data["updated_at"] = timestamp
        return self
    
    def build(self) -> Dict[str, Any]:
        """Build the final test data."""
        return self.data.copy()


class MockValidator:
    """Utility for validating mock data."""
    
    @staticmethod
    def validate_environment_data(data: Dict[str, Any]) -> bool:
        """Validate environment data structure."""
        required_fields = ["key", "name", "default_version", "region", "status"]
        return all(field in data for field in required_fields)
    
    @staticmethod
    def validate_instance_data(data: Dict[str, Any]) -> bool:
        """Validate instance data structure."""
        required_fields = ["id", "env_key", "status", "region"]
        return all(field in data for field in required_fields)
    
    @staticmethod
    def validate_query_result(data: Any) -> bool:
        """Validate database query result."""
        return isinstance(data, (list, dict)) and len(data) > 0
    
    @staticmethod
    def validate_verifier_result(data: Dict[str, Any]) -> bool:
        """Validate verifier result structure."""
        required_fields = ["success", "message", "execution_time", "timestamp"]
        return all(field in data for field in required_fields)


class PerformanceSimulator:
    """Simulate performance characteristics for testing."""
    
    @staticmethod
    def simulate_delay(min_time: float = 0.01, max_time: float = 0.1) -> float:
        """Simulate operation delay."""
        return random.uniform(min_time, max_time)
    
    @staticmethod
    async def simulate_async_delay(min_time: float = 0.01, max_time: float = 0.1) -> float:
        """Simulate async operation delay."""
        delay = PerformanceSimulator.simulate_delay(min_time, max_time)
        await asyncio.sleep(delay)
        return delay
    
    @staticmethod
    def simulate_timeout_error() -> Exception:
        """Simulate a timeout error."""
        return TimeoutError("Operation timed out")
    
    @staticmethod
    def simulate_network_error() -> Exception:
        """Simulate a network error."""
        return ConnectionError("Network connection failed")
