"""Unit tests for SQLiteResource dual-mode functionality."""

import pytest
import tempfile
import sqlite3
import os
from fleet.resources.sqlite import SQLiteResource
from fleet.instance.models import (
    Resource as ResourceModel,
    ResourceType,
    ResourceMode,
    QueryResponse,
    DescribeResponse,
)


class TestSQLiteResourceDirectMode:
    """Test SQLiteResource in direct (local file) mode."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary SQLite database for testing."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        # Initialize with test data
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT,
                age INTEGER
            )
        """)
        cursor.execute(
            "INSERT INTO users (id, name, email, age) VALUES (?, ?, ?, ?)",
            (1, "Alice", "alice@example.com", 30),
        )
        cursor.execute(
            "INSERT INTO users (id, name, email, age) VALUES (?, ?, ?, ?)",
            (2, "Bob", "bob@example.com", 25),
        )
        conn.commit()
        conn.close()

        yield path

        # Cleanup
        if os.path.exists(path):
            os.remove(path)

    @pytest.fixture
    def resource(self, temp_db):
        """Create a SQLiteResource in direct mode."""
        resource_model = ResourceModel(
            name="test_db",
            type=ResourceType.db,
            mode=ResourceMode.rw,
        )
        return SQLiteResource(resource_model, client=None, db_path=temp_db)

    def test_mode_property(self, resource):
        """Test that mode property returns 'direct'."""
        assert resource.mode == "direct"

    def test_query_select(self, resource):
        """Test SELECT query in direct mode."""
        response = resource.query("SELECT * FROM users ORDER BY id")

        assert response.success is True
        assert response.columns == ["id", "name", "email", "age"]
        assert len(response.rows) == 2
        # Rows can be either tuples or lists depending on the implementation
        assert list(response.rows[0]) == [1, "Alice", "alice@example.com", 30]
        assert list(response.rows[1]) == [2, "Bob", "bob@example.com", 25]

    def test_query_with_params(self, resource):
        """Test query with parameters."""
        response = resource.query("SELECT * FROM users WHERE id = ?", [1])

        assert response.success is True
        assert len(response.rows) == 1
        assert response.rows[0][1] == "Alice"

    def test_exec_insert(self, resource):
        """Test INSERT operation in direct mode."""
        response = resource.exec(
            "INSERT INTO users (id, name, email, age) VALUES (?, ?, ?, ?)",
            [3, "Charlie", "charlie@example.com", 35],
        )

        assert response.success is True
        assert response.rows_affected == 1
        assert response.last_insert_id == 3

        # Verify the insert
        check = resource.query("SELECT * FROM users WHERE id = 3")
        assert len(check.rows) == 1
        assert check.rows[0][1] == "Charlie"

    def test_exec_update(self, resource):
        """Test UPDATE operation in direct mode."""
        response = resource.exec("UPDATE users SET age = ? WHERE id = ?", [31, 1])

        assert response.success is True
        assert response.rows_affected == 1

        # Verify the update
        check = resource.query("SELECT age FROM users WHERE id = 1")
        assert check.rows[0][0] == 31

    def test_exec_delete(self, resource):
        """Test DELETE operation in direct mode."""
        response = resource.exec("DELETE FROM users WHERE id = ?", [2])

        assert response.success is True
        assert response.rows_affected == 1

        # Verify the delete
        check = resource.query("SELECT * FROM users")
        assert len(check.rows) == 1

    def test_describe(self, resource):
        """Test describe() in direct mode."""
        response = resource.describe()

        assert response.success is True
        assert response.resource_name == "test_db"
        assert len(response.tables) == 1

        table = response.tables[0]
        assert table.name == "users"
        assert table.sql is not None
        assert len(table.columns) == 4

        # Check column details
        columns = {col["name"]: col for col in table.columns}
        assert "id" in columns
        assert columns["id"]["primary_key"] is True
        assert "name" in columns
        assert columns["name"]["notnull"] is True

    def test_table_query_builder(self, resource):
        """Test table() query builder in direct mode."""
        users = resource.table("users").all()

        assert len(users) == 2
        assert users[0]["name"] == "Alice"
        assert users[1]["name"] == "Bob"

    def test_query_builder_eq(self, resource):
        """Test query builder eq() filter."""
        user = resource.table("users").eq("name", "Alice").first()

        assert user is not None
        assert user["name"] == "Alice"
        assert user["email"] == "alice@example.com"

    def test_query_builder_count(self, resource):
        """Test query builder count()."""
        count = resource.table("users").count()
        assert count == 2

        count_filtered = resource.table("users").eq("age", 30).count()
        assert count_filtered == 1

    def test_query_builder_where(self, resource):
        """Test query builder where() with multiple conditions."""
        users = resource.table("users").where(age=25).all()

        assert len(users) == 1
        assert users[0]["name"] == "Bob"

    def test_query_builder_limit(self, resource):
        """Test query builder limit()."""
        users = resource.table("users").limit(1).all()

        assert len(users) == 1

    def test_query_error_handling(self, resource):
        """Test error handling for invalid queries."""
        response = resource.query("SELECT * FROM nonexistent_table")

        assert response.success is False
        assert response.error is not None
        assert "nonexistent_table" in response.error.lower() or "no such table" in response.error.lower()


class TestSQLiteResourceHTTPMode:
    """Test SQLiteResource in HTTP (remote) mode."""

    @pytest.fixture
    def mock_client(self, mocker):
        """Create a mock HTTP client."""
        return mocker.Mock()

    @pytest.fixture
    def resource(self, mock_client):
        """Create a SQLiteResource in HTTP mode."""
        resource_model = ResourceModel(
            name="remote_db",
            type=ResourceType.db,
            mode=ResourceMode.rw,
        )
        return SQLiteResource(resource_model, client=mock_client, db_path=None)

    def test_mode_property(self, resource):
        """Test that mode property returns 'http'."""
        assert resource.mode == "http"

    def test_query_http(self, resource, mock_client, mocker):
        """Test that query() calls HTTP client."""
        # Mock the HTTP response
        mock_response = mocker.Mock()
        mock_response.json.return_value = {
            "success": True,
            "columns": ["id", "name"],
            "rows": [[1, "Alice"]],
            "message": "Query successful",
        }
        mock_client.request.return_value = mock_response

        response = resource.query("SELECT * FROM users")

        # Verify HTTP client was called
        mock_client.request.assert_called_once()
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "POST"
        assert "/query" in call_args[0][1]

        # Verify response
        assert response.success is True
        assert response.columns == ["id", "name"]

    def test_describe_http(self, resource, mock_client, mocker):
        """Test that describe() calls HTTP client."""
        # Mock the HTTP response
        mock_response = mocker.Mock()
        mock_response.json.return_value = {
            "success": True,
            "resource_name": "remote_db",
            "tables": [],
            "message": "Schema retrieved",
        }
        mock_client.request.return_value = mock_response

        response = resource.describe()

        # Verify HTTP client was called
        mock_client.request.assert_called_once()
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "GET"
        assert "/describe" in call_args[0][1]

        # Verify response
        assert response.success is True
        assert response.resource_name == "remote_db"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
