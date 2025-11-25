"""
Test to verify expect_only and expect_only_v2 work correctly.

expect_only: Original simple implementation - only supports whole-row specs for additions/deletions
expect_only_v2: Enhanced implementation with field-level spec support for additions/deletions
"""

import sqlite3
import tempfile
import os
import pytest
from fleet.verifiers.db import DatabaseSnapshot, IgnoreConfig


# ============================================================================
# Tests for expect_only_v2 (field-level spec support)
# ============================================================================


def test_field_level_specs_for_added_row():
    """Test that field-level specs work for row additions in expect_only_v2"""

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

        # Field-level specs should work for added rows in v2
        before.diff(after).expect_only_v2(
            [
                {"table": "users", "pk": 2, "field": "id", "after": 2},
                {"table": "users", "pk": 2, "field": "name", "after": "Bob"},
                {"table": "users", "pk": 2, "field": "status", "after": "inactive"},
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_field_level_specs_with_wrong_values():
    """Test that wrong values are detected in expect_only_v2"""

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
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only_v2(
                [
                    {"table": "users", "pk": 2, "field": "id", "after": 2},
                    {"table": "users", "pk": 2, "field": "name", "after": "Bob"},
                    {
                        "table": "users",
                        "pk": 2,
                        "field": "status",
                        "after": "WRONG_VALUE",
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_multiple_table_changes_with_mixed_specs():
    """Test complex scenario with multiple tables and mixed field/row specs in expect_only_v2"""

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

        # Mixed specs: field-level for new user, whole-row for new order
        before.diff(after).expect_only_v2(
            [
                # Field-level specs for new user
                {"table": "users", "pk": 3, "field": "id", "after": 3},
                {"table": "users", "pk": 3, "field": "name", "after": "Charlie"},
                {
                    "table": "users",
                    "pk": 3,
                    "field": "email",
                    "after": "charlie@test.com",
                },
                {"table": "users", "pk": 3, "field": "role", "after": "user"},
                # Field-level spec for order status change
                {"table": "orders", "pk": 1, "field": "status", "after": "completed"},
                # Whole-row spec for new order
                {"table": "orders", "pk": 2, "field": None, "after": "__added__"},
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_partial_field_specs_with_unexpected_changes():
    """Test that partial field specs catch unexpected changes in unspecified fields"""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        before_db = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        after_db = f.name

    try:
        conn = sqlite3.connect(before_db)
        conn.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL, category TEXT, stock INTEGER)"
        )
        conn.execute(
            "INSERT INTO products VALUES (1, 'Widget', 10.99, 'electronics', 100)"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(after_db)
        conn.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL, category TEXT, stock INTEGER)"
        )
        conn.execute(
            "INSERT INTO products VALUES (1, 'Widget', 12.99, 'electronics', 95)"
        )
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Only specify price change, but stock also changed - should fail
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only(
                [
                    {"table": "products", "pk": 1, "field": "price", "after": 12.99},
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_numeric_type_conversion_in_specs():
    """Test that numeric type conversions work correctly in field specs with expect_only_v2"""

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
        before.diff(after).expect_only_v2(
            [
                {"table": "metrics", "pk": "2", "field": "id", "after": 2},
                {"table": "metrics", "pk": "2", "field": "value", "after": 2.71},
                {"table": "metrics", "pk": "2", "field": "count", "after": 17},
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_deletion_with_field_level_specs():
    """Test that field-level specs work for row deletions in expect_only_v2"""

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

        # Field-level specs for deleted row
        before.diff(after).expect_only_v2(
            [
                {"table": "inventory", "pk": 2, "field": "id", "before": 2},
                {"table": "inventory", "pk": 2, "field": "item", "before": "Widget B"},
                {"table": "inventory", "pk": 2, "field": "quantity", "before": 5},
                {
                    "table": "inventory",
                    "pk": 2,
                    "field": "location",
                    "before": "Warehouse 2",
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_mixed_data_types_and_null_values():
    """Test field specs with mixed data types and null values in expect_only_v2"""

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
        before.diff(after).expect_only_v2(
            [
                {"table": "mixed_data", "pk": 2, "field": "id", "after": 2},
                {"table": "mixed_data", "pk": 2, "field": "text_val", "after": None},
                {"table": "mixed_data", "pk": 2, "field": "num_val", "after": 0.0},
                {"table": "mixed_data", "pk": 2, "field": "bool_val", "after": 0},
                {
                    "table": "mixed_data",
                    "pk": 2,
                    "field": "null_val",
                    "after": "not_null",
                },
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


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
        before.diff(after).expect_only(
            [{"table": "users", "pk": 2, "field": None, "after": "__added__"}]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_missing_field_specs():
    """Test that missing field specs are detected in expect_only_v2"""

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

        # Should fail because status field spec is missing
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only_v2(
                [
                    {"table": "users", "pk": 2, "field": "id", "after": 2},
                    {"table": "users", "pk": 2, "field": "name", "after": "Bob"},
                    # Missing status field spec
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_modified_row_with_unauthorized_field_change():
    """Test that unauthorized changes to existing rows are detected"""

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
        conn.execute("INSERT INTO users VALUES (1, 'Alice Updated', 'suspended')")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Should fail because status change is not allowed
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only(
                [
                    {
                        "table": "users",
                        "pk": 1,
                        "field": "name",
                        "after": "Alice Updated",
                    },
                    # Missing status field spec - status should not have changed
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_ignore_config_with_field_specs():
    """Test that ignore_config works correctly with field-level specs in expect_only_v2"""

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

        # Ignore updated_at field
        ignore_config = IgnoreConfig(table_fields={"users": {"updated_at"}})

        # Should work without specifying updated_at because it's ignored
        before.diff(after, ignore_config).expect_only_v2(
            [
                {"table": "users", "pk": 2, "field": "id", "after": 2},
                {"table": "users", "pk": 2, "field": "name", "after": "Bob"},
                {"table": "users", "pk": 2, "field": "status", "after": "inactive"},
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


# ============================================================================
# Tests demonstrating expect_only vs expect_only_v2 behavior
# These tests show cases where expect_only (whole-row only) is more permissive
# than expect_only_v2 (field-level specs).
# ============================================================================


def test_security_whole_row_spec_allows_any_values():
    """
    expect_only with whole-row specs allows ANY field values.

    This demonstrates that expect_only with field=None (whole-row spec)
    is permissive - it only checks that a row was added, not what values it has.
    Use expect_only_v2 with field-level specs for stricter validation.
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
        before.diff(after).expect_only(
            [{"table": "users", "pk": 2, "field": None, "after": "__added__"}]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_security_field_level_specs_catch_wrong_role():
    """
    expect_only_v2 with field-level specs catches unauthorized values.

    If someone tries to add a user with 'admin' role when we expected 'user',
    expect_only_v2 will catch it.
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

        # expect_only_v2 correctly FAILS because role is 'admin' not 'user'
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only_v2(
                [
                    {"table": "users", "pk": 2, "field": "id", "after": 2},
                    {"table": "users", "pk": 2, "field": "name", "after": "Bob"},
                    {
                        "table": "users",
                        "pk": 2,
                        "field": "role",
                        "after": "user",
                    },  # Expected 'user'
                    {"table": "users", "pk": 2, "field": "active", "after": 1},
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_financial_data_validation():
    """
    Demonstrates difference between expect_only and expect_only_v2 for financial data.
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
        before.diff(after).expect_only(
            [{"table": "orders", "pk": 2, "field": None, "after": "__added__"}]
        )

        # expect_only_v2 with field-level specs catches unexpected discount
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only_v2(
                [
                    {"table": "orders", "pk": 2, "field": "id", "after": 2},
                    {"table": "orders", "pk": 2, "field": "user_id", "after": 200},
                    {"table": "orders", "pk": 2, "field": "amount", "after": 1000.00},
                    {
                        "table": "orders",
                        "pk": 2,
                        "field": "discount",
                        "after": 0.0,
                    },  # Expected no discount
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_permissions_validation():
    """
    Demonstrates difference between expect_only and expect_only_v2 for permissions.
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
        before.diff(after).expect_only(
            [{"table": "permissions", "pk": 2, "field": None, "after": "__added__"}]
        )

        # expect_only_v2 with field-level specs catches unexpected delete permission
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only_v2(
                [
                    {"table": "permissions", "pk": 2, "field": "id", "after": 2},
                    {"table": "permissions", "pk": 2, "field": "user_id", "after": 200},
                    {
                        "table": "permissions",
                        "pk": 2,
                        "field": "resource",
                        "after": "admin_panel",
                    },
                    {"table": "permissions", "pk": 2, "field": "can_read", "after": 1},
                    {"table": "permissions", "pk": 2, "field": "can_write", "after": 1},
                    {
                        "table": "permissions",
                        "pk": 2,
                        "field": "can_delete",
                        "after": 0,
                    },  # Expected NO delete
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_json_field_validation():
    """
    Demonstrates difference between expect_only and expect_only_v2 for JSON/text fields.
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
        before.diff(after).expect_only(
            [{"table": "configs", "pk": 2, "field": None, "after": "__added__"}]
        )

        # expect_only_v2 with field-level specs catches unexpected settings
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only_v2(
                [
                    {"table": "configs", "pk": 2, "field": "id", "after": 2},
                    {
                        "table": "configs",
                        "pk": 2,
                        "field": "name",
                        "after": "user_config",
                    },
                    {
                        "table": "configs",
                        "pk": 2,
                        "field": "settings",
                        "after": '{"debug": false}',
                    },
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


# ============================================================================
# Tests showing expect_only vs expect_only_v2 behavior with conflicting specs
# ============================================================================


def test_expect_only_ignores_field_specs_with_whole_row():
    """
    expect_only with whole-row spec ignores any additional field specs.
    expect_only_v2 with field-level specs validates field values.
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
        before.diff(after).expect_only(
            [{"table": "products", "pk": 2, "field": None, "after": "__added__"}]
        )

        # expect_only_v2 with wrong field values fails
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only_v2(
                [
                    {
                        "table": "products",
                        "pk": 2,
                        "field": "id",
                        "after": 2,
                    },
                    {
                        "table": "products",
                        "pk": 2,
                        "field": "name",
                        "after": "Gadget",
                    },
                    {
                        "table": "products",
                        "pk": 2,
                        "field": "price",
                        "after": 50.0,
                    },  # WRONG! Actually 999.99
                    {
                        "table": "products",
                        "pk": 2,
                        "field": "stock",
                        "after": 500,
                    },  # WRONG! Actually 1
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_expect_only_v2_validates_field_values():
    """
    expect_only_v2 validates field values for added rows.
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
        before.diff(after).expect_only(
            [{"table": "accounts", "pk": 2, "field": None, "after": "__added__"}]
        )

        # expect_only_v2 with wrong field values fails
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only_v2(
                [
                    {
                        "table": "accounts",
                        "pk": 2,
                        "field": "id",
                        "after": 2,
                    },
                    {
                        "table": "accounts",
                        "pk": 2,
                        "field": "username",
                        "after": "bob",
                    },
                    {
                        "table": "accounts",
                        "pk": 2,
                        "field": "role",
                        "after": "user",
                    },  # Actually "admin"!
                    {
                        "table": "accounts",
                        "pk": 2,
                        "field": "balance",
                        "after": 0.0,
                    },  # Actually 1000000.0!
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_expect_only_v2_validates_is_public():
    """
    expect_only_v2 validates field values including boolean-like fields.
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
        before.diff(after).expect_only(
            [{"table": "settings", "pk": 1, "field": None, "after": "__added__"}]
        )

        # expect_only_v2 with wrong is_public value fails
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only_v2(
                [
                    {"table": "settings", "pk": 1, "field": "id", "after": 1},
                    {"table": "settings", "pk": 1, "field": "key", "after": "api_key"},
                    {"table": "settings", "pk": 1, "field": "value", "after": "secret123"},
                    {
                        "table": "settings",
                        "pk": 1,
                        "field": "is_public",
                        "after": 0,
                    },  # Says private, but actually public!
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_expect_only_v2_validates_deletion_field_values():
    """
    expect_only_v2 validates field values for deleted rows using 'before' key.
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
        before.diff(after).expect_only(
            [{"table": "sessions", "pk": 2, "field": None, "after": "__removed__"}]
        )

        # expect_only_v2 with wrong admin_session value fails
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only_v2(
                [
                    {"table": "sessions", "pk": 2, "field": "id", "before": 2},
                    {"table": "sessions", "pk": 2, "field": "user_id", "before": 101},
                    {"table": "sessions", "pk": 2, "field": "active", "before": 1},
                    {
                        "table": "sessions",
                        "pk": 2,
                        "field": "admin_session",
                        "before": 0,
                    },  # WRONG! Actually 1
                ]
            )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)
