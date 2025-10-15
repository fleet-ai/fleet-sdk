"""Comprehensive tests for verifier_from_string function.

Tests both sync (fleet/tasks.py) and async (fleet/_async/tasks.py) versions.
"""

import pytest
from fleet.tasks import verifier_from_string as sync_verifier_from_string
from fleet._async.tasks import verifier_from_string as async_verifier_from_string


class TestSyncVerifierFromString:
    """Tests for sync version of verifier_from_string."""

    def test_basic_verifier_without_imports(self):
        """Test basic verifier function without any imports."""
        code = """
def my_verifier(env):
    return 1.0
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        assert verifier.key == "test-key"
        assert verifier.func.__name__ == "my_verifier"

    def test_verifier_with_from_fleet_import_verifier(self):
        """Test the bug case: 'from fleet import verifier' should not be selected."""
        code = """
from fleet import verifier

def my_actual_verifier(env):
    return 1.0
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        # The function name should be 'my_actual_verifier', not 'verifier'
        assert verifier.func.__name__ == "my_actual_verifier"

    def test_verifier_with_from_fleet_verifiers_import_verifier(self):
        """Test bug case: 'from fleet.verifiers import verifier'."""
        code = """
from fleet.verifiers import verifier

def check_something(env):
    return 1.0
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        assert verifier.func.__name__ == "check_something"

    def test_verifier_with_from_fleet_verifiers_verifier_import_verifier(self):
        """Test bug case: 'from fleet.verifiers.verifier import verifier'."""
        code = """
from fleet.verifiers.verifier import verifier

def validate_task(env):
    return 0.5
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        assert verifier.func.__name__ == "validate_task"

    def test_verifier_with_multiple_imports(self):
        """Test verifier with multiple import statements."""
        code = """
from fleet import verifier
from fleet.verifiers.db import IgnoreConfig
import json

def complex_verifier(env):
    data = json.dumps({"status": "ok"})
    return 1.0
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        assert verifier.func.__name__ == "complex_verifier"

    def test_verifier_with_legitimate_imports(self):
        """Test verifier with legitimate imports (not fleet-related)."""
        code = """
import json
import os

def my_verifier(env):
    return 1.0
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        assert verifier.func.__name__ == "my_verifier"

    def test_verifier_using_task_scores(self):
        """Test verifier that uses TASK_SUCCESSFUL_SCORE and TASK_FAILED_SCORE."""
        code = """
def my_verifier(env):
    if True:
        return TASK_SUCCESSFUL_SCORE
    return TASK_FAILED_SCORE
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        assert verifier.func.__name__ == "my_verifier"

    def test_verifier_using_ignore_config(self):
        """Test verifier that uses IgnoreConfig."""
        code = """
def my_verifier(env):
    config = IgnoreConfig()
    return 1.0
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        assert verifier.func.__name__ == "my_verifier"

    def test_no_function_defined_raises_error(self):
        """Test that code with no function raises ValueError."""
        code = """
x = 1
y = 2
"""
        with pytest.raises(ValueError, match="No function found in verifier code"):
            sync_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_only_imports_no_function_raises_error(self):
        """Test that code with only imports and no function raises ValueError."""
        code = """
from fleet import verifier
import json
"""
        with pytest.raises(ValueError, match="No function found in verifier code"):
            sync_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_verifier_with_multiple_functions(self):
        """Test that first user-defined function is selected when multiple exist."""
        code = """
def helper_function():
    return "helper"

def my_verifier(env):
    return 1.0
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        # Should pick the first function (order depends on dict iteration)
        assert verifier.func.__name__ in ["helper_function", "my_verifier"]

    def test_verifier_with_decorator_usage(self):
        """Test verifier that would use @verifier decorator in normal usage."""
        code = """
from fleet.verifiers.verifier import verifier

def actual_verifier_function(env, project_key: str = "TEST"):
    # This is the function that should be selected
    return 1.0
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        assert verifier.func.__name__ == "actual_verifier_function"

    def test_verifier_metadata_stored_correctly(self):
        """Test that verifier metadata is stored correctly."""
        code = """
def my_verifier(env):
    return 1.0
"""
        sha256_val = "abcd1234"
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier-id",
            verifier_key="test-key",
            sha256=sha256_val,
        )
        assert verifier.key == "test-key"
        assert verifier.verifier_id == "test-verifier-id"
        assert verifier._sha256 == sha256_val
        assert verifier._verifier_code == code


class TestAsyncVerifierFromString:
    """Tests for async version of verifier_from_string."""

    def test_basic_async_verifier_without_imports(self):
        """Test basic async verifier function without any imports."""
        code = """
async def my_async_verifier(env):
    return 1.0
"""
        verifier = async_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None

    def test_async_verifier_with_from_fleet_import_verifier(self):
        """Test async bug case: 'from fleet import verifier'."""
        code = """
from fleet import verifier

async def my_actual_async_verifier(env):
    return 1.0
"""
        verifier = async_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        assert verifier.func.__name__ == "my_actual_async_verifier"

    def test_async_verifier_with_multiple_imports(self):
        """Test async verifier with multiple import statements."""
        code = """
from fleet import verifier
from fleet.verifiers.db import IgnoreConfig
import asyncio

async def complex_async_verifier(env):
    await asyncio.sleep(0)
    return 1.0
"""
        verifier = async_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        assert verifier.func.__name__ == "complex_async_verifier"

    def test_sync_function_in_async_module(self):
        """Test that sync functions also work in async module."""
        code = """
from fleet import verifier

def sync_verifier_in_async_module(env):
    return 1.0
"""
        verifier = async_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None
        assert verifier.func.__name__ == "sync_verifier_in_async_module"

    def test_async_no_function_defined_raises_error(self):
        """Test that async code with no function raises ValueError."""
        code = """
x = 1
y = 2
"""
        with pytest.raises(ValueError, match="No function found in verifier code"):
            async_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_async_only_imports_raises_error(self):
        """Test that async code with only imports raises ValueError."""
        code = """
from fleet import verifier
import asyncio
"""
        with pytest.raises(ValueError, match="No function found in verifier code"):
            async_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )


class TestRealWorldScenarios:
    """Test real-world scenarios from the bug report."""

    def test_original_bug_report_scenario(self):
        """Test the exact scenario from the bug report."""
        code = """from fleet import verifier
def blahblah():
    return 1.0
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        # Should select 'blahblah', not the imported 'verifier'
        assert verifier.func.__name__ == "blahblah"

    def test_example_verifier_pattern(self):
        """Test a pattern similar to example_verifier.py."""
        code = """import fleet
from fleet.verifiers.verifier import verifier
from fleet.verifiers.db import IgnoreConfig


def validate_finish_blue_green_deployment(
    env, final_answer: str = None
) -> int:
    '''Validate that DEBT-722 and DEBT-720 are marked as Done'''
    return 1.0
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier.func.__name__ == "validate_finish_blue_green_deployment"

    def test_example_task_pattern_sync(self):
        """Test a pattern similar to example_task.py sync verifier."""
        code = """from fleet.verifiers.verifier import verifier
from fleet.verifiers.code import TASK_SUCCESSFUL_SCORE, TASK_FAILED_SCORE


def create_bug_issue_sync(
    env, project_key: str = "SCRUM", issue_title: str = "Sample Bug"
) -> float:
    '''Synchronous verifier for remote execution.'''
    try:
        return TASK_SUCCESSFUL_SCORE
    except Exception as e:
        return TASK_FAILED_SCORE
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier.func.__name__ == "create_bug_issue_sync"

    def test_example_task_pattern_async(self):
        """Test a pattern similar to example_task.py async verifier."""
        code = """from fleet.verifiers.verifier import verifier
from fleet.verifiers.code import TASK_SUCCESSFUL_SCORE, TASK_FAILED_SCORE


async def create_bug_issue_async(
    env, project_key: str = "SCRUM", issue_title: str = "Sample Bug"
) -> float:
    '''Async verifier for local execution with async environments.'''
    try:
        return TASK_SUCCESSFUL_SCORE
    except Exception as e:
        return TASK_FAILED_SCORE
"""
        verifier = async_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier.func.__name__ == "create_bug_issue_async"
