"""
Tests for expect_exactly method.

expect_exactly is stricter than expect_only_v2:
- ALL changes in diff must match a spec (no unexpected changes)
- ALL specs must have a matching change in diff (no missing expected changes)

This file contains:
1. Real database tests - end-to-end tests with actual SQLite databases
2. Mock-based tests - isolated tests for error message formatting
"""

import sqlite3
import tempfile
import os
import pytest
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock

from fleet.verifiers.db import DatabaseSnapshot, IgnoreConfig
from fleet.resources.sqlite import SyncSnapshotDiff, SyncDatabaseSnapshot


# ============================================================================
# Mock class for testing error messaging without real databases
# ============================================================================


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


# ============================================================================
# Tests for expect_exactly (stricter than expect_only_v2)
# ============================================================================


def test_field_level_specs_for_added_row():
    """Test that bulk field specs work for row additions in expect_exactly"""

    # Create two temporary databases
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        # Setup before database
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.commit()
        conn.close()

        # Setup after database - add a new row
        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive')")
        conn.commit()
        conn.close()

        # Create snapshots
        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Bulk field specs should work for added rows in v2
        before.diff(after).expect_exactly(
            [
                {
                    "table": "users",
                    "pk": 2,
                    "type": "insert",
                    "fields": [("id", 2), ("name", "Bob"), ("status", "inactive")],
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_field_level_specs_with_wrong_values():
    """Test that wrong values are detected in expect_exactly"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Should fail because status value is wrong
        with pytest.raises(AssertionError, match="VERIFICATION FAILED"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("name", "Bob"),
                            ("status", "WRONG_VALUE"),
                        ],
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_modification_with_bulk_fields_spec():
    """Test that bulk field specs work for row modifications in expect_exactly"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, role TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active', 'user')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, role TEXT)"
        )
        # Both name and status changed
        conn.execute("INSERT INTO users VALUES (1, 'Alice Updated', 'inactive', 'user')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Bulk field specs for modifications - specify all changed fields
        # no_other_changes=True ensures no other fields changed
        before.diff(after).expect_exactly(
            [
                {
                    "table": "users",
                    "pk": 1,
                    "type": "modify",
                    "resulting_fields": [("name", "Alice Updated"), ("status", "inactive")],
                    "no_other_changes": True,
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_modification_with_bulk_fields_spec_wrong_value():
    """Test that wrong values in modification bulk field specs are detected"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice Updated', 'inactive')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Should fail because status value is wrong
        with pytest.raises(AssertionError, match="VERIFICATION FAILED"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 1,
                        "type": "modify",
                        "resulting_fields": [
                            ("name", "Alice Updated"),
                            ("status", "WRONG_VALUE"),  # Wrong!
                        ],
                        "no_other_changes": True,
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_modification_with_bulk_fields_spec_missing_field():
    """Test that missing fields in modification bulk field specs are detected when no_other_changes=True"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        # Both name and status changed
        conn.execute("INSERT INTO users VALUES (1, 'Alice Updated', 'inactive')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Should fail because status change is not in resulting_fields and no_other_changes=True
        with pytest.raises(AssertionError) as exc_info:
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 1,
                        "type": "modify",
                        "resulting_fields": [
                            ("name", "Alice Updated"),
                            # status is missing - should fail with no_other_changes=True
                        ],
                        "no_other_changes": True,
                    },
                ]
            )

        assert "status" in str(exc_info.value)
        assert "not specified in resulting_fields" in str(exc_info.value)

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_modification_no_other_changes_false_allows_extra_changes():
    """Test that no_other_changes=False allows other fields to change without checking them"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active', '2024-01-01')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        # All three fields changed: name, status, updated_at
        conn.execute("INSERT INTO users VALUES (1, 'Alice Updated', 'inactive', '2024-01-15')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # With no_other_changes=False, we only need to specify the fields we care about
        # status and updated_at changed but we don't check them
        before.diff(after).expect_exactly(
            [
                {
                    "table": "users",
                    "pk": 1,
                    "type": "modify",
                    "resulting_fields": [
                        ("name", "Alice Updated"),
                        # status and updated_at not specified - that's OK with no_other_changes=False
                    ],
                    "no_other_changes": False,  # Allows other changes
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_modification_no_other_changes_true_with_ellipsis():
    """
    Test that no_other_changes=True and specifying fields with ... means only the specified
    fields are checked, and all other fields must remain unchanged (even if ... is used as the value).
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        # Initial table and row
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active', '2024-01-01')")
        conn.commit()
        conn.close()

        # After: only 'name' changes (others should remain exactly the same)
        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO users VALUES (1, 'Alice Updated', 'active', '2024-01-01')"
        )
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Specify to check only name with ..., others must remain the same (enforced by no_other_changes=True)
        before.diff(after).expect_exactly(
            [
                {
                    "table": "users",
                    "pk": 1,
                    "type": "modify",
                    "resulting_fields": [
                        ("name", ...),  # Only check that field changed, but not checking its value
                    ],
                    "no_other_changes": True,
                },
            ]
        )

        # Now, test that a change to a non-listed field triggers an error
        # We'll modify status, which is not covered by 'resulting_fields'
        conn = sqlite3.connect(after_db)
        conn.execute(
            "DELETE FROM users WHERE id=1"
        )
        conn.execute(
            "INSERT INTO users VALUES (1, 'Alice Updated', 'inactive', '2024-01-01')"
        )
        conn.commit()
        conn.close()

        with pytest.raises(AssertionError):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 1,
                        "type": "modify",
                        "resulting_fields": [
                            ("name", ...),  # Only allow name to change, not status
                        ],
                        "no_other_changes": True,
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_modification_no_other_changes_false_still_validates_specified():
    """Test that no_other_changes=False still validates the fields that ARE specified"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice Updated', 'inactive')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Should fail because name value is wrong, even with no_other_changes=False
        with pytest.raises(AssertionError, match="VERIFICATION FAILED"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 1,
                        "type": "modify",
                        "resulting_fields": [
                            ("name", "WRONG VALUE"),  # This is wrong
                        ],
                        "no_other_changes": False,  # Allows status to change unvalidated
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_modification_missing_no_other_changes_raises_error():
    """Test that missing no_other_changes field raises a ValueError"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice Updated', 'inactive')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Should fail because no_other_changes is missing
        with pytest.raises(ValueError, match="missing required 'no_other_changes'"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 1,
                        "type": "modify",
                        "resulting_fields": [
                            ("name", "Alice Updated"),
                            ("status", "inactive"),
                        ],
                        # no_other_changes is MISSING - should raise ValueError
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_modification_with_bulk_fields_spec_ellipsis():
    """Test that Ellipsis works in modification bulk field specs to skip value check"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active', '2024-01-01')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        # All three fields changed
        conn.execute("INSERT INTO users VALUES (1, 'Alice Updated', 'inactive', '2024-01-15')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Using Ellipsis to skip value check for updated_at
        before.diff(after).expect_exactly(
            [
                {
                    "table": "users",
                    "pk": 1,
                    "type": "modify",
                    "resulting_fields": [
                        ("name", "Alice Updated"),
                        ("status", "inactive"),
                        ("updated_at", ...),  # Don't check value
                    ],
                    "no_other_changes": True,
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


@pytest.mark.skip(reason="Uses legacy spec format not supported by expect_exactly")
def test_multiple_table_changes_with_mixed_specs():
    """Test complex scenario with multiple tables and mixed bulk field/whole-row specs in expect_exactly"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        # Setup before database with multiple tables
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, role TEXT)"
        )
        conn.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'alice@test.com', 'admin')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'bob@test.com', 'user')")
        conn.execute("INSERT INTO orders VALUES (1, 1, 100.0, 'pending')")
        conn.commit()
        conn.close()

        # Setup after database with complex changes
        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, role TEXT)"
        )
        conn.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'alice@test.com', 'admin')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'bob@test.com', 'user')")
        conn.execute(
            "INSERT INTO users VALUES (3, 'Charlie', 'charlie@test.com', 'user')"
        )
        conn.execute("INSERT INTO orders VALUES (1, 1, 100.0, 'completed')")
        conn.execute("INSERT INTO orders VALUES (2, 2, 50.0, 'pending')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Mixed specs: bulk fields for new user, bulk fields for modification, and whole-row for new order
        before.diff(after).expect_exactly(
            [
                # Bulk field specs for new user
                {
                    "table": "users",
                    "pk": 3,
                    "type": "insert",
                    "fields": [
                        ("id", 3),
                        ("name", "Charlie"),
                        ("email", "charlie@test.com"),
                        ("role", "user"),
                    ],
                },
                # Bulk field specs for order status modification (using new format)
                {
                    "table": "orders",
                    "pk": 1,
                    "type": "modify",
                    "resulting_fields": [("status", "completed")],
                    "no_other_changes": True,
                },
                # Whole-row spec for new order (legacy)
                {"table": "orders", "pk": 2, "fields": None, "after": "__added__"},
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


# test_partial_field_specs_with_unexpected_changes removed - uses legacy single-field spec format


def test_numeric_type_conversion_in_specs():
    """Test that numeric type conversions work correctly in bulk field specs with expect_exactly"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE metrics (id INTEGER PRIMARY KEY, value REAL, count INTEGER)"
        )
        conn.execute("INSERT INTO metrics VALUES (1, 3.14, 42)")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE metrics (id INTEGER PRIMARY KEY, value REAL, count INTEGER)"
        )
        conn.execute("INSERT INTO metrics VALUES (1, 3.14, 42)")
        conn.execute("INSERT INTO metrics VALUES (2, 2.71, 17)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Test string vs integer comparison for primary key
        before.diff(after).expect_exactly(
            [
                {
                    "table": "metrics",
                    "pk": "2",
                    "type": "insert",
                    "fields": [("id", 2), ("value", 2.71), ("count", 17)],
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


@pytest.mark.skip(reason="Uses legacy spec format not supported by expect_exactly")
def test_deletion_with_field_level_specs():
    """Test that bulk field specs work for row deletions in expect_exactly"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE inventory (id INTEGER PRIMARY KEY, item TEXT, quantity INTEGER, location TEXT)"
        )
        conn.execute("INSERT INTO inventory VALUES (1, 'Widget A', 10, 'Warehouse 1')")
        conn.execute("INSERT INTO inventory VALUES (2, 'Widget B', 5, 'Warehouse 2')")
        conn.execute("INSERT INTO inventory VALUES (3, 'Widget C', 15, 'Warehouse 1')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE inventory (id INTEGER PRIMARY KEY, item TEXT, quantity INTEGER, location TEXT)"
        )
        conn.execute("INSERT INTO inventory VALUES (1, 'Widget A', 10, 'Warehouse 1')")
        conn.execute("INSERT INTO inventory VALUES (3, 'Widget C', 15, 'Warehouse 1')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Bulk field specs for deleted row (with "type": "delete")
        before.diff(after).expect_exactly(
            [
                {
                    "table": "inventory",
                    "pk": 2,
                    "type": "delete",
                    "fields": [
                        ("id", 2),
                        ("item", "Widget B"),
                        ("quantity", 5),
                        ("location", "Warehouse 2"),
                    ],
                },
                # also do a whole-row check (legacy)
                {
                    "table": "inventory",
                    "pk": 2,
                    "fields": None,
                    "after": "__removed__",
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_mixed_data_types_and_null_values():
    """Test bulk field specs with mixed data types and null values in expect_exactly"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE mixed_data (id INTEGER PRIMARY KEY, text_val TEXT, num_val REAL, bool_val INTEGER, null_val TEXT)"
        )
        conn.execute("INSERT INTO mixed_data VALUES (1, 'test', 42.5, 1, NULL)")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE mixed_data (id INTEGER PRIMARY KEY, text_val TEXT, num_val REAL, bool_val INTEGER, null_val TEXT)"
        )
        conn.execute("INSERT INTO mixed_data VALUES (1, 'test', 42.5, 1, NULL)")
        conn.execute("INSERT INTO mixed_data VALUES (2, NULL, 0.0, 0, 'not_null')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Test various data types and null handling
        # ("text_val", None) checks that the value is SQL NULL
        # ("field", ...) means don't check the value
        before.diff(after).expect_exactly(
            [
                {
                    "table": "mixed_data",
                    "pk": 2,
                    "type": "insert",
                    "fields": [
                        ("id", 2),
                        ("text_val", None),  # Check that value IS NULL
                        ("num_val", 0.0),
                        ("bool_val", 0),
                        ("null_val", "not_null"),
                    ],
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


@pytest.mark.skip(reason="Uses legacy spec format not supported by expect_exactly")
def test_whole_row_spec_backward_compat():
    """Test that whole-row specs still work (backward compatibility)"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Whole-row spec should still work
        before.diff(after).expect_exactly(
            [{"table": "users", "pk": 2, "fields": None, "after": "__added__"}]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_missing_field_specs():
    """Test that missing fields in bulk field specs are detected in expect_exactly"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Should fail because status field is missing from the fields spec
        with pytest.raises(AssertionError, match="VERIFICATION FAILED"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("name", "Bob"),
                            # Missing status field - should fail
                        ],
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


# test_modified_row_with_unauthorized_field_change removed - uses legacy single-field spec format


def test_fields_spec_basic():
    """Test that bulk fields spec works correctly for added rows in expect_exactly"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active', '2024-01-01')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active', '2024-01-01')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive', '2024-01-02')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Test: All fields specified with exact values - should pass
        before.diff(after).expect_exactly(
            [
                {
                    "table": "users",
                    "pk": 2,
                    "type": "insert",
                    "fields": [
                        ("id", 2),
                        ("name", "Bob"),
                        ("status", "inactive"),
                        ("updated_at", "2024-01-02"),
                    ],
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_fields_spec_with_ellipsis_means_dont_check():
    """Test that Ellipsis (...) in a 2-tuple means 'don't check this field's value'"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive', '2024-01-02')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Test: Using Ellipsis means don't check the value - should pass
        # even though updated_at is '2024-01-02'
        before.diff(after).expect_exactly(
            [
                {
                    "table": "users",
                    "pk": 2,
                    "type": "insert",
                    "fields": [
                        ("id", 2),
                        ("name", "Bob"),
                        ("status", "inactive"),
                        ("updated_at", ...),  # Don't check this value
                    ],
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_fields_spec_with_none_checks_for_null():
    """Test that None in a 2-tuple means 'check that field is SQL NULL'"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, deleted_at TEXT)"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, deleted_at TEXT)"
        )
        # deleted_at is NULL
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'active', NULL)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Test: Using None means check that value is SQL NULL - should pass
        before.diff(after).expect_exactly(
            [
                {
                    "table": "users",
                    "pk": 2,
                    "type": "insert",
                    "fields": [
                        ("id", 2),
                        ("name", "Bob"),
                        ("status", "active"),
                        ("deleted_at", None),  # Check that this IS NULL
                    ],
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_fields_spec_with_none_fails_when_not_null():
    """Test that None check fails when field is not actually NULL"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, deleted_at TEXT)"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, deleted_at TEXT)"
        )
        # deleted_at is NOT NULL - has a value
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'active', '2024-01-15')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Test: Using None to check for NULL, but field is NOT NULL - should fail
        with pytest.raises(AssertionError) as exc_info:
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("name", "Bob"),
                            ("status", "active"),
                            ("deleted_at", None),  # Expect NULL, but actual is '2024-01-15'
                        ],
                    },
                ]
            )

        assert "deleted_at" in str(exc_info.value)
        assert "None" in str(exc_info.value)  # Expected NULL shown in table

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_fields_spec_1_tuple_raises_error():
    """Test that a 1-tuple raises an error (use Ellipsis instead)"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive', '2024-01-02')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Test: 1-tuple is no longer supported - should raise ValueError
        with pytest.raises(ValueError, match="Invalid field spec"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("name", "Bob"),
                            ("status",),  # 1-tuple: NOT SUPPORTED - use ("status", ...) instead
                            ("updated_at",),
                        ],
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_fields_spec_missing_field_fails():
    """Test that missing a field in the fields spec causes validation to fail"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive', '2024-01-02')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Test: Missing 'status' field should cause validation to fail
        with pytest.raises(AssertionError) as exc_info:
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("name", "Bob"),
                            # status is MISSING - should fail
                            ("updated_at", ...),  # Don't check this value
                        ],
                    },
                ]
            )

        assert "status" in str(exc_info.value)
        assert "not specified in expected fields" in str(exc_info.value)

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_fields_spec_wrong_value_fails():
    """Test that wrong field value in fields spec causes validation to fail"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive', '2024-01-02')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Test: Wrong value for 'status' should fail
        with pytest.raises(AssertionError) as exc_info:
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("name", "Bob"),
                            ("status", "active"),  # Wrong value - row has 'inactive'
                            ("updated_at", ...),  # Don't check this value
                        ],
                    },
                ]
            )

        assert "status" in str(exc_info.value)
        assert "'active'" in str(exc_info.value)  # Expected value shown in table

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_fields_spec_with_ignore_config():
    """Test that ignore_config works correctly with bulk fields spec"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive', '2024-01-02')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Ignore the updated_at field globally
        ignore_config = IgnoreConfig(table_fields={"users": {"updated_at"}})

        # Test: With ignore_config, we don't need to specify updated_at
        before.diff(after, ignore_config).expect_exactly(
            [
                {
                    "table": "users",
                    "pk": 2,
                    "type": "insert",
                    "fields": [
                        ("id", 2),
                        ("name", "Bob"),
                        ("status", "inactive"),
                        # updated_at is ignored, so we don't need to specify it
                    ],
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


# ============================================================================
# Tests demonstrating expect_only vs expect_exactly behavior
# These tests show cases where expect_only (whole-row only) is more permissive
# than expect_exactly (field-level specs).
# ============================================================================


@pytest.mark.skip(reason="Uses legacy spec format not supported by expect_exactly")
def test_security_whole_row_spec_allows_any_values():
    """
    expect_only with whole-row specs allows ANY field values.

    This demonstrates that expect_only with field=None (whole-row spec)
    is permissive - it only checks that a row was added, not what values it has.
    Use expect_exactly with field-level specs for stricter validation.
    """

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, role TEXT, active INTEGER)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'user', 1)")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, role TEXT, active INTEGER)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'user', 1)")
        # User added with admin role
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'admin', 1)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # expect_only with whole-row spec passes - doesn't check field values
        before.diff(after).expect_exactly(
            [{"table": "users", "pk": 2, "fields": None, "after": "__added__"}]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_security_field_level_specs_catch_wrong_role():
    """
    expect_exactly with bulk field specs catches unauthorized values.

    If someone tries to add a user with 'admin' role when we expected 'user',
    expect_exactly will catch it.
    """

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, role TEXT, active INTEGER)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'user', 1)")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, role TEXT, active INTEGER)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'user', 1)")
        # User added with admin role
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'admin', 1)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # expect_exactly correctly FAILS because role is 'admin' not 'user'
        with pytest.raises(AssertionError, match="VERIFICATION FAILED"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("name", "Bob"),
                            ("role", "user"),  # Expected 'user', but actual is 'admin'
                            ("active", 1),
                        ],
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


@pytest.mark.skip(reason="Uses legacy spec format not supported by expect_exactly")
def test_financial_data_validation():
    """
    Demonstrates difference between expect_only and expect_exactly for financial data.
    """

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, discount REAL)"
        )
        conn.execute("INSERT INTO orders VALUES (1, 100, 50.00, 0.0)")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, discount REAL)"
        )
        conn.execute("INSERT INTO orders VALUES (1, 100, 50.00, 0.0)")
        # Order with 100% discount
        conn.execute("INSERT INTO orders VALUES (2, 200, 1000.00, 1000.00)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # expect_only with whole-row spec passes - doesn't check discount value
        before.diff(after).expect_exactly(
            [{"table": "orders", "pk": 2, "fields": None, "after": "__added__"}]
        )

        # expect_exactly with bulk field specs catches unexpected discount
        with pytest.raises(AssertionError, match="VERIFICATION FAILED"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "orders",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("user_id", 200),
                            ("amount", 1000.00),
                            ("discount", 0.0),  # Expected no discount, but actual is 1000.00
                        ],
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


@pytest.mark.skip(reason="Uses legacy spec format not supported by expect_exactly")
def test_permissions_validation():
    """
    Demonstrates difference between expect_only and expect_exactly for permissions.
    """

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE permissions (id INTEGER PRIMARY KEY, user_id INTEGER, resource TEXT, can_read INTEGER, can_write INTEGER, can_delete INTEGER)"
        )
        conn.execute("INSERT INTO permissions VALUES (1, 100, 'documents', 1, 0, 0)")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE permissions (id INTEGER PRIMARY KEY, user_id INTEGER, resource TEXT, can_read INTEGER, can_write INTEGER, can_delete INTEGER)"
        )
        conn.execute("INSERT INTO permissions VALUES (1, 100, 'documents', 1, 0, 0)")
        # Grant full permissions including delete
        conn.execute("INSERT INTO permissions VALUES (2, 200, 'admin_panel', 1, 1, 1)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # expect_only with whole-row spec passes - doesn't check permission values
        before.diff(after).expect_exactly(
            [{"table": "permissions", "pk": 2, "fields": None, "after": "__added__"}]
        )

        # expect_exactly with bulk field specs catches unexpected delete permission
        with pytest.raises(AssertionError, match="VERIFICATION FAILED"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "permissions",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("user_id", 200),
                            ("resource", "admin_panel"),
                            ("can_read", 1),
                            ("can_write", 1),
                            ("can_delete", 0),  # Expected NO delete, but actual is 1
                        ],
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


@pytest.mark.skip(reason="Uses legacy spec format not supported by expect_exactly")
def test_json_field_validation():
    """
    Demonstrates difference between expect_only and expect_exactly for JSON/text fields.
    """

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE configs (id INTEGER PRIMARY KEY, name TEXT, settings TEXT)"
        )
        conn.execute(
            "INSERT INTO configs VALUES (1, 'app_config', '{\"debug\": false}')"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE configs (id INTEGER PRIMARY KEY, name TEXT, settings TEXT)"
        )
        conn.execute(
            "INSERT INTO configs VALUES (1, 'app_config', '{\"debug\": false}')"
        )
        # Config with different settings
        conn.execute(
            'INSERT INTO configs VALUES (2, \'user_config\', \'{"debug": true, "extra": "value"}\')'
        )
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # expect_only with whole-row spec passes - doesn't check settings value
        before.diff(after).expect_exactly(
            [{"table": "configs", "pk": 2, "fields": None, "after": "__added__"}]
        )

        # expect_exactly with bulk field specs catches unexpected settings
        with pytest.raises(AssertionError, match="VERIFICATION FAILED"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "configs",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("name", "user_config"),
                            ("settings", '{"debug": false}'),  # Wrong value
                        ],
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


# ============================================================================
# Tests showing expect_only vs expect_exactly behavior with conflicting specs
# ============================================================================


@pytest.mark.skip(reason="Uses legacy spec format not supported by expect_exactly")
def test_expect_only_ignores_field_specs_with_whole_row():
    """
    expect_only with whole-row spec ignores any additional field specs.
    expect_exactly with bulk field specs validates field values.
    """

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL, stock INTEGER)"
        )
        conn.execute("INSERT INTO products VALUES (1, 'Widget', 10.0, 100)")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL, stock INTEGER)"
        )
        conn.execute("INSERT INTO products VALUES (1, 'Widget', 10.0, 100)")
        # Add product with price=999.99 and stock=1
        conn.execute("INSERT INTO products VALUES (2, 'Gadget', 999.99, 1)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # expect_only with whole-row spec passes - ignores field specs
        before.diff(after).expect_exactly(
            [{"table": "products", "pk": 2, "fields": None, "after": "__added__"}]
        )

        # expect_exactly with wrong field values fails
        with pytest.raises(AssertionError, match="VERIFICATION FAILED"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "products",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("name", "Gadget"),
                            ("price", 50.0),  # WRONG! Actually 999.99
                            ("stock", 500),  # WRONG! Actually 1
                        ],
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


@pytest.mark.skip(reason="Uses legacy spec format not supported by expect_exactly")
def test_expect_exactly_validates_field_values():
    """
    expect_exactly validates field values for added rows.
    """

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, username TEXT, role TEXT, balance REAL)"
        )
        conn.execute("INSERT INTO accounts VALUES (1, 'alice', 'user', 100.0)")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, username TEXT, role TEXT, balance REAL)"
        )
        conn.execute("INSERT INTO accounts VALUES (1, 'alice', 'user', 100.0)")
        # Actual: role=admin, balance=1000000.0
        conn.execute("INSERT INTO accounts VALUES (2, 'bob', 'admin', 1000000.0)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # expect_only with whole-row spec passes
        before.diff(after).expect_exactly(
            [{"table": "accounts", "pk": 2, "fields": None, "after": "__added__"}]
        )

        # expect_exactly with wrong field values fails
        with pytest.raises(AssertionError, match="VERIFICATION FAILED"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "accounts",
                        "pk": 2,
                        "type": "insert",
                        "fields": [
                            ("id", 2),
                            ("username", "bob"),
                            ("role", "user"),  # Actually "admin"!
                            ("balance", 0.0),  # Actually 1000000.0!
                        ],
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


@pytest.mark.skip(reason="Uses legacy spec format not supported by expect_exactly")
def test_expect_exactly_validates_is_public():
    """
    expect_exactly validates field values including boolean-like fields.
    """

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE settings (id INTEGER PRIMARY KEY, key TEXT, value TEXT, is_public INTEGER)"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE settings (id INTEGER PRIMARY KEY, key TEXT, value TEXT, is_public INTEGER)"
        )
        # Add a setting with is_public=1
        conn.execute(
            "INSERT INTO settings VALUES (1, 'api_key', 'secret123', 1)"
        )
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # expect_only with whole-row spec passes
        before.diff(after).expect_exactly(
            [{"table": "settings", "pk": 1, "fields": None, "after": "__added__"}]
        )

        # expect_exactly with wrong is_public value fails
        with pytest.raises(AssertionError, match="VERIFICATION FAILED"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "settings",
                        "pk": 1,
                        "type": "insert",
                        "fields": [
                            ("id", 1),
                            ("key", "api_key"),
                            ("value", "secret123"),
                            ("is_public", 0),  # Says private, but actually public!
                        ],
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


@pytest.mark.skip(reason="Uses legacy spec format not supported by expect_exactly")
def test_deletion_with_bulk_fields_spec():
    """
    expect_exactly validates field values for deleted rows using bulk field specs with 'type': 'delete',
    and without fields.
    """

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY, user_id INTEGER, active INTEGER, admin_session INTEGER)"
        )
        conn.execute("INSERT INTO sessions VALUES (1, 100, 1, 0)")
        conn.execute("INSERT INTO sessions VALUES (2, 101, 1, 1)")  # Admin session!
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY, user_id INTEGER, active INTEGER, admin_session INTEGER)"
        )
        conn.execute("INSERT INTO sessions VALUES (1, 100, 1, 0)")
        # Session 2 (admin session) is deleted
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # expect_only with whole-row spec passes
        before.diff(after).expect_exactly(
            [{"table": "sessions", "pk": 2, "fields": None, "after": "__removed__"}]
        )

        before.diff(after).expect_exactly(
                [
                    {
                        "table": "sessions",
                        "pk": 2,
                        "type": "delete",
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


# ============================================================================
# Tests for targeted query optimization edge cases
# These tests verify the _expect_only_targeted_v2 optimization works correctly
# ============================================================================


def test_targeted_empty_allowed_changes_no_changes():
    """Test that empty allowed_changes with no actual changes passes (uses _expect_no_changes)."""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive')")
        conn.commit()
        conn.close()

        # Same data in after database
        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Empty allowed_changes should pass when there are no changes
        before.diff(after).expect_exactly([])

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_targeted_empty_allowed_changes_with_changes_fails():
    """Test that empty allowed_changes with actual changes fails."""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'active')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'inactive')")  # New row!
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Empty allowed_changes should fail when there are changes
        # The error message depends on the optimization path taken
        with pytest.raises(AssertionError):
            before.diff(after).expect_exactly([])

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_targeted_unmentioned_table_row_added_fails():
    """Test that row added in an unmentioned table is detected by targeted optimization."""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"
        )
        conn.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice')")
        conn.execute("INSERT INTO orders VALUES (1, 1)")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"
        )
        conn.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob')")  # Allowed change
        conn.execute("INSERT INTO orders VALUES (1, 1)")
        conn.execute("INSERT INTO orders VALUES (2, 2)")  # Sneaky unmentioned change!
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Only mention users table - orders change should be detected
        with pytest.raises(AssertionError, match="orders"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 2,
                        "type": "insert",
                        "fields": [("id", 2), ("name", "Bob")],
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_targeted_unmentioned_table_row_deleted_fails():
    """Test that row deleted in an unmentioned table is detected."""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"
        )
        conn.execute(
            "CREATE TABLE logs (id INTEGER PRIMARY KEY, message TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice')")
        conn.execute("INSERT INTO logs VALUES (1, 'Log entry 1')")
        conn.execute("INSERT INTO logs VALUES (2, 'Log entry 2')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"
        )
        conn.execute(
            "CREATE TABLE logs (id INTEGER PRIMARY KEY, message TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice Updated')")  # Allowed change
        conn.execute("INSERT INTO logs VALUES (1, 'Log entry 1')")
        # logs id=2 deleted - not mentioned!
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Only mention users table - logs deletion should be detected
        with pytest.raises(AssertionError, match="logs"):
            before.diff(after).expect_exactly(
                [
                    {
                        "table": "users",
                        "pk": 1,
                        "type": "modify",
                        "resulting_fields": [("name", "Alice Updated")],
                        "no_other_changes": True,
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_targeted_multiple_changes_same_table():
    """Test targeted optimization with multiple changes to the same table."""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, quantity INTEGER)"
        )
        conn.execute("INSERT INTO items VALUES (1, 'Widget', 10)")
        conn.execute("INSERT INTO items VALUES (2, 'Gadget', 20)")
        conn.execute("INSERT INTO items VALUES (3, 'Gizmo', 30)")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, quantity INTEGER)"
        )
        conn.execute("INSERT INTO items VALUES (1, 'Widget Updated', 15)")  # Modified
        conn.execute("INSERT INTO items VALUES (2, 'Gadget', 20)")  # Unchanged
        # Item 3 deleted
        conn.execute("INSERT INTO items VALUES (4, 'New Item', 40)")  # Added
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # All changes properly specified
        before.diff(after).expect_exactly(
            [
                {
                    "table": "items",
                    "pk": 1,
                    "type": "modify",
                    "resulting_fields": [("name", "Widget Updated"), ("quantity", 15)],
                    "no_other_changes": True,
                },
                {
                    "table": "items",
                    "pk": 3,
                    "type": "delete",
                },
                {
                    "table": "items",
                    "pk": 4,
                    "type": "insert",
                    "fields": [("id", 4), ("name", "New Item"), ("quantity", 40)],
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


# Legacy spec tests removed - expect_exactly requires explicit type field


def test_targeted_with_ignore_config():
    """Test that ignore_config works correctly with targeted optimization."""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE audit (id INTEGER PRIMARY KEY, action TEXT, timestamp TEXT)"
        )
        conn.execute(
            "CREATE TABLE data (id INTEGER PRIMARY KEY, value TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO audit VALUES (1, 'init', '2024-01-01')")
        conn.execute("INSERT INTO data VALUES (1, 'original', '2024-01-01')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE audit (id INTEGER PRIMARY KEY, action TEXT, timestamp TEXT)"
        )
        conn.execute(
            "CREATE TABLE data (id INTEGER PRIMARY KEY, value TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO audit VALUES (1, 'init', '2024-01-01')")
        conn.execute("INSERT INTO audit VALUES (2, 'update', '2024-01-02')")  # Ignored table
        conn.execute("INSERT INTO data VALUES (1, 'updated', '2024-01-02')")  # Changed
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Ignore the audit table entirely, and updated_at field in data
        ignore_config = IgnoreConfig(
            tables={"audit"},
            table_fields={"data": {"updated_at"}},
        )

        # Only need to specify the value change, audit table is ignored
        before.diff(after, ignore_config).expect_exactly(
            [
                {
                    "table": "data",
                    "pk": 1,
                    "type": "modify",
                    "resulting_fields": [("value", "updated")],
                    "no_other_changes": True,
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_targeted_string_vs_int_pk_coercion():
    """Test that PK comparison works with string vs int coercion."""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"
        )
        conn.execute("INSERT INTO items VALUES (1, 'Item 1')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"
        )
        conn.execute("INSERT INTO items VALUES (1, 'Item 1')")
        conn.execute("INSERT INTO items VALUES (2, 'Item 2')")
        conn.execute("INSERT INTO items VALUES (3, 'Item 3')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Use string PKs - should still work due to coercion
        before.diff(after).expect_exactly(
            [
                {
                    "table": "items",
                    "pk": "2",  # String PK
                    "type": "insert",
                    "fields": [("id", 2), ("name", "Item 2")],
                },
                {
                    "table": "items",
                    "pk": 3,  # Integer PK
                    "type": "insert",
                    "fields": [("id", 3), ("name", "Item 3")],
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_targeted_modify_without_resulting_fields():
    """Test that type: 'modify' without resulting_fields allows any modification."""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, field_a TEXT, field_b TEXT, field_c TEXT)"
        )
        conn.execute("INSERT INTO records VALUES (1, 'a1', 'b1', 'c1')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, field_a TEXT, field_b TEXT, field_c TEXT)"
        )
        conn.execute("INSERT INTO records VALUES (1, 'a2', 'b2', 'c2')")  # All fields changed
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # type: "modify" without resulting_fields allows any modification
        before.diff(after).expect_exactly(
            [
                {
                    "table": "records",
                    "pk": 1,
                    "type": "modify",
                    # No resulting_fields - allows any changes
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_targeted_insert_without_fields():
    """Test that type: 'insert' without fields allows insertion with any values."""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE entities (id INTEGER PRIMARY KEY, data TEXT, secret TEXT)"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE entities (id INTEGER PRIMARY KEY, data TEXT, secret TEXT)"
        )
        conn.execute("INSERT INTO entities VALUES (1, 'any data', 'any secret')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # type: "insert" without fields allows insertion with any values
        before.diff(after).expect_exactly(
            [
                {
                    "table": "entities",
                    "pk": 1,
                    "type": "insert",
                    # No fields - allows any values
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_targeted_multiple_tables_all_specs():
    """Test targeted optimization with multiple tables and all spec types."""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("CREATE TABLE comments (id INTEGER PRIMARY KEY, body TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'Alice')")
        conn.execute("INSERT INTO posts VALUES (1, 'Post 1')")
        conn.execute("INSERT INTO posts VALUES (2, 'Post 2')")
        conn.execute("INSERT INTO comments VALUES (1, 'Comment 1')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("CREATE TABLE comments (id INTEGER PRIMARY KEY, body TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'Alice')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob')")  # Added
        conn.execute("INSERT INTO posts VALUES (1, 'Post 1 Updated')")  # Modified
        # Post 2 deleted
        conn.execute("INSERT INTO comments VALUES (1, 'Comment 1')")  # Unchanged
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Multiple tables with different change types
        before.diff(after).expect_exactly(
            [
                {
                    "table": "users",
                    "pk": 2,
                    "type": "insert",
                    "fields": [("id", 2), ("name", "Bob")],
                },
                {
                    "table": "posts",
                    "pk": 1,
                    "type": "modify",
                    "resulting_fields": [("title", "Post 1 Updated")],
                    "no_other_changes": True,
                },
                {
                    "table": "posts",
                    "pk": 2,
                    "type": "delete",
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_targeted_row_exists_both_sides_no_change():
    """Test that specifying a row that exists but didn't change works correctly."""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"
        )
        conn.execute("INSERT INTO items VALUES (1, 'Item 1')")
        conn.execute("INSERT INTO items VALUES (2, 'Item 2')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"
        )
        conn.execute("INSERT INTO items VALUES (1, 'Item 1')")  # Unchanged
        conn.execute("INSERT INTO items VALUES (2, 'Item 2 Updated')")  # Changed
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Specify the change correctly
        before.diff(after).expect_exactly(
            [
                {
                    "table": "items",
                    "pk": 2,
                    "type": "modify",
                    "resulting_fields": [("name", "Item 2 Updated")],
                    "no_other_changes": True,
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


# ============================================================================
# Mock-based tests for error messaging (from test_error_messaging_v2.py)
# These tests use MockSnapshotDiff to test validation/error formatting logic
# without needing actual database files.
# ============================================================================


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


# ============================================================================
# Mock-based tests for expect_exactly function
# ============================================================================


class TestExpectExactlyMock:
    """
    Test cases for the expect_exactly function using mock diffs.

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


# ============================================================================
# Run tests directly
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
