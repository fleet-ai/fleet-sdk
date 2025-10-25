"""Verification tests for SQLite shared memory behavior.

These tests verify how SQLite's shared memory databases work to ensure
our implementation assumptions are correct.
"""

import sqlite3
import pytest


def test_plain_memory_no_sharing():
    """Verify that plain :memory: databases don't share data."""
    conn1 = sqlite3.connect(':memory:')
    conn1.execute("CREATE TABLE test (id INT)")
    conn1.execute("INSERT INTO test VALUES (1)")

    # Second connection to :memory: creates a SEPARATE database
    conn2 = sqlite3.connect(':memory:')

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        conn2.execute("SELECT * FROM test")

    conn1.close()
    conn2.close()


def test_shared_memory_uri_sharing():
    """Verify that shared memory URIs DO share data."""
    conn1 = sqlite3.connect('file:testdb?mode=memory&cache=shared', uri=True)
    conn1.execute("CREATE TABLE test (id INT)")
    conn1.execute("INSERT INTO test VALUES (1)")
    conn1.commit()  # Commit so other connections can see changes

    # Second connection to same URI shares the database
    conn2 = sqlite3.connect('file:testdb?mode=memory&cache=shared', uri=True)
    result = conn2.execute("SELECT * FROM test").fetchall()

    assert result == [(1,)]

    conn1.close()
    conn2.close()


def test_different_namespaces_isolated():
    """Verify that different shared memory namespaces are isolated."""
    conn1 = sqlite3.connect('file:db1?mode=memory&cache=shared', uri=True)
    conn1.execute("CREATE TABLE test (id INT)")
    conn1.execute("INSERT INTO test VALUES (1)")

    conn2 = sqlite3.connect('file:db2?mode=memory&cache=shared', uri=True)

    # db2 should not have the test table from db1
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        conn2.execute("SELECT * FROM test")

    conn1.close()
    conn2.close()


def test_data_lost_when_all_connections_close():
    """Verify that shared memory data is lost when all connections close."""
    conn1 = sqlite3.connect('file:tempdb?mode=memory&cache=shared', uri=True)
    conn1.execute("CREATE TABLE test (id INT)")
    conn1.execute("INSERT INTO test VALUES (1)")
    conn1.commit()  # Commit so other connections can see changes

    conn2 = sqlite3.connect('file:tempdb?mode=memory&cache=shared', uri=True)
    result = conn2.execute("SELECT * FROM test").fetchall()
    assert result == [(1,)]

    # Close all connections
    conn1.close()
    conn2.close()

    # Open new connection - database is recreated empty
    conn3 = sqlite3.connect('file:tempdb?mode=memory&cache=shared', uri=True)

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        conn3.execute("SELECT * FROM test")

    conn3.close()


def test_anchor_connection_keeps_data_alive():
    """Verify that keeping one connection open preserves the data."""
    # Create anchor connection
    anchor = sqlite3.connect('file:persistent?mode=memory&cache=shared', uri=True)
    # Drop table if it exists from a previous test run
    anchor.execute("DROP TABLE IF EXISTS test")
    anchor.execute("CREATE TABLE test (id INT)")
    anchor.execute("INSERT INTO test VALUES (1)")
    anchor.commit()  # Commit so other connections can see changes

    # Open and close other connections
    conn1 = sqlite3.connect('file:persistent?mode=memory&cache=shared', uri=True)
    result = conn1.execute("SELECT * FROM test").fetchall()
    assert result == [(1,)]
    conn1.close()

    # Even after conn1 closes, data is still there because anchor is open
    conn2 = sqlite3.connect('file:persistent?mode=memory&cache=shared', uri=True)
    result = conn2.execute("SELECT * FROM test").fetchall()
    assert result == [(1,)]
    conn2.close()

    # Close anchor
    anchor.close()

    # Now data is gone
    conn3 = sqlite3.connect('file:persistent?mode=memory&cache=shared', uri=True)
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        conn3.execute("SELECT * FROM test")
    conn3.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
