"""
Test script for expect_only_v2 error messaging.

This script creates mock diffs and allowed_changes to exercise all the error
message paths in _validate_diff_against_allowed_changes_v2.

Run with: pytest tests/test_error_messaging_v2.py -v -s
"""

import pytest
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock

# Import the actual classes from the SDK
from fleet.resources.sqlite import SyncSnapshotDiff, SyncDatabaseSnapshot
from fleet.verifiers.db import IgnoreConfig


class MockSnapshotDiff(SyncSnapshotDiff):
    """
    A mock SyncSnapshotDiff that uses pre-defined diff data instead of
    computing it from actual database snapshots.

    This allows us to test the validation and error messaging logic
    without needing actual database files.
    """

    def __init__(self, diff_data: Dict[str, Any], ignore_config: Optional[IgnoreConfig] = None):
        # Create minimal mock snapshots
        mock_before = MagicMock(spec=SyncDatabaseSnapshot)
        mock_after = MagicMock(spec=SyncDatabaseSnapshot)

        # Mock the resource for HTTP mode detection (we want local mode for tests)
        mock_resource = MagicMock()
        mock_resource.client = None  # No HTTP client = local mode
        mock_resource._mode = "local"
        mock_after.resource = mock_resource

        # Call parent init
        super().__init__(mock_before, mock_after, ignore_config)

        # Store the mock diff data
        self._mock_diff_data = diff_data

    def _collect(self) -> Dict[str, Any]:
        """Return the pre-defined mock diff data instead of computing it."""
        return self._mock_diff_data

    def _get_primary_key_columns(self, table: str) -> List[str]:
        """Return a default primary key since we don't have real tables."""
        return ["id"]


# =============================================================================
# TEST CASES
# =============================================================================

class TestErrorMessaging:
    """Test cases for error message generation."""

    def test_unexpected_insertion_no_spec(self):
        """Test error message when a row is inserted but no spec allows it."""
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    {
                        "row_id": 123,
                        "data": {
                            "id": 123,
                            "title": "Bug report",
                            "status": "open",
                            "priority": "high",
                        },
                    }
                ],
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        allowed_changes = []  # No changes allowed

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Unexpected insertion, no spec")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "INSERTION" in error_msg
        assert "issues" in error_msg
        assert "123" in error_msg
        assert "No changes were allowed" in error_msg

    def test_insertion_with_field_value_mismatch(self):
        """Test error when insertion spec has wrong field value."""
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    {
                        "row_id": 123,
                        "data": {
                            "id": 123,
                            "title": "Bug report",
                            "status": "open",  # Actual value
                            "priority": "high",
                        },
                    }
                ],
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        allowed_changes = [
            {
                "table": "issues",
                "pk": 123,
                "type": "insert",
                "fields": [
                    ("id", 123),
                    ("title", "Bug report"),
                    ("status", "closed"),  # Expected 'closed' but got 'open'
                    ("priority", "high"),
                ],
            }
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Insertion with field value mismatch")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "INSERTION" in error_msg
        assert "status" in error_msg
        assert "open" in error_msg
        assert "closed" in error_msg or "expected" in error_msg

    def test_insertion_with_missing_field_in_spec(self):
        """Test error when insertion has field not in spec."""
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    {
                        "row_id": 123,
                        "data": {
                            "id": 123,
                            "title": "Bug report",
                            "status": "open",
                            "priority": "high",  # This field is not in spec
                            "created_at": "2024-01-15",  # This field is not in spec
                        },
                    }
                ],
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        allowed_changes = [
            {
                "table": "issues",
                "pk": 123,
                "type": "insert",
                "fields": [
                    ("id", 123),
                    ("title", "Bug report"),
                    ("status", "open"),
                    # Missing: priority, created_at
                ],
            }
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Insertion with missing field in spec")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "INSERTION" in error_msg
        assert "priority" in error_msg
        assert "NOT_IN_FIELDS_SPEC" in error_msg

    def test_unexpected_modification_no_spec(self):
        """Test error when a row is modified but no spec allows it."""
        diff = {
            "users": {
                "table_name": "users",
                "primary_key": ["id"],
                "added_rows": [],
                "removed_rows": [],
                "modified_rows": [
                    {
                        "row_id": 456,
                        "changes": {
                            "last_login": {
                                "before": "2024-01-01",
                                "after": "2024-01-15",
                            }
                        },
                        "data": {
                            "id": 456,
                            "name": "Alice",
                            "last_login": "2024-01-15",
                        },
                    }
                ],
            }
        }
        allowed_changes = []

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Unexpected modification, no spec")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "MODIFICATION" in error_msg
        assert "users" in error_msg
        assert "last_login" in error_msg
        assert "2024-01-01" in error_msg
        assert "2024-01-15" in error_msg

    def test_modification_with_wrong_resulting_field_value(self):
        """Test error when modification spec has wrong resulting field value."""
        diff = {
            "users": {
                "table_name": "users",
                "primary_key": ["id"],
                "added_rows": [],
                "removed_rows": [],
                "modified_rows": [
                    {
                        "row_id": 456,
                        "changes": {
                            "status": {
                                "before": "active",
                                "after": "inactive",  # Actual
                            }
                        },
                        "data": {"id": 456, "name": "Alice", "status": "inactive"},
                    }
                ],
            }
        }
        allowed_changes = [
            {
                "table": "users",
                "pk": 456,
                "type": "modify",
                "resulting_fields": [("status", "suspended")],  # Expected 'suspended'
                "no_other_changes": True,
            }
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Modification with wrong resulting field value")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "MODIFICATION" in error_msg
        assert "status" in error_msg
        assert "suspended" in error_msg or "expected" in error_msg

    def test_modification_with_extra_changes_strict_mode(self):
        """Test error when modification has extra changes and no_other_changes=True."""
        diff = {
            "users": {
                "table_name": "users",
                "primary_key": ["id"],
                "added_rows": [],
                "removed_rows": [],
                "modified_rows": [
                    {
                        "row_id": 456,
                        "changes": {
                            "status": {"before": "active", "after": "inactive"},
                            "updated_at": {"before": "2024-01-01", "after": "2024-01-15"},  # Extra change!
                        },
                        "data": {"id": 456, "status": "inactive", "updated_at": "2024-01-15"},
                    }
                ],
            }
        }
        allowed_changes = [
            {
                "table": "users",
                "pk": 456,
                "type": "modify",
                "resulting_fields": [("status", "inactive")],  # Only status
                "no_other_changes": True,  # Strict mode - no other changes allowed
            }
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Modification with extra changes (strict mode)")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "MODIFICATION" in error_msg
        assert "updated_at" in error_msg
        assert "NOT_IN_RESULTING_FIELDS" in error_msg

    def test_unexpected_deletion_no_spec(self):
        """Test error when a row is deleted but no spec allows it."""
        diff = {
            "logs": {
                "table_name": "logs",
                "primary_key": ["id"],
                "added_rows": [],
                "removed_rows": [
                    {
                        "row_id": 789,
                        "data": {
                            "id": 789,
                            "message": "Old log entry",
                            "level": "info",
                        },
                    }
                ],
                "modified_rows": [],
            }
        }
        allowed_changes = []

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Unexpected deletion, no spec")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "DELETION" in error_msg
        assert "logs" in error_msg
        assert "789" in error_msg

    def test_multiple_unexpected_changes(self):
        """Test error message with multiple unexpected changes."""
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    {"row_id": 1, "data": {"id": 1, "title": "Issue 1"}},
                    {"row_id": 2, "data": {"id": 2, "title": "Issue 2"}},
                ],
                "removed_rows": [
                    {"row_id": 3, "data": {"id": 3, "title": "Issue 3"}},
                ],
                "modified_rows": [
                    {
                        "row_id": 4,
                        "changes": {"status": {"before": "open", "after": "closed"}},
                        "data": {"id": 4, "title": "Issue 4", "status": "closed"},
                    },
                ],
            }
        }
        allowed_changes = []

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Multiple unexpected changes")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        # Should show multiple changes
        assert "1." in error_msg
        assert "2." in error_msg

    def test_many_changes_truncation(self):
        """Test that error message truncates when there are many changes."""
        # Create 10 unexpected insertions
        added_rows = [
            {"row_id": i, "data": {"id": i, "title": f"Issue {i}"}}
            for i in range(10)
        ]
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": added_rows,
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        allowed_changes = []

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Many changes truncation")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        # Should show truncation message
        assert "... and" in error_msg
        assert "more unexpected changes" in error_msg

    def test_allowed_changes_display(self):
        """Test that allowed changes are displayed correctly in error."""
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    {"row_id": 999, "data": {"id": 999, "title": "Unexpected"}}
                ],
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        allowed_changes = [
            {
                "table": "issues",
                "pk": 123,
                "type": "insert",
                "fields": [("id", 123), ("title", "Expected"), ("status", "open")],
            },
            {
                "table": "users",
                "pk": 456,
                "type": "modify",
                "resulting_fields": [("status", "active")],
                "no_other_changes": True,
            },
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Allowed changes display")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "Allowed changes were:" in error_msg
        assert "issues" in error_msg
        assert "123" in error_msg

    def test_successful_validation_no_error(self):
        """Test that validation passes when changes match spec."""
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    {
                        "row_id": 123,
                        "data": {"id": 123, "title": "Bug", "status": "open"},
                    }
                ],
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        allowed_changes = [
            {
                "table": "issues",
                "pk": 123,
                "type": "insert",
                "fields": [("id", 123), ("title", "Bug"), ("status", "open")],
            }
        ]

        mock = MockSnapshotDiff(diff)
        # Should not raise
        result = mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)
        assert result is mock

        print("\n" + "=" * 80)
        print("TEST: Successful validation (no error)")
        print("=" * 80)
        print("Validation passed - no AssertionError raised")
        print("=" * 80)

    def test_ellipsis_wildcard_in_spec(self):
        """Test that ... (ellipsis) wildcard accepts any value."""
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    {
                        "row_id": 123,
                        "data": {
                            "id": 123,
                            "title": "Any title here",
                            "created_at": "2024-01-15T10:30:00Z",
                        },
                    }
                ],
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        allowed_changes = [
            {
                "table": "issues",
                "pk": 123,
                "type": "insert",
                "fields": [
                    ("id", 123),
                    ("title", ...),  # Accept any value
                    ("created_at", ...),  # Accept any value
                ],
            }
        ]

        mock = MockSnapshotDiff(diff)
        # Should not raise - ellipsis accepts any value
        result = mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)
        assert result is mock

        print("\n" + "=" * 80)
        print("TEST: Ellipsis wildcard in spec")
        print("=" * 80)
        print("Validation passed with ... wildcards")
        print("=" * 80)


class TestComprehensiveErrorScenarios:
    """
    Comprehensive test covering all error scenarios:

    | Type         | (a) Correct        | (b) Wrong Fields (multiple) | (c) Missing         | (d) Unexpected     |
    |--------------|--------------------|-----------------------------|---------------------|---------------------|
    | INSERTION    | Row 100 matches    | Row 101 has 3 wrong fields  | Row 102 not added   | Row 999 unexpected  |
    | MODIFICATION | Row 300 matches    | Row 301 has 2 wrong fields  | Row 302 not modified| -                   |
    | DELETION     | Row 200 matches    | -                           | Row 202 not deleted | Row 201 unexpected  |
    """

    def test_all_scenarios(self):
        """Test comprehensive scenarios: 3 correct + 7 errors."""
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    # (a) CORRECT INSERTION - matches spec exactly
                    {
                        "row_id": 100,
                        "data": {
                            "id": 100,
                            "title": "Correct new issue",
                            "status": "open",
                            "priority": "medium",
                        },
                    },
                    # (b) WRONG FIELDS INSERTION - multiple fields wrong
                    {
                        "row_id": 101,
                        "data": {
                            "id": 101,
                            "title": "Wrong title here",  # Spec expects 'Expected title'
                            "status": "closed",  # Spec expects 'open'
                            "priority": "low",  # Spec expects 'high'
                        },
                    },
                    # (c) MISSING INSERTION - row 102 NOT here (spec expects it)
                    # (d) UNEXPECTED INSERTION - no spec for this
                    {
                        "row_id": 999,
                        "data": {
                            "id": 999,
                            "title": "Surprise insert",
                            "status": "new",
                            "priority": "high",
                        },
                    },
                ],
                "removed_rows": [
                    # (a) CORRECT DELETION - matches spec
                    {
                        "row_id": 200,
                        "data": {
                            "id": 200,
                            "title": "Correctly deleted issue",
                            "status": "resolved",
                        },
                    },
                    # (b) UNEXPECTED DELETION - deleted but no spec
                    {
                        "row_id": 201,
                        "data": {
                            "id": 201,
                            "title": "Should not be deleted",
                            "status": "active",
                        },
                    },
                    # (c) MISSING DELETION - row 202 NOT here (spec expects delete)
                ],
                "modified_rows": [
                    # (a) CORRECT MODIFICATION - matches spec
                    {
                        "row_id": 300,
                        "changes": {
                            "status": {"before": "open", "after": "in_progress"},
                        },
                        "data": {
                            "id": 300,
                            "title": "Correctly modified issue",
                            "status": "in_progress",
                        },
                    },
                    # (b) WRONG FIELDS MODIFICATION - multiple fields wrong
                    {
                        "row_id": 301,
                        "changes": {
                            "status": {"before": "open", "after": "closed"},
                            "priority": {"before": "low", "after": "high"},
                        },
                        "data": {
                            "id": 301,
                            "title": "Wrong value modification",
                            "status": "closed",  # Spec expects 'resolved'
                            "priority": "high",  # Spec expects 'low'
                        },
                    },
                    # (c) MISSING MODIFICATION - row 302 NOT here (spec expects modify)
                ],
            }
        }

        allowed_changes = [
            # === INSERTIONS ===
            # (a) CORRECT - row 100 matches
            {
                "table": "issues",
                "pk": 100,
                "type": "insert",
                "fields": [
                    ("id", 100),
                    ("title", "Correct new issue"),
                    ("status", "open"),
                    ("priority", "medium"),
                ],
            },
            # (b) WRONG FIELDS - 3 fields mismatch
            {
                "table": "issues",
                "pk": 101,
                "type": "insert",
                "fields": [
                    ("id", 101),
                    ("title", "Expected title"),  # MISMATCH: actual is 'Wrong title here'
                    ("status", "open"),  # MISMATCH: actual is 'closed'
                    ("priority", "high"),  # MISMATCH: actual is 'low'
                ],
            },
            # (c) MISSING - expects row 102, not added
            {
                "table": "issues",
                "pk": 102,
                "type": "insert",
                "fields": [
                    ("id", 102),
                    ("title", "Expected but missing"),
                    ("status", "new"),
                    ("priority", "low"),
                ],
            },
            # (d) NO SPEC for row 999 - it's unexpected

            # === DELETIONS ===
            # (a) CORRECT - row 200 matches
            {"table": "issues", "pk": 200, "type": "delete"},
            # (b) NO SPEC for row 201 - it's unexpected
            # (c) MISSING - expects row 202 deleted
            {"table": "issues", "pk": 202, "type": "delete"},

            # === MODIFICATIONS ===
            # (a) CORRECT - row 300 matches
            {
                "table": "issues",
                "pk": 300,
                "type": "modify",
                "resulting_fields": [("status", "in_progress")],
                "no_other_changes": True,
            },
            # (b) WRONG FIELDS - 2 fields mismatch
            {
                "table": "issues",
                "pk": 301,
                "type": "modify",
                "resulting_fields": [
                    ("status", "resolved"),  # MISMATCH: actual is 'closed'
                    ("priority", "low"),  # MISMATCH: actual is 'high'
                ],
                "no_other_changes": True,
            },
            # (c) MISSING - expects row 302 modified
            {
                "table": "issues",
                "pk": 302,
                "type": "modify",
                "resulting_fields": [("status", "done")],
                "no_other_changes": True,
            },
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Comprehensive Error Scenarios (expect_only_v2)")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        # Verify CORRECT changes (100, 200, 300) are NOT errors
        unexpected_section = error_msg.split("Allowed changes were:")[0]
        assert "Row ID: 100" not in unexpected_section, "Row 100 (correct insert) should not be error"
        assert "Row ID: 200" not in unexpected_section, "Row 200 (correct delete) should not be error"
        assert "Row ID: 300" not in unexpected_section, "Row 300 (correct modify) should not be error"

        # Verify WRONG FIELD errors (101, 301) are present
        assert "101" in error_msg, "Row 101 (wrong field insert) should be error"
        assert "301" in error_msg, "Row 301 (wrong field modify) should be error"

        # Verify UNEXPECTED changes (201, 999) are present
        assert "201" in error_msg, "Row 201 (unexpected delete) should be error"
        assert "999" in error_msg, "Row 999 (unexpected insert) should be error"

    def test_with_expect_exactly(self):
        """Test the same scenarios with expect_exactly - should catch all 7 errors."""
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    {"row_id": 100, "data": {"id": 100, "title": "Correct new issue", "status": "open", "priority": "medium"}},
                    {"row_id": 101, "data": {"id": 101, "title": "Wrong title here", "status": "closed", "priority": "low"}},
                    {"row_id": 999, "data": {"id": 999, "title": "Surprise insert", "status": "new", "priority": "high"}},
                ],
                "removed_rows": [
                    {"row_id": 200, "data": {"id": 200, "title": "Correctly deleted issue", "status": "resolved"}},
                    {"row_id": 201, "data": {"id": 201, "title": "Should not be deleted", "status": "active"}},
                ],
                "modified_rows": [
                    {"row_id": 300, "changes": {"status": {"before": "open", "after": "in_progress"}},
                     "data": {"id": 300, "status": "in_progress"}},
                    {"row_id": 301, "changes": {"status": {"before": "open", "after": "closed"}, "priority": {"before": "low", "after": "high"}},
                     "data": {"id": 301, "status": "closed", "priority": "high"}},
                ],
            }
        }

        expected_changes = [
            {"table": "issues", "pk": 100, "type": "insert",
             "fields": [("id", 100), ("title", "Correct new issue"), ("status", "open"), ("priority", "medium")]},
            {"table": "issues", "pk": 101, "type": "insert",
             "fields": [("id", 101), ("title", "Expected title"), ("status", "open"), ("priority", "high")]},
            {"table": "issues", "pk": 102, "type": "insert",
             "fields": [("id", 102), ("title", "Expected but missing"), ("status", "new"), ("priority", "low")]},
            {"table": "issues", "pk": 200, "type": "delete"},
            {"table": "issues", "pk": 202, "type": "delete"},
            {"table": "issues", "pk": 300, "type": "modify",
             "resulting_fields": [("status", "in_progress")], "no_other_changes": True},
            {"table": "issues", "pk": 301, "type": "modify",
             "resulting_fields": [("status", "resolved"), ("priority", "low")], "no_other_changes": True},
            {"table": "issues", "pk": 302, "type": "modify",
             "resulting_fields": [("status", "done")], "no_other_changes": True},
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock.expect_exactly(expected_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Comprehensive Error Scenarios with expect_exactly")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        # Verify error count
        assert "7 error(s) detected" in error_msg

        # Verify all error categories are present
        assert "FIELD MISMATCHES" in error_msg
        assert "UNEXPECTED CHANGES" in error_msg
        assert "MISSING EXPECTED CHANGES" in error_msg

        # Verify field mismatches show multiple fields
        assert "title" in error_msg  # INSERT 101 has wrong title
        assert "status" in error_msg  # INSERT 101 and MODIFY 301 have wrong status
        assert "priority" in error_msg  # INSERT 101 and MODIFY 301 have wrong priority

        # Verify hints section exists
        assert "HINTS" in error_msg or "near-match" in error_msg.lower()

    def test_special_patterns(self):
        """
        Test special spec patterns:
        - Ellipsis (...): Accept any value for a field
        - None: Check for SQL NULL
        - no_other_changes=False: Lenient mode for modifications

        Scenarios:
        | Row  | Type   | Pattern Being Tested                    | Should Pass? |
        |------|--------|-----------------------------------------|--------------|
        | 400  | INSERT | Ellipsis for title field               | YES          |
        | 401  | INSERT | Ellipsis works, but other field wrong  | NO (status)  |
        | 402  | INSERT | None check - field is NULL             | YES          |
        | 403  | INSERT | None check - field is NOT NULL         | NO           |
        | 500  | MODIFY | no_other_changes=False (lenient)       | YES          |
        | 501  | MODIFY | no_other_changes=True with extra change| NO           |
        """
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    # Row 400: Ellipsis should accept any title
                    {
                        "row_id": 400,
                        "data": {
                            "id": 400,
                            "title": "Any title works here",  # Spec uses ...
                            "status": "open",
                        },
                    },
                    # Row 401: Ellipsis for title, but status is wrong
                    {
                        "row_id": 401,
                        "data": {
                            "id": 401,
                            "title": "This title is fine",  # Spec uses ...
                            "status": "closed",  # WRONG: spec expects 'open'
                        },
                    },
                    # Row 402: None check - field IS NULL (matches)
                    {
                        "row_id": 402,
                        "data": {
                            "id": 402,
                            "title": "Has null field",
                            "assignee": None,  # Spec expects None
                        },
                    },
                    # Row 403: None check - field is NOT NULL (mismatch)
                    {
                        "row_id": 403,
                        "data": {
                            "id": 403,
                            "title": "Should have null",
                            "assignee": "john",  # WRONG: spec expects None
                        },
                    },
                ],
                "removed_rows": [],
                "modified_rows": [
                    # Row 500: no_other_changes=False - extra change is OK
                    {
                        "row_id": 500,
                        "changes": {
                            "status": {"before": "open", "after": "closed"},
                            "updated_at": {"before": "2024-01-01", "after": "2024-01-15"},  # Extra change
                        },
                        "data": {"id": 500, "status": "closed", "updated_at": "2024-01-15"},
                    },
                    # Row 501: no_other_changes=True - extra change is NOT OK
                    {
                        "row_id": 501,
                        "changes": {
                            "status": {"before": "open", "after": "closed"},
                            "priority": {"before": "low", "after": "high"},  # NOT allowed
                        },
                        "data": {"id": 501, "status": "closed", "priority": "high"},
                    },
                ],
            }
        }

        expected_changes = [
            # Row 400: Ellipsis for title - should PASS
            {
                "table": "issues",
                "pk": 400,
                "type": "insert",
                "fields": [
                    ("id", 400),
                    ("title", ...),  # Accept any value
                    ("status", "open"),
                ],
            },
            # Row 401: Ellipsis for title, but wrong status - should FAIL on status
            {
                "table": "issues",
                "pk": 401,
                "type": "insert",
                "fields": [
                    ("id", 401),
                    ("title", ...),  # Accept any value
                    ("status", "open"),  # MISMATCH: actual is 'closed'
                ],
            },
            # Row 402: None check - field IS NULL - should PASS
            {
                "table": "issues",
                "pk": 402,
                "type": "insert",
                "fields": [
                    ("id", 402),
                    ("title", "Has null field"),
                    ("assignee", None),  # Expect NULL
                ],
            },
            # Row 403: None check - field is NOT NULL - should FAIL
            {
                "table": "issues",
                "pk": 403,
                "type": "insert",
                "fields": [
                    ("id", 403),
                    ("title", "Should have null"),
                    ("assignee", None),  # Expect NULL, actual is 'john'
                ],
            },
            # Row 500: no_other_changes=False (lenient) - should PASS
            {
                "table": "issues",
                "pk": 500,
                "type": "modify",
                "resulting_fields": [("status", "closed")],
                "no_other_changes": False,  # Lenient: ignore updated_at change
            },
            # Row 501: no_other_changes=True (strict) with extra change - should FAIL
            {
                "table": "issues",
                "pk": 501,
                "type": "modify",
                "resulting_fields": [("status", "closed")],
                "no_other_changes": True,  # Strict: priority change not allowed
            },
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock.expect_exactly(expected_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Special Patterns (ellipsis, None, no_other_changes)")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        # Should have 3 errors: 401 (wrong status), 403 (not NULL), 501 (extra change)
        assert "3 error(s) detected" in error_msg, f"Expected 3 errors, got: {error_msg}"

        # Rows 400, 402, 500 should pass (not in errors)
        assert "pk=400" not in error_msg, "Row 400 (ellipsis) should pass"
        assert "pk=402" not in error_msg, "Row 402 (None match) should pass"
        assert "pk=500" not in error_msg, "Row 500 (lenient modify) should pass"

        # Rows 401, 403, 501 should fail
        assert "pk=401" in error_msg, "Row 401 (ellipsis but wrong status) should fail"
        assert "pk=403" in error_msg, "Row 403 (None mismatch) should fail"
        assert "pk=501" in error_msg, "Row 501 (strict modify with extra) should fail"

        # Verify specific error reasons
        # Row 401: status mismatch (ellipsis for title should work, but status wrong)
        assert "status" in error_msg and ("closed" in error_msg or "open" in error_msg)

        # Row 403: assignee should show None vs 'john'
        assert "assignee" in error_msg

        # Row 501: priority change not in resulting_fields
        assert "priority" in error_msg


class TestMixedCorrectAndIncorrect:
    """
    Test cases with mixed correct and incorrect changes to verify that:
    1. Correct specs are matched and don't appear as errors
    2. Incorrect specs are flagged with clear error messages
    3. The error message clearly distinguishes what matched vs what didn't
    """

    def test_mixed_all_change_types(self):
        """
        Test with 1 correct and 1 incorrect of each type:
        - ADDITION: 1 correct (matches spec), 1 incorrect (wrong field value)
        - MODIFICATION: 1 correct (matches spec), 1 incorrect (extra field changed)
        - DELETION: 1 correct (matches spec), 1 incorrect (not in spec at all)
        """
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    # CORRECT ADDITION - matches spec exactly
                    {
                        "row_id": 100,
                        "data": {
                            "id": 100,
                            "title": "Correct new issue",
                            "status": "open",
                            "priority": "medium",
                        },
                    },
                    # INCORRECT ADDITION - status is wrong
                    {
                        "row_id": 101,
                        "data": {
                            "id": 101,
                            "title": "Incorrect new issue",
                            "status": "closed",  # Spec expects 'open'
                            "priority": "high",
                        },
                    },
                ],
                "removed_rows": [
                    # CORRECT DELETION - matches spec
                    {
                        "row_id": 200,
                        "data": {
                            "id": 200,
                            "title": "Old issue to delete",
                            "status": "resolved",
                        },
                    },
                    # INCORRECT DELETION - not allowed at all
                    {
                        "row_id": 201,
                        "data": {
                            "id": 201,
                            "title": "Should not be deleted",
                            "status": "active",
                        },
                    },
                ],
                "modified_rows": [
                    # CORRECT MODIFICATION - matches spec
                    {
                        "row_id": 300,
                        "changes": {
                            "status": {"before": "open", "after": "in_progress"},
                        },
                        "data": {
                            "id": 300,
                            "title": "Issue being worked on",
                            "status": "in_progress",
                        },
                    },
                    # INCORRECT MODIFICATION - has extra field change not in spec
                    {
                        "row_id": 301,
                        "changes": {
                            "status": {"before": "open", "after": "closed"},
                            "updated_at": {"before": "2024-01-01", "after": "2024-01-15"},  # Not in spec!
                        },
                        "data": {
                            "id": 301,
                            "title": "Issue with extra change",
                            "status": "closed",
                            "updated_at": "2024-01-15",
                        },
                    },
                ],
            }
        }

        allowed_changes = [
            # CORRECT ADDITION spec
            {
                "table": "issues",
                "pk": 100,
                "type": "insert",
                "fields": [
                    ("id", 100),
                    ("title", "Correct new issue"),
                    ("status", "open"),
                    ("priority", "medium"),
                ],
            },
            # INCORRECT ADDITION spec - expects status='open' but row has 'closed'
            {
                "table": "issues",
                "pk": 101,
                "type": "insert",
                "fields": [
                    ("id", 101),
                    ("title", "Incorrect new issue"),
                    ("status", "open"),  # WRONG - actual is 'closed'
                    ("priority", "high"),
                ],
            },
            # CORRECT DELETION spec
            {
                "table": "issues",
                "pk": 200,
                "type": "delete",
            },
            # No spec for row 201 deletion - it's unexpected
            # CORRECT MODIFICATION spec
            {
                "table": "issues",
                "pk": 300,
                "type": "modify",
                "resulting_fields": [("status", "in_progress")],
                "no_other_changes": True,
            },
            # INCORRECT MODIFICATION spec - doesn't include updated_at
            {
                "table": "issues",
                "pk": 301,
                "type": "modify",
                "resulting_fields": [("status", "closed")],
                "no_other_changes": True,  # Strict mode - will fail due to updated_at
            },
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Mixed correct and incorrect - all change types")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        # Verify CORRECT changes are NOT in error message (they should be matched)
        # Row 100 (correct addition) should NOT appear as an error
        # Row 200 (correct deletion) should NOT appear as an error
        # Row 300 (correct modification) should NOT appear as an error

        # Verify INCORRECT changes ARE in error message
        # Row 101 (wrong status value)
        assert "101" in error_msg, "Row 101 (incorrect addition) should be in error"
        assert "status" in error_msg, "status field mismatch should be mentioned"

        # Row 201 (unexpected deletion)
        assert "201" in error_msg, "Row 201 (unexpected deletion) should be in error"
        assert "DELETION" in error_msg, "Deletion type should be mentioned"

        # Row 301 (extra field change)
        assert "301" in error_msg, "Row 301 (incorrect modification) should be in error"
        assert "updated_at" in error_msg, "updated_at field should be mentioned"

        # Count the number of errors - should be exactly 3
        # (101 insertion mismatch, 201 unexpected deletion, 301 modification mismatch)
        lines_with_row_id = [l for l in error_msg.split('\n') if 'Row ID:' in l]
        print(f"\nRows with errors: {len(lines_with_row_id)}")
        print("Row IDs in error:", [l.strip() for l in lines_with_row_id])

    def test_mixed_with_detailed_output(self):
        """
        Same as above but with more detailed assertions about what the
        error message should contain for each incorrect change.
        """
        diff = {
            "tasks": {
                "table_name": "tasks",
                "primary_key": ["id"],
                "added_rows": [
                    # CORRECT - fully matches
                    {
                        "row_id": "task-001",
                        "data": {"id": "task-001", "name": "Setup", "done": False},
                    },
                    # INCORRECT - 'done' should be False per spec
                    {
                        "row_id": "task-002",
                        "data": {"id": "task-002", "name": "Deploy", "done": True},
                    },
                ],
                "removed_rows": [],
                "modified_rows": [
                    # CORRECT - status change matches
                    {
                        "row_id": "task-003",
                        "changes": {"done": {"before": False, "after": True}},
                        "data": {"id": "task-003", "name": "Test", "done": True},
                    },
                    # INCORRECT - 'done' value is wrong
                    {
                        "row_id": "task-004",
                        "changes": {"done": {"before": True, "after": False}},
                        "data": {"id": "task-004", "name": "Review", "done": False},
                    },
                ],
            }
        }

        allowed_changes = [
            # CORRECT insertion
            {
                "table": "tasks",
                "pk": "task-001",
                "type": "insert",
                "fields": [("id", "task-001"), ("name", "Setup"), ("done", False)],
            },
            # INCORRECT insertion - expects done=False but got True
            {
                "table": "tasks",
                "pk": "task-002",
                "type": "insert",
                "fields": [("id", "task-002"), ("name", "Deploy"), ("done", False)],
            },
            # CORRECT modification
            {
                "table": "tasks",
                "pk": "task-003",
                "type": "modify",
                "resulting_fields": [("done", True)],
                "no_other_changes": True,
            },
            # INCORRECT modification - expects done=True but got False
            {
                "table": "tasks",
                "pk": "task-004",
                "type": "modify",
                "resulting_fields": [("done", True)],
                "no_other_changes": True,
            },
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Mixed with detailed output")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        # Correct ones should NOT appear in the "unexpected changes" section
        # (They may appear in "Allowed changes were:" section which is OK)
        unexpected_section = error_msg.split("Allowed changes were:")[0]
        assert "task-001" not in unexpected_section, "task-001 (correct insert) should not be in unexpected section"
        assert "task-003" not in unexpected_section, "task-003 (correct modify) should not be in unexpected section"

        # Incorrect ones SHOULD be errors
        assert "task-002" in error_msg, "task-002 (wrong insert) should be error"
        assert "task-004" in error_msg, "task-004 (wrong modify) should be error"

        # Should mention the 'done' field issue
        assert "done" in error_msg

        print("\n--- Analysis ---")
        print(f"task-001 in error: {'task-001' in error_msg} (should be False)")
        print(f"task-002 in error: {'task-002' in error_msg} (should be True)")
        print(f"task-003 in error: {'task-003' in error_msg} (should be False)")
        print(f"task-004 in error: {'task-004' in error_msg} (should be True)")


# =============================================================================
# TEST CASES FOR expect_exactly (NEW FUNCTION - uses real implementation)
# =============================================================================


class TestExpectExactly:
    """
    Test cases for the new expect_exactly function.

    expect_exactly should catch:
    1. Unexpected changes (like expect_only_v2)
    2. Missing expected changes (NEW - not caught by expect_only_v2)
    """

    def test_all_specs_satisfied_passes(self):
        """When all specs are satisfied exactly, should pass."""
        diff = {
            "users": {
                "table_name": "users",
                "primary_key": ["id"],
                "added_rows": [
                    {"row_id": 1, "data": {"id": 1, "name": "Alice"}},
                ],
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        expected_changes = [
            {
                "table": "users",
                "pk": 1,
                "type": "insert",
                "fields": [("id", 1), ("name", "Alice")],
            }
        ]

        mock = MockSnapshotDiff(diff)
        # Should pass - spec matches exactly
        result = mock.expect_exactly(expected_changes)
        assert result is mock

        print("\n" + "=" * 80)
        print("TEST: All specs satisfied - PASSED")
        print("=" * 80)

    def test_missing_insert_fails(self):
        """When spec expects insert but row wasn't added, should fail."""
        diff = {
            "users": {
                "table_name": "users",
                "primary_key": ["id"],
                "added_rows": [],  # No rows added
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        expected_changes = [
            {
                "table": "users",
                "pk": 100,
                "type": "insert",
                "fields": [("id", 100), ("name", "Expected but missing")],
            }
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock.expect_exactly(expected_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Missing insert")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "MISSING" in error_msg
        assert "insert" in error_msg.lower()
        assert "100" in error_msg

    def test_missing_delete_fails(self):
        """When spec expects delete but row still exists, should fail."""
        diff = {
            "users": {
                "table_name": "users",
                "primary_key": ["id"],
                "added_rows": [],
                "removed_rows": [],  # No rows deleted
                "modified_rows": [],
            }
        }
        expected_changes = [
            {
                "table": "users",
                "pk": 200,
                "type": "delete",
            }
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock.expect_exactly(expected_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Missing delete")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "MISSING" in error_msg
        assert "delete" in error_msg.lower()
        assert "200" in error_msg

    def test_missing_modify_fails(self):
        """When spec expects modify but row wasn't changed, should fail."""
        diff = {
            "users": {
                "table_name": "users",
                "primary_key": ["id"],
                "added_rows": [],
                "removed_rows": [],
                "modified_rows": [],  # No rows modified
            }
        }
        expected_changes = [
            {
                "table": "users",
                "pk": 300,
                "type": "modify",
                "resulting_fields": [("status", "active")],
                "no_other_changes": True,
            }
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock.expect_exactly(expected_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Missing modify")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "MISSING" in error_msg
        assert "modify" in error_msg.lower()
        assert "300" in error_msg

    def test_unexpected_change_still_fails(self):
        """Unexpected changes should still be caught (like expect_only_v2)."""
        diff = {
            "users": {
                "table_name": "users",
                "primary_key": ["id"],
                "added_rows": [
                    {"row_id": 999, "data": {"id": 999, "name": "Unexpected"}},
                ],
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        expected_changes = []  # No changes expected

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock.expect_exactly(expected_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Unexpected change")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "UNEXPECTED" in error_msg or "Unexpected" in error_msg

    def test_wrong_field_value_fails(self):
        """When change happens but field value doesn't match spec, should fail."""
        diff = {
            "users": {
                "table_name": "users",
                "primary_key": ["id"],
                "added_rows": [
                    {"row_id": 1, "data": {"id": 1, "name": "Alice", "role": "admin"}},
                ],
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        expected_changes = [
            {
                "table": "users",
                "pk": 1,
                "type": "insert",
                "fields": [("id", 1), ("name", "Alice"), ("role", "user")],  # Expected 'user' not 'admin'
            }
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock.expect_exactly(expected_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Wrong field value")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        assert "role" in error_msg or "UNEXPECTED" in error_msg

    def test_comprehensive_all_errors(self):
        """
        Comprehensive test with all 6 error types:
        - 3 correct (should pass)
        - 3 wrong field values (should fail)
        - 3 missing changes (should fail)
        """
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [
                    # CORRECT insert
                    {"row_id": 100, "data": {"id": 100, "title": "Correct", "status": "open"}},
                    # WRONG FIELD insert - status is 'closed' not 'open'
                    {"row_id": 101, "data": {"id": 101, "title": "Wrong", "status": "closed"}},
                    # Row 102 NOT added (missing insert)
                ],
                "removed_rows": [
                    # CORRECT delete
                    {"row_id": 200, "data": {"id": 200, "title": "Deleted"}},
                    # UNEXPECTED delete - no spec for this
                    {"row_id": 201, "data": {"id": 201, "title": "Unexpected delete"}},
                    # Row 202 NOT deleted (missing delete)
                ],
                "modified_rows": [
                    # CORRECT modify
                    {"row_id": 300, "changes": {"status": {"before": "open", "after": "closed"}},
                     "data": {"id": 300, "status": "closed"}},
                    # WRONG FIELD modify - status is 'closed' not 'resolved'
                    {"row_id": 301, "changes": {"status": {"before": "open", "after": "closed"}},
                     "data": {"id": 301, "status": "closed"}},
                    # Row 302 NOT modified (missing modify)
                ],
            }
        }

        expected_changes = [
            # CORRECT insert
            {"table": "issues", "pk": 100, "type": "insert",
             "fields": [("id", 100), ("title", "Correct"), ("status", "open")]},
            # WRONG FIELD insert - expects 'open' but got 'closed'
            {"table": "issues", "pk": 101, "type": "insert",
             "fields": [("id", 101), ("title", "Wrong"), ("status", "open")]},
            # MISSING insert
            {"table": "issues", "pk": 102, "type": "insert",
             "fields": [("id", 102), ("title", "Missing"), ("status", "new")]},

            # CORRECT delete
            {"table": "issues", "pk": 200, "type": "delete"},
            # No spec for 201 - it's unexpected
            # MISSING delete
            {"table": "issues", "pk": 202, "type": "delete"},

            # CORRECT modify
            {"table": "issues", "pk": 300, "type": "modify",
             "resulting_fields": [("status", "closed")], "no_other_changes": True},
            # WRONG FIELD modify - expects 'resolved' but got 'closed'
            {"table": "issues", "pk": 301, "type": "modify",
             "resulting_fields": [("status", "resolved")], "no_other_changes": True},
            # MISSING modify
            {"table": "issues", "pk": 302, "type": "modify",
             "resulting_fields": [("status", "done")], "no_other_changes": True},
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(AssertionError) as exc_info:
            mock.expect_exactly(expected_changes)

        error_msg = str(exc_info.value)
        print("\n" + "=" * 80)
        print("TEST: Comprehensive - All Error Types")
        print("=" * 80)
        print(error_msg)
        print("=" * 80)

        # Should detect MISSING changes
        assert "MISSING" in error_msg, "Should report missing changes"
        assert "102" in error_msg, "Should mention missing insert pk=102"
        assert "202" in error_msg, "Should mention missing delete pk=202"
        assert "302" in error_msg, "Should mention missing modify pk=302"

        # Should detect UNEXPECTED changes
        assert "201" in error_msg, "Should mention unexpected delete pk=201"

        # Should detect WRONG FIELD values
        assert "101" in error_msg, "Should mention wrong field insert pk=101"
        assert "301" in error_msg, "Should mention wrong field modify pk=301"

        print("\n--- Error Categories Detected ---")
        print(f"Missing changes (102, 202, 302): {'102' in error_msg and '202' in error_msg and '302' in error_msg}")
        print(f"Unexpected change (201): {'201' in error_msg}")
        print(f"Wrong field values (101, 301): {'101' in error_msg and '301' in error_msg}")

    def test_empty_diff_empty_spec_passes(self):
        """Empty diff with empty specs should pass."""
        diff = {
            "users": {
                "table_name": "users",
                "primary_key": ["id"],
                "added_rows": [],
                "removed_rows": [],
                "modified_rows": [],
            }
        }
        expected_changes = []

        mock = MockSnapshotDiff(diff)
        result = mock.expect_exactly(expected_changes)
        assert result is mock

        print("\n" + "=" * 80)
        print("TEST: Empty diff, empty spec - PASSED")
        print("=" * 80)

    def test_no_other_changes_required(self):
        """Modify specs with resulting_fields must have no_other_changes."""
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [],
                "removed_rows": [],
                "modified_rows": [
                    {
                        "row_id": 100,
                        "changes": {"status": {"before": "open", "after": "closed"}},
                        "data": {"id": 100, "status": "closed"},
                    }
                ],
            }
        }

        # Missing no_other_changes should raise ValueError
        expected_changes = [
            {
                "table": "issues",
                "pk": 100,
                "type": "modify",
                "resulting_fields": [("status", "closed")],
                # no_other_changes is MISSING
            }
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(ValueError) as exc_info:
            mock.expect_exactly(expected_changes)

        error_msg = str(exc_info.value)
        assert "no_other_changes" in error_msg
        assert "missing required" in error_msg.lower()

        print("\n" + "=" * 80)
        print("TEST: no_other_changes required - ValueError raised correctly")
        print(f"Error: {error_msg}")
        print("=" * 80)

    def test_no_other_changes_must_be_boolean(self):
        """no_other_changes must be a boolean, not a string or other type."""
        diff = {
            "issues": {
                "table_name": "issues",
                "primary_key": ["id"],
                "added_rows": [],
                "removed_rows": [],
                "modified_rows": [
                    {
                        "row_id": 100,
                        "changes": {"status": {"before": "open", "after": "closed"}},
                        "data": {"id": 100, "status": "closed"},
                    }
                ],
            }
        }

        # no_other_changes as string should raise ValueError
        expected_changes = [
            {
                "table": "issues",
                "pk": 100,
                "type": "modify",
                "resulting_fields": [("status", "closed")],
                "no_other_changes": "True",  # Wrong type - should be bool
            }
        ]

        mock = MockSnapshotDiff(diff)
        with pytest.raises(ValueError) as exc_info:
            mock.expect_exactly(expected_changes)

        error_msg = str(exc_info.value)
        assert "boolean" in error_msg.lower()

        print("\n" + "=" * 80)
        print("TEST: no_other_changes must be boolean - ValueError raised correctly")
        print(f"Error: {error_msg}")
        print("=" * 80)


# =============================================================================
# RUN TESTS DIRECTLY
# =============================================================================

if __name__ == "__main__":
    # Run with verbose output to see all error messages
    pytest.main([__file__, "-v", "-s"])
