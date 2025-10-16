"""
Test to verify expect_only works correctly with row additions and field-level specs.
"""

import sqlite3
import tempfile
import os
import pytest
from fleet.verifiers.db import DatabaseSnapshot, IgnoreConfig


def test_field_level_specs_for_added_row():
    """Test that field-level specs work for row additions"""

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

        # Field-level specs should work for added rows
        before.diff(after).expect_only(
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
    """Test that wrong values are detected"""

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
            before.diff(after).expect_only(
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
    """Test complex scenario with multiple tables and mixed field/row specs"""

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
        before.diff(after).expect_only(
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
    """Test that numeric type conversions work correctly in field specs"""

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
        before.diff(after).expect_only(
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
    """Test that field-level specs work for row deletions"""

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
        before.diff(after).expect_only(
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
    """Test field specs with mixed data types and null values"""

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
        before.diff(after).expect_only(
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
    """Test that missing field specs are detected"""

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
            before.diff(after).expect_only(
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
    """Test that ignore_config works correctly with field-level specs"""

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
        before.diff(after, ignore_config).expect_only(
            [
                {"table": "users", "pk": 2, "field": "id", "after": 2},
                {"table": "users", "pk": 2, "field": "name", "after": "Bob"},
                {"table": "users", "pk": 2, "field": "status", "after": "inactive"},
            ]
        )

    finally:
        os.unlink(before_db)
        os.unlink(after_db)
