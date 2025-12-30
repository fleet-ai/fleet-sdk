"""
Test to verify expect_exactly works correctly.

expect_exactly: Stricter than expect_exactly - requires ALL specs to be matched
and ALL changes to have a matching spec.
"""

import sqlite3
import tempfile
import os
import pytest
from fleet.verifiers.db import DatabaseSnapshot, IgnoreConfig


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
