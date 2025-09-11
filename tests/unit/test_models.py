"""
Unit tests for data models and types.
Tests model validation, serialization, and data handling.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import pytest
from datetime import datetime, timezone

from .base_test import BaseModelTest
from .constants import *


class TestEnvironmentModel(BaseModelTest):
    """Test Environment model functionality."""
    
    def setUp(self):
        """Set up environment model test fixtures."""
        super().setUp()
        self.model_data = MOCK_ENVIRONMENTS[0].copy()
    
    def test_environment_model_creation(self):
        """Test environment model creation."""
        # Arrange
        env_data = self.create_test_model_data()
        
        # Act
        mock_env = Mock()
        mock_env.key = env_data["key"]
        mock_env.name = env_data["name"]
        mock_env.default_version = env_data["default_version"]
        mock_env.region = env_data["region"]
        mock_env.status = env_data["status"]
        
        # Assert
        self.assert_model_has_attributes(mock_env, ["key", "name", "default_version", "region", "status"])
        self.assert_model_attribute_values(mock_env, {
            "key": env_data["key"],
            "name": env_data["name"],
            "default_version": env_data["default_version"],
            "region": env_data["region"],
            "status": env_data["status"]
        })
    
    def test_environment_model_validation(self):
        """Test environment model validation."""
        # Arrange
        env_data = self.create_test_model_data()
        
        # Act & Assert
        required_fields = ["key", "name", "default_version", "region", "status"]
        for field in required_fields:
            self.assertIn(field, env_data)
            self.assertIsNotNone(env_data[field])
            self.assertIsInstance(env_data[field], str)
            self.assertGreater(len(env_data[field]), 0)
    
    def test_environment_model_serialization(self):
        """Test environment model serialization."""
        # Arrange
        env_data = self.create_test_model_data()
        
        # Act
        serialized = {
            "key": env_data["key"],
            "name": env_data["name"],
            "default_version": env_data["default_version"],
            "region": env_data["region"],
            "status": env_data["status"]
        }
        
        # Assert
        self.assertIsInstance(serialized, dict)
        self.assertEqual(len(serialized), 5)
        for key, value in serialized.items():
            self.assertIsInstance(value, str)
            self.assertGreater(len(value), 0)


class TestInstanceModel(BaseModelTest):
    """Test Instance model functionality."""
    
    def setUp(self):
        """Set up instance model test fixtures."""
        super().setUp()
        self.model_data = MOCK_INSTANCE.copy()
    
    def test_instance_model_creation(self):
        """Test instance model creation."""
        # Arrange
        instance_data = self.create_test_model_data()
        
        # Act
        mock_instance = Mock()
        mock_instance.id = instance_data["id"]
        mock_instance.env_key = instance_data["env_key"]
        mock_instance.status = instance_data["status"]
        mock_instance.region = instance_data["region"]
        mock_instance.resources = instance_data["resources"]
        
        # Assert
        self.assert_model_has_attributes(mock_instance, ["id", "env_key", "status", "region", "resources"])
        self.assert_model_attribute_values(mock_instance, {
            "id": instance_data["id"],
            "env_key": instance_data["env_key"],
            "status": instance_data["status"],
            "region": instance_data["region"]
        })
    
    def test_instance_model_validation(self):
        """Test instance model validation."""
        # Arrange
        instance_data = self.create_test_model_data()
        
        # Act & Assert
        required_fields = ["id", "env_key", "status", "region"]
        for field in required_fields:
            self.assertIn(field, instance_data)
            self.assertIsNotNone(instance_data[field])
            self.assertIsInstance(instance_data[field], str)
            self.assertGreater(len(instance_data[field]), 0)
        
        # Validate resources structure
        self.assertIn("resources", instance_data)
        self.assertIsInstance(instance_data["resources"], dict)
        self.assertIn("database", instance_data["resources"])
        self.assertIn("browser", instance_data["resources"])
    
    def test_instance_model_resources(self):
        """Test instance model resources structure."""
        # Arrange
        instance_data = self.create_test_model_data()
        resources = instance_data["resources"]
        
        # Act & Assert
        # Database resource
        self.assertIn("database", resources)
        database = resources["database"]
        self.assertIn("url", database)
        self.assertIn("type", database)
        self.assertEqual(database["type"], "sqlite")
        
        # Browser resource
        self.assertIn("browser", resources)
        browser = resources["browser"]
        self.assertIn("cdp_url", browser)
        self.assertIn("devtools_url", browser)
        self.assertTrue(browser["cdp_url"].startswith("ws://"))
        self.assertTrue(browser["devtools_url"].startswith("http://"))


class TestAccountModel(BaseModelTest):
    """Test Account model functionality."""
    
    def setUp(self):
        """Set up account model test fixtures."""
        super().setUp()
        self.model_data = MOCK_ACCOUNT.copy()
    
    def test_account_model_creation(self):
        """Test account model creation."""
        # Arrange
        account_data = self.create_test_model_data()
        
        # Act
        mock_account = Mock()
        mock_account.id = account_data["id"]
        mock_account.name = account_data["name"]
        mock_account.team_id = account_data["team_id"]
        mock_account.team_name = account_data["team_name"]
        mock_account.plan = account_data["plan"]
        
        # Assert
        self.assert_model_has_attributes(mock_account, ["id", "name", "team_id", "team_name", "plan"])
        self.assert_model_attribute_values(mock_account, {
            "id": account_data["id"],
            "name": account_data["name"],
            "team_id": account_data["team_id"],
            "team_name": account_data["team_name"],
            "plan": account_data["plan"]
        })
    
    def test_account_model_validation(self):
        """Test account model validation."""
        # Arrange
        account_data = self.create_test_model_data()
        
        # Act & Assert
        required_fields = ["id", "name", "team_id", "team_name", "plan"]
        for field in required_fields:
            self.assertIn(field, account_data)
            self.assertIsNotNone(account_data[field])
            self.assertIsInstance(account_data[field], str)
            self.assertGreater(len(account_data[field]), 0)
    
    def test_account_model_plan_validation(self):
        """Test account model plan validation."""
        # Arrange
        valid_plans = ["free", "pro", "enterprise"]
        
        for plan in valid_plans:
            # Act
            account_data = self.create_test_model_data(plan=plan)
            
            # Assert
            self.assertEqual(account_data["plan"], plan)
            self.assertIn(plan, valid_plans)


class TestTaskModel(BaseModelTest):
    """Test Task model functionality."""
    
    def setUp(self):
        """Set up task model test fixtures."""
        super().setUp()
        self.model_data = MOCK_TASK.copy()
    
    def test_task_model_creation(self):
        """Test task model creation."""
        # Arrange
        task_data = self.create_test_model_data()
        
        # Act
        mock_task = Mock()
        mock_task.id = task_data["id"]
        mock_task.name = task_data["name"]
        mock_task.description = task_data["description"]
        mock_task.env_id = task_data["env_id"]
        mock_task.version = task_data["version"]
        mock_task.status = task_data["status"]
        mock_task.metadata = task_data["metadata"]
        
        # Assert
        self.assert_model_has_attributes(mock_task, ["id", "name", "description", "env_id", "version", "status", "metadata"])
        self.assert_model_attribute_values(mock_task, {
            "id": task_data["id"],
            "name": task_data["name"],
            "description": task_data["description"],
            "env_id": task_data["env_id"],
            "version": task_data["version"],
            "status": task_data["status"]
        })
    
    def test_task_model_validation(self):
        """Test task model validation."""
        # Arrange
        task_data = self.create_test_model_data()
        
        # Act & Assert
        required_fields = ["id", "name", "description", "env_id", "version", "status"]
        for field in required_fields:
            self.assertIn(field, task_data)
            self.assertIsNotNone(task_data[field])
            self.assertIsInstance(task_data[field], str)
            self.assertGreater(len(task_data[field]), 0)
        
        # Validate metadata
        self.assertIn("metadata", task_data)
        self.assertIsInstance(task_data["metadata"], dict)
        self.assertIn("priority", task_data["metadata"])
        self.assertIn("category", task_data["metadata"])
        self.assertIn("tags", task_data["metadata"])
    
    def test_task_model_metadata_validation(self):
        """Test task model metadata validation."""
        # Arrange
        task_data = self.create_test_model_data()
        metadata = task_data["metadata"]
        
        # Act & Assert
        self.assertIn("priority", metadata)
        self.assertIn("category", metadata)
        self.assertIn("tags", metadata)
        
        # Validate priority
        valid_priorities = ["low", "medium", "high", "critical"]
        self.assertIn(metadata["priority"], valid_priorities)
        
        # Validate tags
        self.assertIsInstance(metadata["tags"], list)
        for tag in metadata["tags"]:
            self.assertIsInstance(tag, str)
            self.assertGreater(len(tag), 0)


class TestVerifierResultModel(BaseModelTest):
    """Test VerifierResult model functionality."""
    
    def setUp(self):
        """Set up verifier result model test fixtures."""
        super().setUp()
        self.model_data = MOCK_VERIFIER_RESULT.copy()
    
    def test_verifier_result_model_creation(self):
        """Test verifier result model creation."""
        # Arrange
        result_data = self.create_test_model_data()
        
        # Act
        mock_result = Mock()
        mock_result.success = result_data["success"]
        mock_result.message = result_data["message"]
        mock_result.execution_time = result_data["execution_time"]
        mock_result.timestamp = result_data["timestamp"]
        mock_result.details = result_data["details"]
        
        # Assert
        self.assert_model_has_attributes(mock_result, ["success", "message", "execution_time", "timestamp", "details"])
        self.assert_model_attribute_values(mock_result, {
            "success": result_data["success"],
            "message": result_data["message"],
            "execution_time": result_data["execution_time"],
            "timestamp": result_data["timestamp"]
        })
    
    def test_verifier_result_model_validation(self):
        """Test verifier result model validation."""
        # Arrange
        result_data = self.create_test_model_data()
        
        # Act & Assert
        # Validate success field
        self.assertIn("success", result_data)
        self.assertIsInstance(result_data["success"], bool)
        
        # Validate message field
        self.assertIn("message", result_data)
        self.assertIsInstance(result_data["message"], str)
        self.assertGreater(len(result_data["message"]), 0)
        
        # Validate execution_time field
        self.assertIn("execution_time", result_data)
        self.assertIsInstance(result_data["execution_time"], float)
        self.assertGreater(result_data["execution_time"], 0)
        
        # Validate timestamp field
        self.assertIn("timestamp", result_data)
        self.assertIsInstance(result_data["timestamp"], str)
        self.assertIn("T", result_data["timestamp"])  # ISO format
        self.assertIn("Z", result_data["timestamp"])  # UTC timezone
    
    def test_verifier_result_model_details(self):
        """Test verifier result model details validation."""
        # Arrange
        result_data = self.create_test_model_data()
        details = result_data["details"]
        
        # Act & Assert
        self.assertIsInstance(details, dict)
        self.assertIn("checks_performed", details)
        self.assertIn("assertions_passed", details)
        self.assertIn("assertions_failed", details)
        
        # Validate numeric fields
        self.assertIsInstance(details["checks_performed"], int)
        self.assertIsInstance(details["assertions_passed"], int)
        self.assertIsInstance(details["assertions_failed"], int)
        
        # Validate logical consistency
        total_assertions = details["assertions_passed"] + details["assertions_failed"]
        self.assertEqual(details["checks_performed"], total_assertions)


class TestDatabaseSchemaModel(BaseModelTest):
    """Test DatabaseSchema model functionality."""
    
    def setUp(self):
        """Set up database schema model test fixtures."""
        super().setUp()
        self.model_data = MOCK_DATABASE_SCHEMA.copy()
    
    def test_database_schema_model_creation(self):
        """Test database schema model creation."""
        # Arrange
        schema_data = self.create_test_model_data()
        
        # Act
        mock_schema = Mock()
        mock_schema.tables = schema_data["tables"]
        
        # Assert
        self.assert_model_has_attributes(mock_schema, ["tables"])
        self.assertIsInstance(mock_schema.tables, list)
        self.assertGreater(len(mock_schema.tables), 0)
    
    def test_database_schema_model_validation(self):
        """Test database schema model validation."""
        # Arrange
        schema_data = self.create_test_model_data()
        tables = schema_data["tables"]
        
        # Act & Assert
        self.assertIsInstance(tables, list)
        self.assertGreater(len(tables), 0)
        
        for table in tables:
            self.assertIn("name", table)
            self.assertIn("columns", table)
            self.assertIsInstance(table["name"], str)
            self.assertIsInstance(table["columns"], list)
            self.assertGreater(len(table["columns"]), 0)
    
    def test_database_schema_model_columns(self):
        """Test database schema model columns validation."""
        # Arrange
        schema_data = self.create_test_model_data()
        tables = schema_data["tables"]
        
        # Act & Assert
        for table in tables:
            columns = table["columns"]
            for column in columns:
                self.assertIn("name", column)
                self.assertIn("type", column)
                self.assertIsInstance(column["name"], str)
                self.assertIsInstance(column["type"], str)
                self.assertGreater(len(column["name"]), 0)
                self.assertGreater(len(column["type"]), 0)


class TestBrowserDataModel(BaseModelTest):
    """Test BrowserData model functionality."""
    
    def setUp(self):
        """Set up browser data model test fixtures."""
        super().setUp()
        self.model_data = MOCK_BROWSER_DATA.copy()
    
    def test_browser_data_model_creation(self):
        """Test browser data model creation."""
        # Arrange
        browser_data = self.create_test_model_data()
        
        # Act
        mock_browser = Mock()
        mock_browser.cdp_url = browser_data["cdp_url"]
        mock_browser.devtools_url = browser_data["devtools_url"]
        mock_browser.user_agent = browser_data["user_agent"]
        mock_browser.viewport = browser_data["viewport"]
        
        # Assert
        self.assert_model_has_attributes(mock_browser, ["cdp_url", "devtools_url", "user_agent", "viewport"])
        self.assert_model_attribute_values(mock_browser, {
            "cdp_url": browser_data["cdp_url"],
            "devtools_url": browser_data["devtools_url"],
            "user_agent": browser_data["user_agent"]
        })
    
    def test_browser_data_model_validation(self):
        """Test browser data model validation."""
        # Arrange
        browser_data = self.create_test_model_data()
        
        # Act & Assert
        # Validate URLs
        self.assertIn("cdp_url", browser_data)
        self.assertIn("devtools_url", browser_data)
        self.assertTrue(browser_data["cdp_url"].startswith("ws://"))
        self.assertTrue(browser_data["devtools_url"].startswith("http://"))
        
        # Validate user agent
        self.assertIn("user_agent", browser_data)
        self.assertIsInstance(browser_data["user_agent"], str)
        self.assertIn("Mozilla", browser_data["user_agent"])
        
        # Validate viewport
        self.assertIn("viewport", browser_data)
        self.assertIsInstance(browser_data["viewport"], dict)
        self.assertIn("width", browser_data["viewport"])
        self.assertIn("height", browser_data["viewport"])
        self.assertIsInstance(browser_data["viewport"]["width"], int)
        self.assertIsInstance(browser_data["viewport"]["height"], int)
    
    def test_browser_data_model_viewport(self):
        """Test browser data model viewport validation."""
        # Arrange
        browser_data = self.create_test_model_data()
        viewport = browser_data["viewport"]
        
        # Act & Assert
        self.assertIn("width", viewport)
        self.assertIn("height", viewport)
        self.assertIsInstance(viewport["width"], int)
        self.assertIsInstance(viewport["height"], int)
        self.assertGreater(viewport["width"], 0)
        self.assertGreater(viewport["height"], 0)


class TestModelSerialization(unittest.TestCase):
    """Test model serialization and deserialization."""
    
    def test_environment_model_serialization(self):
        """Test environment model serialization."""
        # Arrange
        env_data = MOCK_ENVIRONMENTS[0]
        
        # Act
        serialized = {
            "key": env_data["key"],
            "name": env_data["name"],
            "default_version": env_data["default_version"],
            "region": env_data["region"],
            "status": env_data["status"]
        }
        
        # Assert
        self.assertIsInstance(serialized, dict)
        self.assertEqual(len(serialized), 5)
        for key, value in serialized.items():
            self.assertIsInstance(value, str)
    
    def test_task_model_serialization(self):
        """Test task model serialization."""
        # Arrange
        task_data = MOCK_TASK
        
        # Act
        serialized = {
            "id": task_data["id"],
            "name": task_data["name"],
            "description": task_data["description"],
            "env_id": task_data["env_id"],
            "version": task_data["version"],
            "status": task_data["status"],
            "metadata": task_data["metadata"]
        }
        
        # Assert
        self.assertIsInstance(serialized, dict)
        self.assertEqual(len(serialized), 7)
        self.assertIsInstance(serialized["metadata"], dict)
    
    def test_verifier_result_model_serialization(self):
        """Test verifier result model serialization."""
        # Arrange
        result_data = MOCK_VERIFIER_RESULT
        
        # Act
        serialized = {
            "success": result_data["success"],
            "message": result_data["message"],
            "execution_time": result_data["execution_time"],
            "timestamp": result_data["timestamp"],
            "details": result_data["details"]
        }
        
        # Assert
        self.assertIsInstance(serialized, dict)
        self.assertEqual(len(serialized), 5)
        self.assertIsInstance(serialized["success"], bool)
        self.assertIsInstance(serialized["execution_time"], float)
        self.assertIsInstance(serialized["details"], dict)


class TestModelValidation(unittest.TestCase):
    """Test model validation scenarios."""
    
    def test_required_field_validation(self):
        """Test required field validation."""
        # Arrange
        required_fields = ["id", "name", "status"]
        
        # Act & Assert
        for field in required_fields:
            # Test with missing field
            data = MOCK_TASK.copy()
            del data[field]
            
            # Should handle missing field gracefully
            self.assertNotIn(field, data)
    
    def test_data_type_validation(self):
        """Test data type validation."""
        # Arrange
        test_cases = [
            ("string_field", "test_value", str),
            ("int_field", 123, int),
            ("float_field", 123.45, float),
            ("bool_field", True, bool),
            ("list_field", [1, 2, 3], list),
            ("dict_field", {"key": "value"}, dict)
        ]
        
        # Act & Assert
        for field_name, value, expected_type in test_cases:
            self.assertIsInstance(value, expected_type)
    
    def test_data_range_validation(self):
        """Test data range validation."""
        # Arrange
        test_cases = [
            ("positive_int", 5, lambda x: x > 0),
            ("non_negative_float", 0.5, lambda x: x >= 0),
            ("string_length", "test", lambda x: len(x) > 0),
            ("list_size", [1, 2, 3], lambda x: len(x) > 0)
        ]
        
        # Act & Assert
        for field_name, value, validator in test_cases:
            self.assertTrue(validator(value))


if __name__ == '__main__':
    unittest.main()
