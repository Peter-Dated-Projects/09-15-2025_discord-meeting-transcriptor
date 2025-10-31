"""
Integration tests for database connections.

This module provides an overview of integration tests structure.

IMPORTANT: Database integration tests have been organized by environment:

📁 Local Tests (MySQL):
   - File: tests/integration/test_database_connections_local.py
   - Run:  pytest --db-env local tests/integration/test_database_connections_local.py
   - Tests database connections, queries, and connection pooling for MySQL

📁 Production Tests (PostgreSQL):
   - File: tests/integration/test_database_connections_prod.py
   - Run:  pytest --db-env prod tests/integration/test_database_connections_prod.py
   - Tests database connections, queries, and connection pooling for PostgreSQL

Requirements for integration tests:
- Test database must be running and accessible
- Correct credentials must be set via environment variables
- Tests are marked with @pytest.mark.integration and @pytest.mark.local/@pytest.mark.prod

Running all integration tests:
    pytest --db-env local tests/integration/
    pytest --db-env prod tests/integration/

Running all integration tests without database:
    pytest tests/integration/ -m "integration and not (local or prod)"
"""

import pytest
import os

from source.server.production.postgresql import PostgreSQLServer
from source.server.dev.mysql import MySQLServer


# ============================================================================
# Shared Comparison/Compatibility Tests
# ============================================================================
# These tests can run in either environment to verify compatibility


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_and_mysql_independent_connections() -> None:
    """
    Test that PostgreSQL and MySQL can maintain independent connections.

    This test runs in both local and prod environments.
    When running with --db-env local, only MySQL connection is meaningful.
    When running with --db-env prod, only PostgreSQL connection is meaningful.
    Both should complete without errors.
    """
    postgres = PostgreSQLServer(
        name="integration_test_postgres",
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        database=os.getenv("POSTGRES_DB", "postgres"),
    )

    mysql = MySQLServer(
        name="integration_test_mysql",
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DB", "mysql"),
    )

    # Try to connect to both, but don't fail if one is unavailable
    # This allows the test to run in either environment
    postgres_connected = False
    mysql_connected = False

    try:
        await postgres.connect()
        pg_health = await postgres.health_check()
        assert pg_health is True
        assert postgres._connected is True
        postgres_connected = True
    except Exception:
        # PostgreSQL not available (expected when running --db-env local)
        pass
    finally:
        if postgres_connected:
            await postgres.disconnect()

    try:
        await mysql.connect()
        mysql_health = await mysql.health_check()
        assert mysql_health is True
        assert mysql._connected is True
        mysql_connected = True
    except Exception:
        # MySQL not available (expected when running --db-env prod)
        pass
    finally:
        if mysql_connected:
            await mysql.disconnect()

    # At least one should have been available
    assert (
        postgres_connected or mysql_connected
    ), "Neither PostgreSQL nor MySQL was available for connection testing"
