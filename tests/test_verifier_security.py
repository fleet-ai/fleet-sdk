"""Security tests for verifier_from_string function.

Tests that the verifier parsing and validation properly blocks
arbitrary code execution during import.
"""

import pytest
from fleet.tasks import verifier_from_string as sync_verifier_from_string
from fleet._async.tasks import verifier_from_string as async_verifier_from_string


class TestSyncVerifierSecurity:
    """Security tests for sync version of verifier_from_string."""

    def test_blocks_module_level_subprocess_run(self):
        """Test that module-level subprocess.run() is blocked."""
        code = """
import subprocess
subprocess.run(['echo', 'malicious'])

def my_verifier(env):
    return 1.0
"""
        with pytest.raises(ValueError, match="Expression statements that are not constants"):
            sync_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_blocks_module_level_open(self):
        """Test that module-level open() is blocked."""
        code = """
open('/etc/passwd', 'r')

def my_verifier(env):
    return 1.0
"""
        with pytest.raises(ValueError, match="Expression statements that are not constants"):
            sync_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_blocks_assignment_with_subprocess_call(self):
        """Test that variable assignment with subprocess call is blocked."""
        code = """
import subprocess
result = subprocess.run(['echo', 'malicious'])

def my_verifier(env):
    return 1.0
"""
        with pytest.raises(ValueError, match="Variable assignments with function calls"):
            sync_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_blocks_assignment_with_open_call(self):
        """Test that variable assignment with open() is blocked."""
        code = """
file_handle = open('/etc/passwd', 'r')

def my_verifier(env):
    return 1.0
"""
        with pytest.raises(ValueError, match="Variable assignments with function calls"):
            sync_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_blocks_assignment_with_any_function_call(self):
        """Test that variable assignment with any function call is blocked."""
        code = """
import os
path = os.getcwd()

def my_verifier(env):
    return 1.0
"""
        with pytest.raises(ValueError, match="Variable assignments with function calls"):
            sync_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_allows_constant_assignment(self):
        """Test that constant variable assignments are allowed."""
        code = """
CONSTANT_VALUE = 42
ANOTHER_CONSTANT = "test"
PI = 3.14159

def my_verifier(env):
    return CONSTANT_VALUE
"""
        # Should not raise
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None

    def test_allows_list_dict_constant_assignment(self):
        """Test that list/dict constant assignments are allowed."""
        code = """
MY_LIST = [1, 2, 3]
MY_DICT = {"key": "value"}
MY_TUPLE = (1, 2, 3)

def my_verifier(env):
    return 1.0
"""
        # Should not raise
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None

    def test_allows_valid_imports(self):
        """Test that imports are allowed."""
        code = """
import json
import os
from typing import Dict

def my_verifier(env):
    return 1.0
"""
        # Should not raise
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None

    def test_allows_class_definitions(self):
        """Test that class definitions are allowed."""
        code = """
class MyHelper:
    def __init__(self):
        self.value = 42

    def get_value(self):
        return self.value

def my_verifier(env):
    helper = MyHelper()
    return helper.get_value()
"""
        # Should not raise
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None

    def test_allows_multiple_functions(self):
        """Test that multiple function definitions are allowed."""
        code = """
def helper_function(x):
    return x * 2

def my_verifier(env):
    return helper_function(0.5)
"""
        # Should not raise
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None

    def test_extracts_first_function_name(self):
        """Test that the first function name is correctly extracted."""
        code = """
def first_function(env):
    return 1.0

def second_function(env):
    return 0.5
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        # The first function should be used
        assert verifier.func.__name__ == "first_function"

    def test_error_message_includes_line_number(self):
        """Test that error messages include helpful line numbers."""
        code = """
import subprocess

subprocess.run(['echo', 'test'])

def my_verifier(env):
    return 1.0
"""
        with pytest.raises(ValueError, match=r"Line \d+"):
            sync_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_blocks_nested_function_call_in_list(self):
        """Test that function calls nested in list assignments are blocked."""
        code = """
import os
MY_LIST = [1, 2, os.getcwd()]

def my_verifier(env):
    return 1.0
"""
        with pytest.raises(ValueError, match="Variable assignments with function calls"):
            sync_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_blocks_nested_function_call_in_dict(self):
        """Test that function calls nested in dict assignments are blocked."""
        code = """
import os
MY_DICT = {"cwd": os.getcwd()}

def my_verifier(env):
    return 1.0
"""
        with pytest.raises(ValueError, match="Variable assignments with function calls"):
            sync_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_allows_docstrings(self):
        """Test that module-level docstrings are allowed."""
        code = '''
"""This is a module docstring."""

def my_verifier(env):
    """This is a function docstring."""
    return 1.0
'''
        # Should not raise
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None

    def test_function_with_decorator_extracts_correct_name(self):
        """Test that decorators don't affect function name extraction."""
        code = """
def some_decorator(func):
    return func

@some_decorator
def my_actual_function(env):
    return 1.0
"""
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        # Should extract 'some_decorator' (first function) or 'my_actual_function'
        # depending on order, but NOT the decorator name itself
        assert verifier.func.__name__ in ["some_decorator", "my_actual_function"]

    def test_blocks_decorator_with_function_call(self):
        """Test that decorators with function calls are blocked."""
        code = """
import subprocess

@subprocess.run(['echo', 'bad'])
def my_verifier(env):
    return 1.0
"""
        # Decorators execute during import, so calls in decorators are dangerous
        with pytest.raises(ValueError, match="Function decorators with function calls"):
            sync_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_allows_simple_decorator_reference(self):
        """Test that simple decorator references (no calls) are allowed."""
        code = """
def my_decorator(func):
    return func

@my_decorator
def my_verifier(env):
    return 1.0
"""
        # Simple decorator reference (no call) should be allowed
        verifier = sync_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None


class TestAsyncVerifierSecurity:
    """Security tests for async version of verifier_from_string."""

    def test_blocks_module_level_subprocess_run(self):
        """Test that module-level subprocess.run() is blocked."""
        code = """
import subprocess
subprocess.run(['echo', 'malicious'])

async def my_async_verifier(env):
    return 1.0
"""
        with pytest.raises(ValueError, match="Expression statements that are not constants"):
            async_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_blocks_assignment_with_function_call(self):
        """Test that variable assignment with function call is blocked."""
        code = """
import subprocess
result = subprocess.run(['echo', 'malicious'])

async def my_async_verifier(env):
    return 1.0
"""
        with pytest.raises(ValueError, match="Variable assignments with function calls"):
            async_verifier_from_string(
                verifier_func=code,
                verifier_id="test-verifier",
                verifier_key="test-key",
                sha256="test-sha",
            )

    def test_allows_constant_assignment(self):
        """Test that constant variable assignments are allowed."""
        code = """
CONSTANT_VALUE = 42

async def my_async_verifier(env):
    return CONSTANT_VALUE
"""
        # Should not raise
        verifier = async_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None

    def test_allows_async_function_definitions(self):
        """Test that async function definitions are recognized."""
        code = """
async def my_async_verifier(env):
    return 1.0
"""
        # Should not raise
        verifier = async_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        assert verifier is not None

    def test_extracts_first_async_function_name(self):
        """Test that the first async function name is correctly extracted."""
        code = """
async def first_async_function(env):
    return 1.0

async def second_async_function(env):
    return 0.5
"""
        verifier = async_verifier_from_string(
            verifier_func=code,
            verifier_id="test-verifier",
            verifier_key="test-key",
            sha256="test-sha",
        )
        # The first function should be used
        assert verifier.func.__name__ == "first_async_function"
