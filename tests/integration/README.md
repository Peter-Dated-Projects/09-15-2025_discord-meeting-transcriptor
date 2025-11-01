# Integration Tests

Integration tests verify that the application works correctly with real database instances.

## Structure

Integration tests are separated by environment:

### Local Tests (MySQL)
- **File**: `test_database_connections_local.py`
- **Marker**: `@pytest.mark.local`
- **Requirements**: Running MySQL instance
- **Run with**: `pytest --db-env local test_database_connections_local.py`

Tests:
- ✅ MySQL real connection
- ✅ MySQL query execution
- ✅ MySQL connection failure handling
- ✅ MySQL connection pool properties
- ✅ MySQL multiple sequential queries

### Production Tests (PostgreSQL)
- **File**: `test_database_connections_prod.py`
- **Marker**: `@pytest.mark.prod`
- **Requirements**: Running PostgreSQL instance
- **Run with**: `pytest --db-env prod test_database_connections_prod.py`

Tests:
- ✅ PostgreSQL real connection
- ✅ PostgreSQL query execution
- ✅ PostgreSQL connection failure handling
- ✅ PostgreSQL connection pool properties
- ✅ PostgreSQL multiple sequential queries
- ✅ PostgreSQL transaction support

### Shared Tests
- **File**: `test_database_connections.py`
- **Purpose**: Compatibility and cross-environment tests
- **Behavior**: Works in both `--db-env local` and `--db-env prod` modes

## Running Integration Tests

### Local environment (MySQL)
```bash
# Run all local integration tests
pytest --db-env local tests/integration/test_database_connections_local.py

# Run with helper script
./run_tests_env.sh local tests/integration/test_database_connections_local.py

# Run specific test
pytest --db-env local tests/integration/test_database_connections_local.py::test_mysql_real_connection
```

### Production environment (PostgreSQL)
```bash
# Run all prod integration tests
pytest --db-env prod tests/integration/test_database_connections_prod.py

# Run with helper script
./run_tests_env.sh prod tests/integration/test_database_connections_prod.py

# Run specific test
pytest --db-env prod tests/integration/test_database_connections_prod.py::test_postgres_real_connection
```

### All integration tests in an environment
```bash
# Run all integration tests in local environment
pytest --db-env local tests/integration/ -m integration

# Run all integration tests in prod environment
pytest --db-env prod tests/integration/ -m integration
```

## Prerequisites

### Local (MySQL) Integration Tests
Requires a running MySQL instance with environment variables:
```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=<your_password>
MYSQL_DB=mysql
```

Or using Docker:
```bash
docker-compose -f docker-compose.local.yml up mysql
```

### Production (PostgreSQL) Integration Tests
Requires a running PostgreSQL instance with environment variables:
```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<your_password>
POSTGRES_DB=postgres
```

Or using Docker:
```bash
docker-compose -f docker-compose.local.yml up postgres
```

## Test Markers

All integration tests use markers for filtering:

- `@pytest.mark.integration`: Marks the test as an integration test
- `@pytest.mark.local`: Marks the test for local (MySQL) environment
- `@pytest.mark.prod`: Marks the test for production (PostgreSQL) environment
- `@pytest.mark.asyncio`: Marks the test as async

Run only local integration tests:
```bash
pytest --db-env local tests/integration/ -m "integration and local"
```

Run only prod integration tests:
```bash
pytest --db-env prod tests/integration/ -m "integration and prod"
```

## Troubleshooting

### "Connect call failed" errors
The database instance is not running or not reachable. Start the appropriate database:

**MySQL**:
```bash
docker-compose -f docker-compose.local.yml up mysql
```

**PostgreSQL**:
```bash
docker-compose -f docker-compose.local.yml up postgres
```

### Connection credentials error
Verify that environment variables match your database configuration:

**For MySQL**:
```bash
echo $MYSQL_HOST $MYSQL_PORT $MYSQL_USER $MYSQL_PASSWORD $MYSQL_DB
```

**For PostgreSQL**:
```bash
echo $POSTGRES_HOST $POSTGRES_PORT $POSTGRES_USER $POSTGRES_PASSWORD $POSTGRES_DB
```

### Environment not specified
Always include `--db-env local` or `--db-env prod`:

```bash
# ❌ Wrong
pytest tests/integration/

# ✅ Correct
pytest --db-env local tests/integration/
pytest --db-env prod tests/integration/
```

## Best Practices

1. **Run environment-specific tests**: Always use the corresponding `--db-env` flag
2. **Check database availability**: Start the database before running integration tests
3. **Use fixtures when possible**: Leverage `database_connection` fixture for new tests
4. **Mark tests appropriately**: Use `@pytest.mark.local` or `@pytest.mark.prod`
5. **Clean up after tests**: All tests should disconnect from the database in finally blocks
6. **Document database-specific features**: Add comments for features unique to MySQL or PostgreSQL
