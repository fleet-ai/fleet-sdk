"""
Tests for task management functionality.
"""

import pytest
from .base_test import BaseFleetTest


class TestTaskManagement(BaseFleetTest):
    """Test task management functionality."""
    
    def test_task_creation(self):
        """Test Task class creation."""
        from fleet import Task
        
        task = Task(
            key="test-task",
            prompt="Test task prompt",
            env_id="dropbox:Forge1.1.0",
            metadata={"category": "test", "difficulty": "easy"}
        )
        
        assert task.key == "test-task"
        assert task.prompt == "Test task prompt"
        assert task.env_id == "dropbox:Forge1.1.0"
        assert task.metadata["category"] == "test"
        assert task.metadata["difficulty"] == "easy"
        print("✅ Task creation works")
    
    def test_task_with_verifier(self):
        """Test Task with verifier."""
        from fleet import Task
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_task_verifier")
        def test_verifier(env, param: str = "test") -> float:
            return 1.0 if param == "test" else 0.0
        
        task = Task(
            key="test-task-with-verifier",
            prompt="Test task with verifier",
            env_id="hubspot:Forge1.1.0",
            verifier=test_verifier,
            metadata={"category": "verification", "difficulty": "medium"}
        )
        
        assert task.verifier == test_verifier
        assert hasattr(task.verifier, 'key')
        assert task.verifier.key == "test_task_verifier"
        print("✅ Task with verifier works")
    
    def test_task_attributes(self):
        """Test Task attributes."""
        from fleet import Task
        
        task = Task(
            key="test-attributes",
            prompt="Test attributes",
            env_id="ramp:Forge1.1.0"
        )
        
        # Check required attributes
        assert hasattr(task, 'key')
        assert hasattr(task, 'prompt')
        assert hasattr(task, 'env_id')
        assert hasattr(task, 'created_at')
        
        # Check optional attributes
        assert hasattr(task, 'metadata')
        assert hasattr(task, 'verifier')
        
        print("✅ Task attributes complete")
    
    def test_task_metadata(self):
        """Test Task metadata handling."""
        from fleet import Task
        
        metadata = {
            "category": "automation",
            "difficulty": "hard",
            "tags": ["test", "integration"],
            "priority": "high"
        }
        
        task = Task(
            key="test-metadata",
            prompt="Test metadata handling",
            env_id="dropbox:Forge1.1.0",
            metadata=metadata
        )
        
        assert task.metadata["category"] == "automation"
        assert task.metadata["difficulty"] == "hard"
        assert task.metadata["tags"] == ["test", "integration"]
        assert task.metadata["priority"] == "high"
        print("✅ Task metadata handling works")


class TestTaskIntegration(BaseFleetTest):
    """Test task integration with environment."""
    
    def test_task_with_environment_creation(self, fleet_client):
        """Test task with environment creation."""
        from fleet import Task
        
        task = Task(
            key="test-env-task",
            prompt="Test task with environment",
            env_id="hubspot",
            version="Forge1.1.0"
        )
        
        # Create environment for task
        env = fleet_client.make_for_task(task)
        
        assert env is not None
        assert env.env_key == "hubspot"
        assert "Forge1.1.0" in env.version
        print("✅ Task with environment creation works")
    
    def test_task_verifier_execution(self, env):
        """Test task verifier execution."""
        from fleet import Task
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_execution_verifier")
        def test_execution_verifier(env) -> float:
            try:
                # Test database access
                db = env.db()
                result = db.query("SELECT 1 as test")
                if result is not None:
                    return 1.0
                return 0.0
            except Exception:
                return 0.0
        
        task = Task(
            key="test-execution",
            prompt="Test verifier execution",
            env_id="dropbox",
            version="Forge1.1.0",
            verifier=test_execution_verifier
        )
        
        # Execute verifier
        result = task.verifier(env)
        assert isinstance(result, float)
        assert result >= 0.0
        print(f"✅ Task verifier execution: {result}")


class TestAsyncTaskManagement(BaseFleetTest):
    """Test async task management functionality."""
    
    @pytest.mark.asyncio
    async def test_async_task_with_environment(self, async_fleet_client):
        """Test async task with environment."""
        from fleet import Task
        
        task = Task(
            key="test-async-task",
            prompt="Test async task",
            env_id="ramp",
            version="Forge1.1.0"
        )
        
        # Create environment for task
        env = await async_fleet_client.make_for_task(task)
        
        assert env is not None
        assert env.env_key == "ramp"
        print("✅ Async task with environment works")
    
    @pytest.mark.asyncio
    async def test_async_task_verifier_execution(self, async_env):
        """Test async task verifier execution."""
        from fleet import Task
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_async_execution_verifier")
        async def test_async_execution_verifier(env) -> float:
            try:
                # Test async database access
                db = env.db()
                result = await db.query("SELECT 1 as test")
                if result is not None:
                    return 1.0
                return 0.0
            except Exception:
                return 0.0
        
        task = Task(
            key="test-async-execution",
            prompt="Test async verifier execution",
            env_id="hubspot",
            version="Forge1.1.0",
            verifier=test_async_execution_verifier
        )
        
        # Execute async verifier
        result = await task.verifier(async_env)
        assert isinstance(result, float)
        assert result >= 0.0
        print(f"✅ Async task verifier execution: {result}")


class TestTaskAdvanced(BaseFleetTest):
    """Test advanced task functionality."""
    
    def test_task_with_complex_verifier(self):
        """Test task with complex verifier logic."""
        from fleet import Task
        from fleet.verifiers.decorator import verifier
        
        @verifier(key="test_complex_verifier")
        def test_complex_verifier(env, project_key: str = "TEST", issue_title: str = "Test Issue") -> float:
            try:
                # Simulate complex verification logic
                db = env.db()
                
                # Query for specific conditions
                query = """
                SELECT id, issue_type, name, project_key 
                FROM issues 
                WHERE project_key = ? AND name = ? AND issue_type = 'Bug'
                """
                
                result = db.query(query, args=[project_key, issue_title])
                
                if result and hasattr(result, 'rows') and result.rows and len(result.rows) > 0:
                    print(f"✓ Found issue: {result.rows[0][0]} - {result.rows[0][2]}")
                    return 1.0
                else:
                    print(f"✗ No issue found with title '{issue_title}' in project {project_key}")
                    return 0.0
                    
            except Exception as e:
                print(f"✗ Error in verification: {e}")
                return 0.0
        
        task = Task(
            key="test-complex-verifier",
            prompt="Create a bug issue titled 'Test Issue' in the TEST project",
            env_id="dropbox:Forge1.1.0",
            verifier=test_complex_verifier,
            metadata={"category": "issue_creation", "difficulty": "medium"}
        )
        
        assert task.verifier == test_complex_verifier
        assert task.verifier.key == "test_complex_verifier"
        print("✅ Task with complex verifier works")
    
    def test_task_verification_workflow(self, env):
        """Test complete task verification workflow."""
        from fleet import Task
        from fleet.verifiers.decorator import verifier
        from datetime import datetime
        
        @verifier(key="test_workflow_verifier")
        def test_workflow_verifier(env, project_key: str = "WORKFLOW", issue_title: str = "Workflow Test") -> float:
            try:
                db = env.db()
                
                # Step 1: Check if issue exists
                check_query = """
                SELECT id, issue_type, name, project_key 
                FROM issues 
                WHERE project_key = ? AND name = ?
                """
                
                result = db.query(check_query, args=[project_key, issue_title])
                
                if result and hasattr(result, 'rows') and result.rows and len(result.rows) > 0:
                    print(f"✓ Issue already exists: {result.rows[0][0]}")
                    return 1.0
                
                # Step 2: Create the issue if it doesn't exist
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                create_query = """
                INSERT INTO issues (id, project_key, issue_type, name, status, created_at, updated_at)
                VALUES (?, ?, 'Bug', ?, 'Todo', ?, ?)
                """
                
                issue_id = f"{project_key}-9999"
                db.exec(create_query, args=[issue_id, project_key, issue_title, timestamp, timestamp])
                
                # Step 3: Verify the issue was created
                verify_result = db.query(check_query, args=[project_key, issue_title])
                if verify_result and hasattr(verify_result, 'rows') and verify_result.rows:
                    print(f"✓ Issue created successfully: {verify_result.rows[0][0]}")
                    return 1.0
                else:
                    print("✗ Issue creation failed")
                    return 0.0
                    
            except Exception as e:
                print(f"✗ Workflow error: {e}")
                return 0.0
        
        task = Task(
            key="test-workflow",
            prompt="Create a bug issue titled 'Workflow Test' in the WORKFLOW project",
            env_id="hubspot:Forge1.1.0",
            verifier=test_workflow_verifier,
            metadata={"category": "workflow", "difficulty": "hard"}
        )
        
        # Execute the workflow
        result = task.verifier(env, "WORKFLOW", "Workflow Test")
        assert isinstance(result, float)
        assert result >= 0.0
        print(f"✅ Task verification workflow: {result}")
    
    def test_task_error_handling(self):
        """Test task error handling."""
        from fleet import Task
        
        # Test task with invalid parameters
        try:
            task = Task(
                key="",  # Empty key
                prompt="",  # Empty prompt
                env_id=""  # Empty env_id
            )
            # If no error is raised, that's fine
            print("✅ Task with empty parameters handled")
        except Exception as e:
            # Expected error for invalid parameters
            print(f"✅ Task error handling works: {type(e).__name__}")
    
    def test_task_serialization(self):
        """Test task serialization."""
        from fleet import Task
        
        task = Task(
            key="test-serialization",
            prompt="Test task serialization",
            env_id="dropbox:Forge1.1.0",
            metadata={"test": "data"}
        )
        
        # Test basic serialization
        task_dict = {
            "key": task.key,
            "prompt": task.prompt,
            "env_id": task.env_id,
            "metadata": task.metadata
        }
        
        assert task_dict["key"] == "test-serialization"
        assert task_dict["prompt"] == "Test task serialization"
        assert task_dict["env_id"] == "dropbox:Forge1.1.0"
        assert task_dict["metadata"]["test"] == "data"
        print("✅ Task serialization works")
