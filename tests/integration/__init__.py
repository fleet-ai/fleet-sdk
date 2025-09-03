"""
Fleet SDK Integration Tests

This package contains comprehensive integration tests for the Fleet Python SDK.
Tests are designed to work with real API calls to verify SDK functionality.

Test Structure:
- test_sdk_import.py: SDK import and basic functionality
- test_fleet_core.py: Core functionality including .make() 
- test_resources.py: Database, browser, and resource tests
- test_verifiers.py: Verifier functionality tests
- base_test.py: DRY base classes for common functionality

Usage:
    pytest integration/
    pytest integration/test_fleet_core.py
    pytest -m "not slow"
"""

__version__ = "1.0.0"
