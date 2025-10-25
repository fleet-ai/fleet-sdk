"""Unit tests for Fleet.instance() and AsyncFleet.instance() dispatch logic."""

import pytest
import tempfile
import sqlite3
import os
from unittest.mock import Mock, AsyncMock, patch
from fleet.client import Fleet
from fleet._async.client import AsyncFleet


class TestFleetInstanceDispatch:
    """Test Fleet.instance() dispatching logic."""

    @pytest.fixture
    def fleet_client(self):
        """Create a Fleet client with mocked HTTP client."""
        with patch("fleet.client.default_httpx_client") as mock_client:
            mock_client.return_value = Mock()
            client = Fleet(api_key="test_key")
            # Mock the internal client's request method
            client.client.request = Mock()
            return client

    @pytest.fixture
    def temp_db_files(self):
        """Create temporary SQLite database files."""
        files = {}
        for name in ["current", "seed"]:
            fd, path = tempfile.mkstemp(suffix=".db")
            os.close(fd)

            # Initialize with test table
            conn = sqlite3.connect(path)
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE test_{name} (
                    id INTEGER PRIMARY KEY,
                    value TEXT
                )
            """)
            cursor.execute(f"INSERT INTO test_{name} (id, value) VALUES (1, '{name}_data')")
            conn.commit()
            conn.close()

            files[name] = path

        yield files

        # Cleanup
        for path in files.values():
            if os.path.exists(path):
                os.remove(path)

    def test_dispatch_dict_local_mode(self, fleet_client, temp_db_files):
        """Test that dict input dispatches to local mode."""
        env = fleet_client.instance(temp_db_files)

        assert env.instance_id == "local"
        assert env.env_key == "local"
        assert env.region == "local"

        # Verify we can access databases
        current_db = env.db("current")
        assert current_db is not None
        assert current_db.mode == "direct"

        seed_db = env.db("seed")
        assert seed_db is not None
        assert seed_db.mode == "direct"

        # Verify query works
        result = current_db.query("SELECT * FROM test_current")
        assert result.success is True
        assert len(result.rows) == 1

    def test_dispatch_url_localhost_mode(self, fleet_client):
        """Test that http:// URL dispatches to localhost mode."""
        env = fleet_client.instance("http://localhost:8080")

        assert env.instance_id == "http://localhost:8080"
        assert env.env_key == "localhost"
        assert env.region == "localhost"

        # Verify instance client is created with correct URL
        assert env.instance.base_url == "http://localhost:8080"

    def test_dispatch_https_url_localhost_mode(self, fleet_client):
        """Test that https:// URL dispatches to localhost mode."""
        env = fleet_client.instance("https://custom-server.local:9000/api")

        assert env.instance_id == "https://custom-server.local:9000/api"
        assert env.env_key == "localhost"

        # Verify instance client is created with correct URL
        assert env.instance.base_url == "https://custom-server.local:9000/api"

    def test_dispatch_string_remote_mode(self, fleet_client):
        """Test that regular string dispatches to remote mode."""
        # Mock the HTTP response for remote mode
        mock_response = Mock()
        mock_response.json.return_value = {
            "instance_id": "test-instance-123",
            "env_key": "test_env",
            "version": "v1.0.0",
            "status": "running",
            "subdomain": "test",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "terminated_at": None,
            "team_id": "team-123",
            "region": "us-west-1",
            "env_variables": None,
            "data_key": None,
            "data_version": None,
            "urls": {
                "root": "https://test.fleet.run/",
                "app": ["https://test.fleet.run/app"],
                "api": "https://test.fleet.run/api",
                "health": "https://test.fleet.run/health",
                "api_docs": "https://test.fleet.run/docs",
                "manager": {
                    "api": "https://test.fleet.run/manager/api",
                    "docs": "https://test.fleet.run/manager/docs",
                    "reset": "https://test.fleet.run/manager/reset",
                    "diff": "https://test.fleet.run/manager/diff",
                    "snapshot": "https://test.fleet.run/manager/snapshot",
                    "execute_verifier_function": "https://test.fleet.run/manager/execute",
                    "execute_verifier_function_with_upload": "https://test.fleet.run/manager/execute_upload",
                },
            },
            "health": True,
        }
        fleet_client.client.request.return_value = mock_response

        env = fleet_client.instance("test-instance-123")

        # Verify HTTP client was called for remote API
        fleet_client.client.request.assert_called()
        call_args = fleet_client.client.request.call_args
        assert "/v1/env/instances/test-instance-123" in call_args[0][1]

        # Verify we got a remote env back
        assert env.instance_id == "test-instance-123"
        assert env.env_key == "test_env"

    def test_local_mode_query_functionality(self, fleet_client, temp_db_files):
        """Test that local mode databases are fully functional."""
        env = fleet_client.instance(temp_db_files)

        # Test query on current db
        current = env.db("current")
        result = current.query("SELECT value FROM test_current WHERE id = 1")
        assert result.success is True
        assert result.rows[0][0] == "current_data"

        # Test query on seed db
        seed = env.db("seed")
        result = seed.query("SELECT value FROM test_seed WHERE id = 1")
        assert result.success is True
        assert result.rows[0][0] == "seed_data"

        # Test query builder
        current_data = current.table("test_current").eq("id", 1).first()
        assert current_data is not None
        assert current_data["value"] == "current_data"

    def test_local_mode_exec_functionality(self, fleet_client, temp_db_files):
        """Test that local mode supports write operations."""
        env = fleet_client.instance(temp_db_files)
        db = env.db("current")

        # Insert data
        result = db.exec("INSERT INTO test_current (id, value) VALUES (2, 'new_data')")
        assert result.success is True
        assert result.rows_affected == 1

        # Verify insert
        check = db.query("SELECT value FROM test_current WHERE id = 2")
        assert check.rows[0][0] == "new_data"

        # Update data
        result = db.exec("UPDATE test_current SET value = 'updated' WHERE id = 2")
        assert result.success is True

        # Verify update
        check = db.query("SELECT value FROM test_current WHERE id = 2")
        assert check.rows[0][0] == "updated"

    def test_local_mode_creates_new_instances(self, fleet_client, temp_db_files):
        """Test that db() creates new SQLiteResource instances each time (not cached)."""
        env = fleet_client.instance(temp_db_files)

        db1 = env.db("current")
        db2 = env.db("current")

        # Should be different objects (new wrapper each time)
        assert db1 is not db2

        # But both should work identically
        result1 = db1.query("SELECT * FROM test_current")
        result2 = db2.query("SELECT * FROM test_current")
        assert result1.rows == result2.rows

    def test_local_mode_no_state_leakage(self, fleet_client, temp_db_files):
        """Test that monkey-patching one db() instance doesn't affect another."""
        env = fleet_client.instance(temp_db_files)

        db1 = env.db("current")
        db1._custom_attribute = "test_value"

        db2 = env.db("current")
        # db2 should be a fresh instance without the custom attribute
        assert not hasattr(db2, "_custom_attribute")

    def test_memory_basic_syntax(self, fleet_client):
        """Test that :memory: syntax works."""
        env = fleet_client.instance({
            "current": ":memory:"
        })

        db = env.db("current")
        assert db.mode == "direct"

        # Create table and insert data
        result = db.exec("CREATE TABLE test (id INTEGER, value TEXT)")
        assert result.success is True

        result = db.exec("INSERT INTO test VALUES (1, 'hello')")
        assert result.success is True

        # Verify data exists
        result = db.query("SELECT * FROM test")
        assert result.success is True
        assert result.rows == [[1, 'hello']]

    def test_memory_namespace_syntax(self, fleet_client):
        """Test that :memory:namespace syntax creates isolated databases."""
        env = fleet_client.instance({
            "current": ":memory:current",
            "seed": ":memory:seed"
        })

        current = env.db("current")
        seed = env.db("seed")

        # Create table in current
        current.exec("CREATE TABLE test_current (id INTEGER, value TEXT)")
        current.exec("INSERT INTO test_current VALUES (1, 'current_data')")

        # Create table in seed
        seed.exec("CREATE TABLE test_seed (id INTEGER, value TEXT)")
        seed.exec("INSERT INTO test_seed VALUES (2, 'seed_data')")

        # Verify current has its data
        result = current.query("SELECT * FROM test_current")
        assert result.success is True
        assert result.rows == [[1, 'current_data']]

        # Verify seed has its data
        result = seed.query("SELECT * FROM test_seed")
        assert result.success is True
        assert result.rows == [[2, 'seed_data']]

        # Verify current doesn't have seed's table
        result = current.query("SELECT name FROM sqlite_master WHERE type='table' AND name='test_seed'")
        assert result.success is True
        assert result.rows is None or len(result.rows) == 0

        # Verify seed doesn't have current's table
        result = seed.query("SELECT name FROM sqlite_master WHERE type='table' AND name='test_current'")
        assert result.success is True
        assert result.rows is None or len(result.rows) == 0

    def test_memory_data_sharing(self, fleet_client):
        """Test that multiple db() calls to same namespace share data."""
        env = fleet_client.instance({
            "current": ":memory:shared"
        })

        # Create table and insert data via first connection
        db1 = env.db("current")
        db1.exec("CREATE TABLE test (id INTEGER, value TEXT)")
        db1.exec("INSERT INTO test VALUES (1, 'shared_data')")

        # Access same database via second connection
        db2 = env.db("current")
        result = db2.query("SELECT * FROM test")
        assert result.success is True
        assert result.rows == [[1, 'shared_data']]

        # Insert via second connection
        db2.exec("INSERT INTO test VALUES (2, 'more_data')")

        # Verify via first connection
        result = db1.query("SELECT * FROM test ORDER BY id")
        assert result.success is True
        assert result.rows == [[1, 'shared_data'], [2, 'more_data']]

    def test_memory_data_persists(self, fleet_client):
        """Test that memory data persists while env is alive."""
        env = fleet_client.instance({
            "current": ":memory:persistent"
        })

        # Create and populate database
        db = env.db("current")
        db.exec("CREATE TABLE test (id INTEGER, value TEXT)")
        db.exec("INSERT INTO test VALUES (1, 'persistent')")

        # Delete the db reference
        del db

        # Create new connection - data should still be there
        db_new = env.db("current")
        result = db_new.query("SELECT * FROM test")
        assert result.success is True
        assert result.rows == [[1, 'persistent']]

    def test_memory_anchor_connection_cleanup(self, fleet_client):
        """Test that closing the instance cleans up anchor connections."""
        env = fleet_client.instance({
            "current": ":memory:cleanup_test",
            "seed": ":memory:cleanup_test2"
        })

        # Verify anchor connections were created
        assert hasattr(env._instance, '_memory_anchors')
        assert 'current' in env._instance._memory_anchors
        assert 'seed' in env._instance._memory_anchors

        # Setup databases
        current = env.db("current")
        current.exec("CREATE TABLE test (id INTEGER)")

        # Close the instance
        env._instance.close()

        # Verify anchors were cleaned up
        assert len(env._instance._memory_anchors) == 0


@pytest.mark.asyncio
class TestAsyncFleetInstanceDispatch:
    """Test AsyncFleet.instance() dispatching logic."""

    @pytest.fixture
    async def async_fleet_client(self):
        """Create an AsyncFleet client with mocked HTTP client."""
        with patch("fleet._async.client.default_httpx_client") as mock_client:
            mock_client.return_value = AsyncMock()
            client = AsyncFleet(api_key="test_key")
            # Mock the internal client's request method
            client.client.request = AsyncMock()
            return client

    @pytest.fixture
    def temp_db_files(self):
        """Create temporary SQLite database files."""
        files = {}
        for name in ["current", "seed"]:
            fd, path = tempfile.mkstemp(suffix=".db")
            os.close(fd)

            # Initialize with test table
            conn = sqlite3.connect(path)
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE test_{name} (
                    id INTEGER PRIMARY KEY,
                    value TEXT
                )
            """)
            cursor.execute(f"INSERT INTO test_{name} (id, value) VALUES (1, '{name}_data')")
            conn.commit()
            conn.close()

            files[name] = path

        yield files

        # Cleanup
        for path in files.values():
            if os.path.exists(path):
                os.remove(path)

    async def test_dispatch_dict_local_mode(self, async_fleet_client, temp_db_files):
        """Test that dict input dispatches to local mode in async."""
        env = await async_fleet_client.instance(temp_db_files)

        assert env.instance_id == "local"
        assert env.env_key == "local"
        assert env.region == "local"

        # Verify we can access databases
        current_db = env.db("current")
        assert current_db is not None
        assert current_db.mode == "direct"

        # Verify async query works
        result = await current_db.query("SELECT * FROM test_current")
        assert result.success is True
        assert len(result.rows) == 1

    async def test_dispatch_url_localhost_mode(self, async_fleet_client):
        """Test that http:// URL dispatches to localhost mode in async."""
        env = await async_fleet_client.instance("http://localhost:8080")

        assert env.instance_id == "http://localhost:8080"
        assert env.env_key == "localhost"

        # Verify instance client is created with correct URL
        assert env.instance.base_url == "http://localhost:8080"

    async def test_local_mode_async_query_functionality(self, async_fleet_client, temp_db_files):
        """Test that local mode databases work with async queries."""
        env = await async_fleet_client.instance(temp_db_files)

        # Test async query
        current = env.db("current")
        result = await current.query("SELECT value FROM test_current WHERE id = 1")
        assert result.success is True
        assert result.rows[0][0] == "current_data"

        # Test async query builder
        current_data = await current.table("test_current").eq("id", 1).first()
        assert current_data is not None
        assert current_data["value"] == "current_data"

    async def test_local_mode_async_exec_functionality(self, async_fleet_client, temp_db_files):
        """Test that local mode supports async write operations."""
        env = await async_fleet_client.instance(temp_db_files)
        db = env.db("current")

        # Insert data
        result = await db.exec("INSERT INTO test_current (id, value) VALUES (2, 'async_data')")
        assert result.success is True
        assert result.rows_affected == 1

        # Verify insert
        check = await db.query("SELECT value FROM test_current WHERE id = 2")
        assert check.rows[0][0] == "async_data"

    async def test_local_mode_async_creates_new_instances(self, async_fleet_client, temp_db_files):
        """Test that db() creates new AsyncSQLiteResource instances each time (not cached)."""
        env = await async_fleet_client.instance(temp_db_files)

        db1 = env.db("current")
        db2 = env.db("current")

        # Should be different objects (new wrapper each time)
        assert db1 is not db2

        # But both should work identically
        result1 = await db1.query("SELECT * FROM test_current")
        result2 = await db2.query("SELECT * FROM test_current")
        assert result1.rows == result2.rows

    async def test_local_mode_async_no_state_leakage(self, async_fleet_client, temp_db_files):
        """Test that monkey-patching one db() instance doesn't affect another in async."""
        env = await async_fleet_client.instance(temp_db_files)

        db1 = env.db("current")
        db1._custom_attribute = "test_value"

        db2 = env.db("current")
        # db2 should be a fresh instance without the custom attribute
        assert not hasattr(db2, "_custom_attribute")


@pytest.mark.asyncio
class TestAsyncFleetInMemoryTests:
    """Test AsyncFleet in-memory functionality."""

    @pytest.fixture
    async def async_fleet_client(self):
        """Create an AsyncFleet client with mocked HTTP client."""
        with patch("fleet._async.client.default_httpx_client") as mock_client:
            mock_client.return_value = AsyncMock()
            client = AsyncFleet(api_key="test_key")
            client.client.request = AsyncMock()
            return client

    async def test_memory_basic_syntax(self, async_fleet_client):
        """Test that :memory: syntax works in async."""
        env = await async_fleet_client.instance({
            "current": ":memory:"
        })

        db = env.db("current")
        assert db.mode == "direct"

        # Create table and insert data
        result = await db.exec("CREATE TABLE test (id INTEGER, value TEXT)")
        assert result.success is True

        result = await db.exec("INSERT INTO test VALUES (1, 'hello')")
        assert result.success is True

        # Verify data exists
        result = await db.query("SELECT * FROM test")
        assert result.success is True
        assert result.rows == [[1, 'hello']]

    async def test_memory_namespace_syntax(self, async_fleet_client):
        """Test that :memory:namespace syntax creates isolated databases in async."""
        env = await async_fleet_client.instance({
            "current": ":memory:current",
            "seed": ":memory:seed"
        })

        current = env.db("current")
        seed = env.db("seed")

        # Create table in current
        await current.exec("CREATE TABLE test_current (id INTEGER, value TEXT)")
        await current.exec("INSERT INTO test_current VALUES (1, 'current_data')")

        # Create table in seed
        await seed.exec("CREATE TABLE test_seed (id INTEGER, value TEXT)")
        await seed.exec("INSERT INTO test_seed VALUES (2, 'seed_data')")

        # Verify current has its data
        result = await current.query("SELECT * FROM test_current")
        assert result.success is True
        assert result.rows == [[1, 'current_data']]

        # Verify seed has its data
        result = await seed.query("SELECT * FROM test_seed")
        assert result.success is True
        assert result.rows == [[2, 'seed_data']]

        # Verify namespaces are isolated
        result = await current.query("SELECT name FROM sqlite_master WHERE type='table' AND name='test_seed'")
        assert result.success is True
        assert result.rows is None or len(result.rows) == 0

    async def test_memory_data_sharing(self, async_fleet_client):
        """Test that multiple db() calls to same namespace share data in async."""
        env = await async_fleet_client.instance({
            "current": ":memory:shared"
        })

        # Create table and insert data via first connection
        db1 = env.db("current")
        await db1.exec("CREATE TABLE test (id INTEGER, value TEXT)")
        await db1.exec("INSERT INTO test VALUES (1, 'shared_data')")

        # Access same database via second connection
        db2 = env.db("current")
        result = await db2.query("SELECT * FROM test")
        assert result.success is True
        assert result.rows == [[1, 'shared_data']]

        # Insert via second connection
        await db2.exec("INSERT INTO test VALUES (2, 'more_data')")

        # Verify via first connection
        result = await db1.query("SELECT * FROM test ORDER BY id")
        assert result.success is True
        assert result.rows == [[1, 'shared_data'], [2, 'more_data']]

    async def test_memory_data_persists(self, async_fleet_client):
        """Test that memory data persists while env is alive in async."""
        env = await async_fleet_client.instance({
            "current": ":memory:persistent"
        })

        # Create and populate database
        db = env.db("current")
        await db.exec("CREATE TABLE test (id INTEGER, value TEXT)")
        await db.exec("INSERT INTO test VALUES (1, 'persistent')")

        # Delete the db reference
        del db

        # Create new connection - data should still be there
        db_new = env.db("current")
        result = await db_new.query("SELECT * FROM test")
        assert result.success is True
        assert result.rows == [[1, 'persistent']]

    async def test_memory_anchor_connection_cleanup(self, async_fleet_client):
        """Test that closing the instance cleans up anchor connections in async."""
        env = await async_fleet_client.instance({
            "current": ":memory:cleanup_test",
            "seed": ":memory:cleanup_test2"
        })

        # Verify anchor connections were created
        assert hasattr(env._instance, '_memory_anchors')
        assert 'current' in env._instance._memory_anchors
        assert 'seed' in env._instance._memory_anchors

        # Setup databases
        current = env.db("current")
        await current.exec("CREATE TABLE test (id INTEGER)")

        # Close the instance
        env._instance.close()

        # Verify anchors were cleaned up
        assert len(env._instance._memory_anchors) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
