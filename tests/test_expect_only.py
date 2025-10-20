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


# ============================================================================
# Tests demonstrating OLD implementation's security issues
# These tests show cases that PASS with the old whole-row approach but
# represent security vulnerabilities that SHOULD have been caught.
# ============================================================================


def test_security_whole_row_spec_allows_malicious_values():
    """
    SECURITY ISSUE: Whole-row specs allow ANY field values, even malicious ones.

    This test demonstrates the danger of using field=None (whole-row spec).
    With the old implementation, this was the ONLY way to allow additions,
    but it's too permissive and allows unauthorized data through.

    This test PASSES (showing backward compatibility) but highlights why you
    should migrate to field-level specs for better security.
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
        # Malicious: user added with admin role!
        conn.execute("INSERT INTO users VALUES (2, 'Hacker', 'admin', 1)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # This PASSES but is insecure - we're allowing a user with admin role!
        # The old implementation would only support this approach
        before.diff(after).expect_only(
            [{"table": "users", "pk": 2, "field": None, "after": "__added__"}]
        )

        # What we SHOULD do (secure): specify exact values
        # This would catch if role was 'admin' instead of 'user'

    finally:
        os.unlink(before_db)
        os.unlink(after_db)


def test_security_field_level_specs_catch_malicious_role():
    """
    SECURITY: Field-level specs properly catch unauthorized values.

    This demonstrates the NEW, secure way to validate additions.
    If someone tries to add a user with 'admin' role when we expected 'user',
    it will be caught.
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
        # Attempted malicious addition with admin role
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'admin', 1)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # This correctly FAILS because role is 'admin' not 'user'
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only(
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


def test_security_sensitive_financial_data():
    """
    SECURITY: Whole-row spec could allow price manipulation in e-commerce.

    Demonstrates a real-world security scenario where whole-row specs are dangerous.
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
        # Malicious: order with 100% discount!
        conn.execute("INSERT INTO orders VALUES (2, 200, 1000.00, 1000.00)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # OLD WAY (insecure): This PASSES even with suspicious 100% discount
        before.diff(after).expect_only(
            [{"table": "orders", "pk": 2, "field": None, "after": "__added__"}]
        )

        # NEW WAY (secure): Would catch the excessive discount
        # If we specified expected values, this would fail:
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only(
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


def test_security_privilege_escalation_in_permissions():
    """
    SECURITY: Demonstrates privilege escalation vulnerability with whole-row specs.

    In a permissions system, whole-row specs could allow unauthorized permission grants.
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
        # Malicious: grant full permissions including delete!
        conn.execute("INSERT INTO permissions VALUES (2, 200, 'admin_panel', 1, 1, 1)")
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # INSECURE: Whole-row spec allows the dangerous permission grant
        before.diff(after).expect_only(
            [{"table": "permissions", "pk": 2, "field": None, "after": "__added__"}]
        )

        # SECURE: Field-level specs would catch unauthorized delete permission
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only(
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


def test_security_data_injection_in_json_fields():
    """
    SECURITY: Whole-row specs could allow malicious data in JSON/text fields.
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
        # Malicious: config with debug enabled and backdoor URL
        conn.execute(
            'INSERT INTO configs VALUES (2, \'user_config\', \'{"debug": true, "backdoor": "https://evil.com"}\')'
        )
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # INSECURE: Passes even with malicious settings
        before.diff(after).expect_only(
            [{"table": "configs", "pk": 2, "field": None, "after": "__added__"}]
        )

        # SECURE: Would catch the malicious settings
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only(
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
# Tests showing field-level specs being IGNORED (not validated)
# These demonstrate cases where you specify field values but they're not checked
# ============================================================================


def test_bug_field_specs_ignored_with_whole_row_spec():
    """
    This test SHOULD FAIL (on buggy code) because we specify wrong field values
    that should be caught but aren't.
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

        # This SHOULD fail because we're specifying wrong values
        # We say price=50.0 (actual: 999.99) and stock=500 (actual: 1)
        # With the buggy implementation, this wrongly passes
        # With the fix, this should raise AssertionError
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only(
                [
                    {"table": "products", "pk": 2, "field": None, "after": "__added__"},
                    # These specify WRONG values - should be caught!
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


def test_bug_wrong_values_pass_with_whole_row_spec():
    """
    BUG: You can specify any values in field specs alongside a whole-row spec,
    even completely wrong ones, and validation passes.

    This test SHOULD FAIL to catch the dangerous security issue where role=admin
    and balance=1000000 are allowed even though we specified role=user and balance=0.
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

        # Should fail because field values don't match!
        # We say role=user (actual: admin) and balance=0.0 (actual: 1000000.0)
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only(
                [
                    {"table": "accounts", "pk": 2, "field": None, "after": "__added__"},
                    # These specifications are COMPLETELY WRONG - should be caught:
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


def test_bug_conflicting_specs_pass_silently():
    """
    BUG: You can have conflicting specs (field-level AND whole-row) and
    the old implementation silently ignores the conflict, using only whole-row.

    This test SHOULD FAIL because we specify is_public=0 but it's actually 1.
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
        # Add a setting that should be private but isn't
        conn.execute(
            "INSERT INTO settings VALUES (1, 'api_key', 'secret123', 1)"
        )  # is_public=1 (BAD!)
        conn.commit()
        conn.close()

        before = DatabaseSnapshot(before_db)
        after = DatabaseSnapshot(after_db)

        # Should fail - we say is_public=0 but it's actually 1 (security issue!)
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only(
                [
                    {"table": "settings", "pk": 1, "field": None, "after": "__added__"},
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


def test_bug_field_specs_dont_work_for_deletions():
    """
    BUG: Field-level specs with 'before' values don't work for validating deletions.
    Only whole-row deletion specs (field=None) are checked.

    This test SHOULD FAIL because we're deleting an admin session when we said
    we should only delete non-admin sessions (admin_session=0).
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

        # Should fail - we say admin_session=0 but it's actually 1!
        # We're deleting an admin session when we shouldn't be
        with pytest.raises(AssertionError, match="Unexpected database changes"):
            before.diff(after).expect_only(
                [
                    {
                        "table": "sessions",
                        "pk": 2,
                        "field": None,
                        "after": "__removed__",
                    },
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
