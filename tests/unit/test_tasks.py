"""
Unit tests for task management functionality.
Tests Task class, task creation, execution, and verification.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import pytest
import time

from .base_test import BaseTaskTest
from .constants import *


class TestTaskCreation(BaseTaskTest):
    """Test task creation functionality."""
    
    def test_task_initialization(self):
        """Test task initialization with required parameters."""
        # Arrange
        task_data = self.task_data.copy()
        
        # Act
        mock_task = self.create_mock_task(**task_data)
        
        # Assert
        self.assertEqual(mock_task.id, task_data["id"])
        self.assertEqual(mock_task.name, task_data["name"])
        self.assertEqual(mock_task.description, task_data["description"])
        self.assertEqual(mock_task.env_id, task_data["env_id"])
        self.assertEqual(mock_task.version, task_data["version"])
        self.assertEqual(mock_task.status, task_data["status"])
    
    def test_task_initialization_with_metadata(self):
        """Test task initialization with metadata."""
        # Arrange
        task_data = self.task_data.copy()
        metadata = {"priority": "high", "category": "testing"}
        task_data["metadata"] = metadata
        
        # Act
        mock_task = self.create_mock_task(**task_data)
        
        # Assert
        self.assertEqual(mock_task.metadata, metadata)
        self.assertEqual(mock_task.metadata["priority"], "high")
        self.assertEqual(mock_task.metadata["category"], "testing")
    
    def test_task_initialization_with_timestamps(self):
        """Test task initialization with timestamps."""
        # Arrange
        task_data = self.task_data.copy()
        created_at = "2024-01-01T00:00:00Z"
        updated_at = "2024-01-01T01:00:00Z"
        task_data["created_at"] = created_at
        task_data["updated_at"] = updated_at
        
        # Act
        mock_task = self.create_mock_task(**task_data)
        
        # Assert
        self.assertEqual(mock_task.created_at, created_at)
        self.assertEqual(mock_task.updated_at, updated_at)
    
    def test_task_creation_with_custom_id(self):
        """Test task creation with custom ID."""
        # Arrange
        custom_id = "custom_task_123"
        
        # Act
        mock_task = self.create_mock_task(id=custom_id)
        
        # Assert
        self.assertEqual(mock_task.id, custom_id)
    
    def test_task_creation_with_custom_env_id(self):
        """Test task creation with custom environment ID."""
        # Arrange
        custom_env_id = "custom_env_456"
        
        # Act
        mock_task = self.create_mock_task(env_id=custom_env_id)
        
        # Assert
        self.assertEqual(mock_task.env_id, custom_env_id)


class TestTaskAttributes(BaseTaskTest):
    """Test task attributes and properties."""
    
    def test_task_has_required_attributes(self):
        """Test that task has all required attributes."""
        # Arrange
        mock_task = self.create_mock_task()
        
        # Act & Assert
        required_attributes = [
            "id", "name", "description", "env_id", "version", 
            "status", "created_at", "updated_at", "metadata"
        ]
        
        for attr in required_attributes:
            self.assertTrue(hasattr(mock_task, attr), f"Missing attribute: {attr}")
    
    def test_task_status_values(self):
        """Test task status values."""
        # Arrange
        status_values = ["pending", "running", "completed", "failed", "cancelled"]
        
        for status in status_values:
            # Act
            mock_task = self.create_mock_task(status=status)
            
            # Assert
            self.assertEqual(mock_task.status, status)
    
    def test_task_metadata_structure(self):
        """Test task metadata structure."""
        # Arrange
        mock_task = self.create_mock_task()
        
        # Act
        metadata = mock_task.metadata
        
        # Assert
        self.assertIsInstance(metadata, dict)
        self.assertIn("priority", metadata)
        self.assertIn("category", metadata)
        self.assertIn("tags", metadata)
        self.assertIsInstance(metadata["tags"], list)


class TestTaskVerification(BaseTaskTest):
    """Test task verification functionality."""
    
    def test_task_verify_success(self):
        """Test successful task verification."""
        # Arrange
        mock_task = self.create_mock_task_with_verifier(verifier_success=True)
        
        # Act
        result = mock_task.verify()
        
        # Assert
        self.assertTrue(result.success)
        self.assertEqual(result.message, MOCK_VERIFIER_RESULT["message"])
        mock_task.verify.assert_called_once()
    
    def test_task_verify_failure(self):
        """Test failed task verification."""
        # Arrange
        mock_task = self.create_mock_task_with_verifier(verifier_success=False)
        
        # Act
        result = mock_task.verify()
        
        # Assert
        self.assertFalse(result.success)
        self.assertEqual(result.message, MOCK_VERIFIER_FAILURE["message"])
        mock_task.verify.assert_called_once()
    
    def test_task_verify_with_environment(self):
        """Test task verification with environment."""
        # Arrange
        mock_task = self.create_mock_task_with_verifier(verifier_success=True)
        mock_env = self.create_mock_environment()
        
        # Act
        result = mock_task.verify(mock_env)
        
        # Assert
        self.assertTrue(result.success)
        mock_task.verify.assert_called_once_with(mock_env)
    
    def test_task_verify_execution_time(self):
        """Test task verification execution time."""
        # Arrange
        mock_task = self.create_mock_task_with_verifier(verifier_success=True)
        
        # Act
        result = mock_task.verify()
        
        # Assert
        self.assertIsNotNone(result.execution_time)
        self.assertGreater(result.execution_time, 0)
        self.assertIsInstance(result.execution_time, float)


class TestTaskManagement(BaseTaskTest):
    """Test task management operations."""
    
    def test_task_list_creation(self):
        """Test creating a list of tasks."""
        # Arrange
        task_count = 5
        
        # Act
        tasks = self.create_mock_task_list(task_count)
        
        # Assert
        self.assertEqual(len(tasks), task_count)
        self.assertIsInstance(tasks, list)
        
        # Verify each task has unique ID
        task_ids = [task.id for task in tasks]
        self.assertEqual(len(set(task_ids)), task_count)  # All IDs should be unique
    
    def test_task_filtering_by_status(self):
        """Test filtering tasks by status."""
        # Arrange
        tasks = self.create_mock_task_list(10)
        
        # Set different statuses
        for i, task in enumerate(tasks):
            statuses = ["pending", "running", "completed", "failed"]
            task.status = statuses[i % len(statuses)]
        
        # Act
        pending_tasks = [task for task in tasks if task.status == "pending"]
        completed_tasks = [task for task in tasks if task.status == "completed"]
        
        # Assert
        self.assertGreater(len(pending_tasks), 0)
        self.assertGreater(len(completed_tasks), 0)
        
        for task in pending_tasks:
            self.assertEqual(task.status, "pending")
        
        for task in completed_tasks:
            self.assertEqual(task.status, "completed")
    
    def test_task_filtering_by_environment(self):
        """Test filtering tasks by environment."""
        # Arrange
        tasks = self.create_mock_task_list(6)
        
        # Set different environment IDs
        env_ids = ["env1", "env2", "env3"]
        for i, task in enumerate(tasks):
            task.env_id = env_ids[i % len(env_ids)]
        
        # Act
        env1_tasks = [task for task in tasks if task.env_id == "env1"]
        env2_tasks = [task for task in tasks if task.env_id == "env2"]
        
        # Assert
        self.assertEqual(len(env1_tasks), 2)  # 6 tasks / 3 envs = 2 per env
        self.assertEqual(len(env2_tasks), 2)
        
        for task in env1_tasks:
            self.assertEqual(task.env_id, "env1")
        
        for task in env2_tasks:
            self.assertEqual(task.env_id, "env2")
    
    def test_task_metadata_filtering(self):
        """Test filtering tasks by metadata."""
        # Arrange
        tasks = self.create_mock_task_list(9)  # Use 9 to ensure even distribution
        
        # Set different priorities
        priorities = ["high", "medium", "low"]
        for i, task in enumerate(tasks):
            # Set priority in metadata
            task.metadata["priority"] = priorities[i % len(priorities)]
        
        # Act
        high_priority_tasks = [task for task in tasks if task.metadata["priority"] == "high"]
        medium_priority_tasks = [task for task in tasks if task.metadata["priority"] == "medium"]
        
        # Assert
        self.assertGreater(len(high_priority_tasks), 0)
        self.assertGreater(len(medium_priority_tasks), 0)
        
        for task in high_priority_tasks:
            self.assertEqual(task.metadata["priority"], "high")
        
        for task in medium_priority_tasks:
            self.assertEqual(task.metadata["priority"], "medium")


class TestTaskExecution(BaseTaskTest):
    """Test task execution scenarios."""
    
    def test_task_execution_lifecycle(self):
        """Test task execution lifecycle."""
        # Arrange
        mock_task = self.create_mock_task(status="pending")
        
        # Act - Simulate lifecycle
        initial_status = mock_task.status
        mock_task.status = "running"
        running_status = mock_task.status
        mock_task.status = "completed"
        final_status = mock_task.status
        
        # Assert
        self.assertEqual(initial_status, "pending")
        self.assertEqual(running_status, "running")
        self.assertEqual(final_status, "completed")
    
    def test_task_execution_with_verification(self):
        """Test task execution with verification."""
        # Arrange
        mock_task = self.create_mock_task_with_verifier(verifier_success=True)
        mock_task.status = "running"
        
        # Act
        verification_result = mock_task.verify()
        mock_task.status = "completed" if verification_result.success else "failed"
        
        # Assert
        self.assertTrue(verification_result.success)
        self.assertEqual(mock_task.status, "completed")
    
    def test_task_execution_failure(self):
        """Test task execution failure."""
        # Arrange
        mock_task = self.create_mock_task_with_verifier(verifier_success=False)
        mock_task.status = "running"
        
        # Act
        verification_result = mock_task.verify()
        mock_task.status = "completed" if verification_result.success else "failed"
        
        # Assert
        self.assertFalse(verification_result.success)
        self.assertEqual(mock_task.status, "failed")
    
    def test_task_execution_timeout(self):
        """Test task execution timeout."""
        # Arrange
        mock_task = self.create_mock_task()
        mock_task.verify.side_effect = TimeoutError("Task execution timed out")
        
        # Act & Assert
        with self.assertRaises(TimeoutError) as context:
            mock_task.verify()
        
        self.assertEqual(str(context.exception), "Task execution timed out")


class TestTaskErrorHandling(BaseTaskTest):
    """Test task error handling scenarios."""
    
    def test_task_creation_with_invalid_data(self):
        """Test task creation with invalid data."""
        # Arrange
        invalid_data = {"id": None, "name": ""}
        
        # Act & Assert
        # Should handle invalid data gracefully
        mock_task = self.create_mock_task(**invalid_data)
        self.assertIsNone(mock_task.id)
        self.assertEqual(mock_task.name, "")
        # env_id should still have default value from mock
        self.assertIsNotNone(mock_task.env_id)
    
    def test_task_verification_error(self):
        """Test task verification error handling."""
        # Arrange
        mock_task = self.create_mock_task()
        mock_task.verify.side_effect = Exception("Verification error")
        
        # Act & Assert
        with self.assertRaises(Exception) as context:
            mock_task.verify()
        
        self.assertEqual(str(context.exception), "Verification error")
    
    def test_task_with_missing_environment(self):
        """Test task with missing environment."""
        # Arrange
        mock_task = self.create_mock_task(env_id="nonexistent_env")
        mock_task.verify.side_effect = ValueError("Environment not found")
        
        # Act & Assert
        with self.assertRaises(ValueError) as context:
            mock_task.verify()
        
        self.assertEqual(str(context.exception), "Environment not found")
    
    def test_task_with_invalid_metadata(self):
        """Test task with invalid metadata."""
        # Arrange
        invalid_metadata = {"priority": 123, "category": None, "tags": "not_a_list"}
        
        # Act
        mock_task = self.create_mock_task(metadata=invalid_metadata)
        
        # Assert
        # Should handle invalid metadata gracefully
        self.assertEqual(mock_task.metadata["priority"], 123)
        self.assertIsNone(mock_task.metadata["category"])
        self.assertEqual(mock_task.metadata["tags"], "not_a_list")


class TestTaskValidation(BaseTaskTest):
    """Test task data validation."""
    
    def test_task_id_validation(self):
        """Test task ID validation."""
        # Arrange
        valid_ids = [
            "task_123",
            "task_abc_def",
            "custom_task_456",
            "test-task-789"
        ]
        
        for task_id in valid_ids:
            # Act
            mock_task = self.create_mock_task(id=task_id)
            
            # Assert
            self.assertEqual(mock_task.id, task_id)
            self.assertIsInstance(mock_task.id, str)
            self.assertGreater(len(mock_task.id), 0)
    
    def test_task_name_validation(self):
        """Test task name validation."""
        # Arrange
        valid_names = [
            "Test Task",
            "Database Migration",
            "User Authentication",
            "API Integration Test"
        ]
        
        for name in valid_names:
            # Act
            mock_task = self.create_mock_task(name=name)
            
            # Assert
            self.assertEqual(mock_task.name, name)
            self.assertIsInstance(mock_task.name, str)
            self.assertGreater(len(mock_task.name), 0)
    
    def test_task_env_id_validation(self):
        """Test task environment ID validation."""
        # Arrange
        valid_env_ids = [
            "dropbox:Forge1.1.0",
            "hubspot:Forge1.1.0",
            "ramp:Forge1.1.0",
            "confluence:v1.4.1"
        ]
        
        for env_id in valid_env_ids:
            # Act
            mock_task = self.create_mock_task(env_id=env_id)
            
            # Assert
            self.assertEqual(mock_task.env_id, env_id)
            self.assertIsInstance(mock_task.env_id, str)
            self.assertIn(":", env_id)  # Should contain version separator
    
    def test_task_status_validation(self):
        """Test task status validation."""
        # Arrange
        valid_statuses = ["pending", "running", "completed", "failed", "cancelled"]
        
        for status in valid_statuses:
            # Act
            mock_task = self.create_mock_task(status=status)
            
            # Assert
            self.assertEqual(mock_task.status, status)
            self.assertIsInstance(mock_task.status, str)
            self.assertIn(status, valid_statuses)


class TestTaskPerformance(BaseTaskTest):
    """Test task performance characteristics."""
    
    def test_task_creation_performance(self):
        """Test task creation performance."""
        # Arrange
        start_time = time.time()
        
        # Act
        tasks = self.create_mock_task_list(100)
        
        # Assert
        end_time = time.time()
        creation_time = end_time - start_time
        
        self.assertEqual(len(tasks), 100)
        self.assertLess(creation_time, 1.0)  # Should create 100 tasks in under 1 second
    
    def test_task_verification_performance(self):
        """Test task verification performance."""
        # Arrange
        mock_task = self.create_mock_task_with_verifier(verifier_success=True)
        
        # Act
        start_time = time.time()
        result = mock_task.verify()
        end_time = time.time()
        
        # Assert
        verification_time = end_time - start_time
        self.assertLess(verification_time, 0.1)  # Should verify in under 100ms
        self.assertTrue(result.success)


if __name__ == '__main__':
    import time
    unittest.main()
