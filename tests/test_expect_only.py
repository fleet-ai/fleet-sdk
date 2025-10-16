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
